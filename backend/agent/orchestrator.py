import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from backend.agent import nodes
from backend.agent.state import AgentState, create_initial_state
from backend.config import settings
from backend.services.lark_bot_service import (
    build_delivery_card,
    build_progress_card,
    lark_bot_service,
)
from backend.services.llm_service import revise_deck_spec, revise_doc_content
from backend.services.llm_service import generate_qa, generate_rehearsal, revise_targeted_slides, summarize_im_context
from backend.services.rocket_chat_service import (
    fetch_im_context,
    post_delivery_to_im,
    rocket_chat_service,
)
from backend.services.sync_service import EventType, sync_service
from backend.tools.tool_factory import ToolFactory

logger = logging.getLogger(__name__)


STEP_PROGRESS = {
    "receive_input": 0.05,
    "parse_intent": 0.12,
    "plan_workflow": 0.2,
    "extract_tasks": 0.3,
    "generate_doc": 0.5,
    "generate_canvas": 0.6,
    "generate_slides": 0.7,
    "generate_rehearsal": 0.78,
    "prepare_delivery": 0.83,
    "confirm_or_modify": 0.88,
    "deliver_result": 1.0,
}


class AgentOrchestrator:
    def __init__(self):
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._tools = ToolFactory.get_all_langchain_tools()
        self._workflow = self._build_workflow()

    def _build_workflow(self):
        """构建 LangGraph 条件工作流。"""
        graph = StateGraph(AgentState)

        graph.add_node("receive_input", nodes.receive_input)
        graph.add_node("parse_intent", nodes.parse_intent)
        graph.add_node("plan_workflow", nodes.plan_workflow)
        graph.add_node("extract_tasks", nodes.extract_tasks)
        graph.add_node("generate_doc", nodes.generate_doc)
        graph.add_node("generate_canvas", nodes.generate_canvas)
        graph.add_node("generate_slides", nodes.generate_slides)
        graph.add_node("confirm_or_modify", nodes.confirm_or_modify)
        graph.add_node("deliver_result", nodes.deliver_result)

        graph.add_edge(START, "receive_input")
        graph.add_edge("receive_input", "parse_intent")
        graph.add_edge("parse_intent", "plan_workflow")
        graph.add_edge("plan_workflow", "extract_tasks")

        graph.add_conditional_edges(
            "extract_tasks",
            self._route_after_extract,
            {
                "generate_doc": "generate_doc",
                "generate_canvas": "generate_canvas",
                "generate_slides": "generate_slides",
                "confirm_or_modify": "confirm_or_modify",
                "deliver_result": "deliver_result",
            },
        )
        graph.add_conditional_edges(
            "generate_doc",
            self._route_after_doc,
            {
                "generate_canvas": "generate_canvas",
                "generate_slides": "generate_slides",
                "confirm_or_modify": "confirm_or_modify",
                "deliver_result": "deliver_result",
            },
        )
        graph.add_conditional_edges(
            "generate_canvas",
            self._route_after_canvas,
            {
                "generate_slides": "generate_slides",
                "confirm_or_modify": "confirm_or_modify",
                "deliver_result": "deliver_result",
            },
        )
        graph.add_conditional_edges(
            "generate_slides",
            self._route_after_slides,
            {
                "confirm_or_modify": "confirm_or_modify",
                "deliver_result": "deliver_result",
            },
        )
        graph.add_edge("confirm_or_modify", "deliver_result")
        graph.add_edge("deliver_result", END)

        return graph.compile()

    @staticmethod
    def _route_after_extract(state: AgentState) -> str:
        if state.get("error"):
            return "deliver_result"
        if nodes.needs_doc(state):
            return "generate_doc"
        if nodes.needs_canvas(state):
            return "generate_canvas"
        if nodes.needs_deck(state):
            return "generate_slides"
        return "confirm_or_modify"

    @staticmethod
    def _route_after_doc(state: AgentState) -> str:
        if state.get("error"):
            return "deliver_result"
        if nodes.needs_canvas(state):
            return "generate_canvas"
        if nodes.needs_deck(state):
            return "generate_slides"
        return "confirm_or_modify"

    @staticmethod
    def _route_after_canvas(state: AgentState) -> str:
        if state.get("error"):
            return "deliver_result"
        if nodes.needs_deck(state):
            return "generate_slides"
        return "confirm_or_modify"

    @staticmethod
    def _route_after_slides(state: AgentState) -> str:
        if state.get("error"):
            return "deliver_result"
        return "confirm_or_modify"

    def register_callback(self, event: str, callback: Callable):
        self._callbacks[event].append(callback)

    async def trigger_callback(self, event: str, data: Dict[str, Any]):
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    await callback(data)
                except Exception as exc:
                    logger.error("Callback error for %s: %s", event, str(exc))

    async def execute_workflow(
        self,
        session_id: str,
        task_id: str,
        intent: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        presentation_scene: Optional[str] = None,
        ws_sender: Callable = None,
    ) -> AgentState:
        context_messages: List[Dict[str, Any]] = []
        if room_id and settings.IM_PROVIDER == "rocket_chat":
            try:
                context_messages = await fetch_im_context(room_id, limit=20)
            except Exception as exc:
                logger.warning("Failed to fetch Rocket.Chat context for room %s: %s", room_id, str(exc))

        state = create_initial_state(
            session_id,
            task_id,
            intent,
            user_id=user_id,
            room_id=room_id,
            context_messages=context_messages,
        )
        state["presentation_scene"] = presentation_scene

        current_state: AgentState = state
        try:
            current_state = await self._run_plan_and_execute(current_state, room_id, task_id, ws_sender)
        except Exception as exc:
            logger.exception("Plan-and-Execute workflow failed for task %s", task_id)
            current_state["error"] = str(exc)
            current_state["status"] = "failed"
            current_state["updated_at"] = datetime.utcnow().isoformat()

        completed_message = {
            "type": "task.completed" if current_state.get("status") == "completed" else "task.failed",
            "task_id": task_id,
            "result": current_state.get("result"),
            "status": current_state.get("status"),
            "error": current_state.get("error"),
            "timestamp": current_state.get("updated_at"),
            "updated_at": current_state.get("updated_at"),
        }
        if ws_sender:
            await ws_sender(completed_message)
        await self.trigger_callback("completed", completed_message)
        await self._push_completion_to_im(room_id, current_state)

        # SyncService broadcast completion
        try:
            await sync_service.broadcast_delivery(
                session_id=current_state.get("session_id", ""),
                task_id=current_state["task_id"],
                delivery=current_state.get("result") or {},
            )
        except Exception:
            pass

        return current_state

    async def _run_plan_and_execute(
        self,
        state: AgentState,
        room_id: Optional[str],
        task_id: str,
        ws_sender: Callable = None,
    ) -> AgentState:
        """Run the Pilot/Planner nodes, then execute the generated agent task graph."""
        for node_name, node_fn in (
            ("receive_input", nodes.receive_input),
            ("parse_intent", nodes.parse_intent),
            ("plan_workflow", nodes.plan_workflow),
            ("extract_tasks", nodes.extract_tasks),
        ):
            state = await node_fn(state)
            await self._publish_progress(room_id, task_id, state, ws_sender)
            if state.get("error"):
                return await nodes.deliver_result(state)

        state = await self._execute_agent_plan(state, room_id, task_id, ws_sender)
        if state.get("error"):
            state = await nodes.deliver_result(state)
            await self._publish_progress(room_id, task_id, state, ws_sender)
            return state

        state = await nodes.confirm_or_modify(state)
        await self._publish_progress(room_id, task_id, state, ws_sender)

        state = await nodes.deliver_result(state)
        await self._publish_progress(room_id, task_id, state, ws_sender)
        return state

    async def _execute_agent_plan(
        self,
        state: AgentState,
        room_id: Optional[str],
        task_id: str,
        ws_sender: Callable = None,
    ) -> AgentState:
        plan = state.get("agent_plan") or {}
        tasks = [dict(task) for task in plan.get("tasks", [])]
        if not tasks:
            state["agent_plan"] = nodes._build_agent_plan(state)
            plan = state.get("agent_plan") or {}
            tasks = [dict(task) for task in state["agent_plan"].get("tasks", [])]

        completed = set(state.get("completed_task_ids", []))
        task_results = dict(state.get("task_results") or {})
        artifacts = dict(state.get("artifacts") or {})
        total = max(len(tasks), 1)

        while len(completed) < len(tasks):
            ready_tasks = [
                task for task in tasks
                if task["id"] not in completed
                and all(dep in completed for dep in task.get("depends_on", []))
            ]
            if not ready_tasks:
                state["error"] = "Agent plan has unresolved dependencies or a cycle."
                return state

            for task in ready_tasks:
                state = self._mark_agent_task_started(state, task, len(completed), total)
                await self._publish_progress(room_id, task_id, state, ws_sender)

                state = await self._run_agent_task(state, task)
                if state.get("error"):
                    task["status"] = "failed"
                    task_results[task["id"]] = {"status": "failed", "error": state.get("error")}
                    state["task_results"] = task_results
                    return state

                task["status"] = "completed"
                completed.add(task["id"])
                state["completed_task_ids"] = list(completed)
                task_results[task["id"]] = self._task_result_payload(state, task)
                artifacts.update(self._artifact_refs(state))
                state["task_results"] = task_results
                state["artifacts"] = artifacts
                state["agent_plan"] = {**plan, "tasks": tasks, "artifacts": sorted(artifacts.keys())}
                state["progress"] = min(0.84, 0.3 + (len(completed) / total) * 0.5)
                state["updated_at"] = datetime.utcnow().isoformat()

        return state

    def _mark_agent_task_started(
        self,
        state: AgentState,
        task: Dict[str, Any],
        completed_count: int,
        total: int,
    ) -> AgentState:
        state["active_agent"] = task.get("agent")
        state["current_step"] = task.get("step") or task.get("action") or "execute_agent_task"
        state["progress"] = STEP_PROGRESS.get(
            state["current_step"],
            min(0.82, 0.3 + (completed_count / max(total, 1)) * 0.5),
        )
        state["updated_at"] = datetime.utcnow().isoformat()
        state.setdefault("messages", []).append({
            "role": "system",
            "content": f"{task.get('agent')} is executing {task.get('action')}",
            "timestamp": state["updated_at"],
            "step": state["current_step"],
            "agent": task.get("agent"),
            "agent_task_id": task.get("id"),
        })
        return state

    async def _run_agent_task(self, state: AgentState, task: Dict[str, Any]) -> AgentState:
        agent = task.get("agent")
        if agent == "im_context_agent":
            summary = await summarize_im_context(
                messages=state.get("context_messages", []),
                current_intent=state.get("intent", ""),
            )
            state["im_context_summary"] = summary
            context_count = summary.get("source_message_count", len(state.get("context_messages") or []))
            state.setdefault("messages", []).append({
                "role": "assistant",
                "content": f"IM Context Agent extracted {len(summary.get('requirements', []))} requirements, {len(summary.get('decisions', []))} decisions, and {len(summary.get('todos', []))} todos from {context_count} messages.",
                "timestamp": datetime.utcnow().isoformat(),
                "step": task.get("step"),
                "agent": agent,
                "summary": summary,
            })
            return state
        if agent == "doc_agent":
            return await nodes.generate_doc(state)
        if agent == "canvas_agent":
            return await nodes.generate_canvas(state)
        if agent == "deck_agent":
            return await nodes.generate_slides(state)
        if agent == "rehearsal_agent":
            if not state.get("slides_content"):
                state["error"] = "Rehearsal Agent requires slides_content."
                return state
            state.setdefault("messages", []).append({
                "role": "assistant",
                "content": "Rehearsal Agent prepared speaker notes and Q&A from the deck.",
                "timestamp": datetime.utcnow().isoformat(),
                "step": task.get("step"),
                "agent": agent,
            })
            return state
        if agent == "delivery_agent":
            return state

        state["error"] = f"Unknown agent: {agent}"
        return state

    @staticmethod
    def _artifact_refs(state: AgentState) -> Dict[str, Any]:
        artifacts: Dict[str, Any] = {}
        if state.get("im_context_summary"):
            artifacts["im_context"] = {
                "summary": state["im_context_summary"].get("summary"),
                "requirements_count": len(state["im_context_summary"].get("requirements", [])),
                "decisions_count": len(state["im_context_summary"].get("decisions", [])),
            }
        if state.get("doc_content"):
            artifacts["document"] = {
                "doc_id": state["doc_content"].get("doc_id"),
                "title": state["doc_content"].get("title"),
            }
        if state.get("canvas_content"):
            artifacts["canvas"] = {
                "canvas_id": state["canvas_content"].get("canvas_id"),
                "title": state["canvas_content"].get("title"),
            }
        if state.get("slides_content"):
            artifacts["deck"] = {
                "slide_id": state["slides_content"].get("slide_id"),
                "title": state["slides_content"].get("title"),
            }
            if state["slides_content"].get("rehearsal") or state["slides_content"].get("qa"):
                artifacts["rehearsal"] = {
                    "qa_count": len(state["slides_content"].get("qa", [])),
                }
        return artifacts

    def _task_result_payload(self, state: AgentState, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "status": "completed",
            "agent": task.get("agent"),
            "action": task.get("action"),
            "artifacts": self._artifact_refs(state),
            "completed_at": datetime.utcnow().isoformat(),
        }

    def _next_step_after(self, node_name: str, state: AgentState) -> Optional[str]:
        """预测下一节点，用于长耗时节点开始前先刷新前端状态。"""
        if node_name == "receive_input":
            return "parse_intent"
        if node_name == "parse_intent":
            return "plan_workflow"
        if node_name == "plan_workflow":
            return "extract_tasks"
        if node_name == "extract_tasks":
            return self._route_after_extract(state)
        if node_name == "generate_doc":
            return self._route_after_doc(state)
        if node_name == "generate_canvas":
            return self._route_after_canvas(state)
        if node_name == "generate_slides":
            return self._route_after_slides(state)
        if node_name == "confirm_or_modify":
            return "deliver_result"
        return None

    async def _publish_step_start(
        self,
        task_id: str,
        state: AgentState,
        ws_sender: Callable = None,
    ) -> None:
        """只给前端和同步通道发送“下一步已开始”，避免 IM 端被刷屏。"""
        progress_message = {
            "type": "task.progress",
            "task_id": task_id,
            "step": state.get("current_step"),
            "message": f"Executing: {state.get('current_step')}",
            "progress": state.get("progress"),
            "status": state.get("status"),
            "timestamp": state.get("updated_at"),
            "updated_at": state.get("updated_at"),
        }
        if ws_sender:
            await ws_sender(progress_message)
        await self.trigger_callback("progress", progress_message)

        try:
            await sync_service.broadcast_task_progress(
                session_id=state.get("session_id", ""),
                task_id=task_id,
                step=state.get("current_step", ""),
                progress=state.get("progress", 0),
                message=f"Executing: {state.get('current_step')}",
            )
        except Exception:
            pass

    async def _publish_progress(
        self,
        room_id: Optional[str],
        task_id: str,
        state: AgentState,
        ws_sender: Callable = None,
    ) -> None:
        progress_message = {
            "type": "task.progress",
            "task_id": task_id,
            "step": state.get("current_step"),
            "message": f"Executing: {state.get('current_step')}",
            "progress": state.get("progress"),
            "status": state.get("status"),
            "timestamp": state.get("updated_at"),
            "updated_at": state.get("updated_at"),
        }
        if ws_sender:
            await ws_sender(progress_message)
        await self.trigger_callback("progress", progress_message)
        await self._push_progress_to_im(room_id, task_id, state)

        # SyncService broadcast for multi-tab consistency
        try:
            await sync_service.broadcast_task_progress(
                session_id=state.get("session_id", ""),
                task_id=task_id,
                step=state.get("current_step", ""),
                progress=state.get("progress", 0),
                message=f"Executing: {state.get('current_step')}",
            )
        except Exception:
            pass

    async def _push_progress_to_im(self, room_id: Optional[str], task_id: str, state: AgentState) -> None:
        if not room_id:
            return

        try:
            if settings.IM_PROVIDER == "lark":
                if not lark_bot_service.is_configured:
                    return
                card = build_progress_card(task_id, state.get("current_step", ""), state.get("progress", 0))
                result = await lark_bot_service.send_card(room_id, card)
                if not result.get("success"):
                    logger.warning("Failed to send Lark progress card: %s", result.get("error"))
                    # 卡片发送失败时退回普通文本，保证飞书侧仍能看到任务进展。
                    text = (
                        "Agent-Pilot 任务进行中\n"
                        f"进度: {int(float(state.get('progress', 0)) * 100)}%\n"
                        f"步骤: {state.get('current_step')}\n"
                        f"任务: {task_id}"
                    )
                    text_result = await lark_bot_service.send_text(room_id, text)
                    if not text_result.get("success"):
                        logger.warning("Failed to send Lark progress text fallback: %s", text_result.get("error"))
                return

            if not rocket_chat_service.is_configured:
                return
            await rocket_chat_service.send_progress_update(
                room_id=room_id,
                task_id=task_id,
                step=state.get("current_step"),
                progress=state.get("progress", 0),
                message=f"Executing: {state.get('current_step')}",
            )

            if state.get("current_step") == "plan_workflow" and state.get("workflow_plan"):
                await rocket_chat_service.send_plan_card(room_id, state["workflow_plan"])
        except Exception as exc:
            logger.warning("Failed to push IM progress for task %s: %s", task_id, str(exc))

    async def _push_completion_to_im(self, room_id: Optional[str], state: AgentState) -> None:
        if not room_id or not state.get("result"):
            return

        try:
            if settings.IM_PROVIDER == "lark":
                if not lark_bot_service.is_configured:
                    return
                result = state.get("result", {})
                doc_info = result.get("document") or result.get("doc") or {}
                slides_info = result.get("slides") or result.get("deck") or {}
                lark_doc_id = None
                if isinstance(doc_info, dict):
                    # 只有真实飞书文档才允许展示“已在飞书中编辑”按钮，避免本地 doc_id 被误当成飞书 doc_id。
                    lark_doc_id = doc_info.get("lark_doc_id")
                    if not lark_doc_id and doc_info.get("provider") == "lark_docx":
                        lark_doc_id = doc_info.get("doc_id")

                card = build_delivery_card(
                    task_id=state["task_id"],
                    doc_title=doc_info.get("title") if isinstance(doc_info, dict) else None,
                    doc_url=doc_info.get("doc_url") if isinstance(doc_info, dict) else None,
                    slides_title=slides_info.get("title") if isinstance(slides_info, dict) else None,
                    slides_count=slides_info.get("slides_count", 0) if isinstance(slides_info, dict) else 0,
                    chat_id=room_id,
                    lark_doc_id=lark_doc_id,
                )
                card_result = await lark_bot_service.send_card(room_id, card)
                if not card_result.get("success"):
                    await lark_bot_service.send_text(room_id, self._build_lark_delivery_text(state))

                await self._push_lark_delivery_files(room_id, state)
                await self._push_lark_rehearsal_summary(room_id, state)
                return

            if not rocket_chat_service.is_configured:
                return
            await post_delivery_to_im(room_id, state["result"])
        except Exception as exc:
            logger.warning("Failed to post IM delivery for task %s: %s", state.get("task_id"), str(exc))

    def _build_lark_delivery_text(self, state: AgentState) -> str:
        result = state.get("result") or {}
        lines = ["Agent-Pilot 任务完成"]

        document = result.get("document") or result.get("doc")
        if isinstance(document, dict):
            title = document.get("title") or "文档"
            lines.append(f"文档: {title}")

        slides = result.get("slides") or result.get("deck")
        if isinstance(slides, dict):
            title = slides.get("title") or "演示稿"
            lines.append(f"PPT: {title}")
            if slides.get("file_path"):
                lines.append(f"文件: {slides.get('file_path')}")

        if result.get("canvas"):
            lines.append("流程图/画布: 已生成")

        lines.append(f"任务 ID: {state['task_id']}")
        return "\n".join(lines)

    async def _push_lark_delivery_files(self, room_id: str, state: AgentState) -> None:
        result = state.get("result") or {}
        slides = result.get("slides") or result.get("deck")
        if not isinstance(slides, dict):
            return

        file_path = slides.get("file_path")
        if not file_path:
            return

        title = slides.get("title") or f"Agent-Pilot-{state['task_id']}"
        file_name = title if str(title).lower().endswith((".ppt", ".pptx")) else f"{title}.pptx"

        try:
            upload_result = await lark_bot_service.send_local_file(
                room_id,
                file_path=file_path,
                file_name=file_name,
            )
            if not upload_result.get("success"):
                logger.warning(
                    "Failed to send Lark PPT file for task %s: %s",
                    state["task_id"],
                    upload_result.get("error") or upload_result,
                )
        except Exception as exc:
            logger.warning("Failed to upload/send Lark PPT for task %s: %s", state["task_id"], str(exc))

    async def _push_lark_rehearsal_summary(self, room_id: str, state: AgentState) -> None:
        result = state.get("result") or {}
        slides = result.get("slides") or result.get("deck")
        if not isinstance(slides, dict):
            return

        rehearsal = slides.get("rehearsal") or {}
        qa_items = slides.get("qa") or []
        rehearsal_slides = rehearsal.get("slides") if isinstance(rehearsal, dict) else []
        if not rehearsal_slides and not qa_items:
            return

        lines = ["演练摘要"]
        for item in (rehearsal_slides or [])[:3]:
            slide_no = int(item.get("slide_index", 0)) + 1
            notes = str(item.get("speaker_notes") or "").strip()
            if notes:
                lines.append(f"- 第 {slide_no} 页：{notes[:80]}")
        if qa_items:
            lines.append("\nTop Q&A")
            for item in qa_items[:3]:
                question = str(item.get("question") or "").strip()
                answer = str(item.get("answer") or "").strip()
                if question:
                    lines.append(f"- Q：{question}")
                if answer:
                    lines.append(f"  A：{answer[:100]}")

        try:
            await lark_bot_service.send_text(room_id, "\n".join(lines))
        except Exception as exc:
            logger.warning("Failed to send Lark rehearsal summary for task %s: %s", state["task_id"], str(exc))

    async def handle_user_feedback(
        self,
        session_id: str,
        task_id: str,
        feedback: str,
        base_result: Dict[str, Any],
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        ws_sender: Callable = None,
    ) -> AgentState:
        logger.info("Handling feedback for task %s: %s", task_id, feedback)
        # 兼容早期或异常任务记录，避免反馈修改时把空结果当作字典读取。
        base_result = base_result or {}

        state = create_initial_state(
            session_id=session_id,
            task_id=task_id,
            intent=feedback,
            user_id=user_id,
            room_id=room_id,
            context_messages=[],
        )
        state["status"] = "running"
        state["messages"] = []
        state["progress"] = 0.0

        async def publish(step: str, progress: float, message: str) -> None:
            state["current_step"] = step
            state["progress"] = progress
            state["updated_at"] = datetime.utcnow().isoformat()
            await self._publish_progress(room_id, task_id, state, ws_sender)
            state["messages"].append(
                {
                    "role": "assistant",
                    "content": message,
                    "timestamp": state["updated_at"],
                    "step": step,
                }
            )

        try:
            await publish("confirm_or_modify", 0.1, f"Processing feedback: {feedback}")

            base_doc = base_result.get("document") or base_result.get("doc") or {}
            base_slides = base_result.get("slides") or base_result.get("deck") or {}
            # 旧版本结果里这些字段可能为空或不是字典，统一归一化后再走局部修订。
            base_doc = base_doc if isinstance(base_doc, dict) else {}
            base_slides = base_slides if isinstance(base_slides, dict) else {}
            should_update_doc = self._should_update_doc(feedback, base_doc, base_slides)
            should_update_slides = self._should_update_slides(feedback, base_doc, base_slides)
            wants_rehearsal = self._wants_rehearsal(feedback)

            if isinstance(base_doc, dict) and should_update_doc:
                await publish("generate_doc", 0.4, "Regenerating document with feedback")
                title = base_doc.get("title") or f"Task {task_id} document"
                revised_doc = await revise_doc_content(
                    title=title,
                    original_content=base_doc.get("content") or base_doc.get("preview") or "",
                    feedback=feedback,
                )
                doc_result = await ToolFactory.invoke_tool(
                    "DocTool",
                    {
                        "action": "create_doc",
                        "task_id": task_id,
                        "title": title,
                        "content": revised_doc,
                    },
                )
                if not doc_result.get("success"):
                    raise RuntimeError(doc_result.get("error") or "Failed to regenerate document")
                state["doc_content"] = {
                    "doc_id": doc_result.get("doc_id"),
                    "title": title,
                    "content": revised_doc,
                    "content_preview": revised_doc[:500] + "..." if len(revised_doc) > 500 else revised_doc,
                    "doc_url": doc_result.get("doc_url"),
                }
            elif isinstance(base_doc, dict) and base_doc:
                state["doc_content"] = {
                    "doc_id": base_doc.get("doc_id"),
                    "title": base_doc.get("title"),
                    "content": base_doc.get("content"),
                    "content_preview": base_doc.get("preview") or base_doc.get("content"),
                    "doc_url": base_doc.get("doc_url"),
                }

            if isinstance(base_slides, dict) and (should_update_slides or wants_rehearsal):
                await publish("generate_slides", 0.75, "Regenerating presentation with feedback")
                slides = base_slides.get("slides") or []
                target_indexes = self._extract_slide_indexes(feedback, len(slides))
                title = base_slides.get("title") or (state.get("doc_content") or {}).get("title") or f"Task {task_id} deck"
                doc_content = (state.get("doc_content") or {}).get("content", "")
                metadata = dict(base_slides.get("metadata") or {})

                if should_update_slides:
                    if not slides:
                        raise RuntimeError("未找到上一版 PPT 页面内容，无法执行局部修改。请重新生成 PPT 后再修改。")
                    if target_indexes:
                        revision = await revise_targeted_slides(
                            title=title,
                            original_slides=slides,
                            feedback=feedback,
                            target_slide_indexes=target_indexes,
                            audience=base_slides.get("audience") or "management",
                            doc_content=doc_content,
                        )
                        if revision.get("global_change") or not revision.get("revised_slides"):
                            # 用户已经明确指定页码时，不能让模型把局部反馈升级成整套重写。
                            logger.warning(
                                "Targeted slide revision requested global/empty change for task %s; forcing local patch",
                                task_id,
                            )
                            revision = {
                                "target_slide_indexes": target_indexes,
                                "global_change": False,
                                "summary": "Applied feedback locally to target slides.",
                                "revised_slides": self._fallback_targeted_slides(slides, target_indexes, feedback),
                            }
                        revised_slides = self._merge_revised_slides(slides, revision)
                        revised_spec = self._build_deck_spec(title, base_slides, revised_slides, metadata)
                    else:
                        revised_spec = await revise_deck_spec(
                            title=title,
                            original_slides=slides,
                            feedback=feedback,
                            audience=base_slides.get("audience") or "management",
                            doc_content=doc_content,
                        )
                        target_indexes = list(range(len(slides)))

                    if not revised_spec.get("slides") and slides:
                        # 模型偶尔会返回自然语言拒绝或空 JSON，不能让空页面覆盖上一版 PPT。
                        logger.warning("Deck revision returned empty slides for task %s; keeping previous slides", task_id)
                        revised_spec = self._build_deck_spec(title, base_slides, slides, metadata)

                    metadata = self._updated_slide_metadata(
                        previous=metadata,
                        feedback=feedback,
                        target_indexes=target_indexes,
                        old_file_path=base_slides.get("file_path"),
                        mode="targeted" if target_indexes and len(target_indexes) < len(slides) else "global",
                    )
                    revised_spec["metadata"] = {**(revised_spec.get("metadata") or {}), **metadata}
                    result = await ToolFactory.invoke_tool(
                        "PPTTool",
                        {
                            "action": "create_slides",
                            "task_id": task_id,
                            "title": revised_spec.get("title"),
                            "slides": revised_spec.get("slides", []),
                            "deck_spec": revised_spec,
                        },
                    )
                    if not result.get("success"):
                        raise RuntimeError(result.get("error") or "Failed to regenerate slides")
                    file_path = result.get("download_url") or result.get("file_path")
                    final_revised_spec = result.get("deck_spec") or revised_spec
                else:
                    revised_spec = self._build_deck_spec(title, base_slides, slides, metadata)
                    file_path = base_slides.get("file_path")
                    final_revised_spec = revised_spec

                if wants_rehearsal:
                    rehearsal = await generate_rehearsal(final_revised_spec)
                    qa = await generate_qa(final_revised_spec, rehearsal)
                    qa_items = qa.get("items", [])
                else:
                    # 普通单页内容微调不重算演练稿和 Q&A，避免一次小改触发多轮 LLM。
                    rehearsal = base_slides.get("rehearsal")
                    qa_items = base_slides.get("qa", [])
                state["slides_content"] = {
                    "slide_id": result.get("slide_id") if should_update_slides else base_slides.get("slide_id"),
                    "title": final_revised_spec.get("title"),
                    "slides": final_revised_spec.get("slides", []),
                    "file_path": file_path,
                    "theme": final_revised_spec.get("theme"),
                    "visual_profile": final_revised_spec.get("visual_profile") or (final_revised_spec.get("metadata", {}) or {}).get("visual_profile"),
                    "audience": final_revised_spec.get("audience"),
                    "duration_minutes": final_revised_spec.get("duration_minutes"),
                    "metadata": final_revised_spec.get("metadata", {}),
                    "rehearsal": rehearsal,
                    "qa": qa_items,
                    "feedback_history": final_revised_spec.get("metadata", {}).get("feedback_history", base_slides.get("feedback_history", [])),
                }
            elif isinstance(base_slides, dict) and base_slides:
                state["slides_content"] = {
                    "slide_id": base_slides.get("slide_id"),
                    "title": base_slides.get("title"),
                    "slides": base_slides.get("slides", []),
                    "file_path": base_slides.get("file_path"),
                    "theme": base_slides.get("theme"),
                    "audience": base_slides.get("audience"),
                    "duration_minutes": base_slides.get("duration_minutes"),
                    "metadata": base_slides.get("metadata", {}),
                    "rehearsal": base_slides.get("rehearsal"),
                    "qa": base_slides.get("qa", []),
                    "feedback_history": base_slides.get("feedback_history", []),
                }

            canvas_result = base_result.get("canvas")
            if isinstance(canvas_result, dict):
                # 画布不是本次反馈的目标时，只保留原画布引用。
                state["canvas_content"] = {"canvas_id": canvas_result.get("canvas_id")}

            state = await nodes.deliver_result(state)
            state["updated_at"] = datetime.utcnow().isoformat()

            completed_message = {
                "type": "task.completed" if state.get("status") == "completed" else "task.failed",
                "task_id": task_id,
                "result": state.get("result"),
                "status": state.get("status"),
                "error": state.get("error"),
                "timestamp": state.get("updated_at"),
                "updated_at": state.get("updated_at"),
            }
            if ws_sender:
                await ws_sender(completed_message)
            await self.trigger_callback("completed", completed_message)
            await self._push_completion_to_im(room_id, state)
            try:
                await sync_service.broadcast_delivery(
                    session_id=session_id,
                    task_id=task_id,
                    delivery=state.get("result") or {},
                )
            except Exception:
                pass
            return state
        except Exception as exc:
            logger.exception("Feedback handling failed for task %s", task_id)
            state["error"] = str(exc)
            state["status"] = "failed"
            state["updated_at"] = datetime.utcnow().isoformat()
            failed_message = {
                "type": "task.failed",
                "task_id": task_id,
                "result": None,
                "status": "failed",
                "error": state["error"],
                "timestamp": state["updated_at"],
                "updated_at": state["updated_at"],
            }
            if ws_sender:
                await ws_sender(failed_message)
            await self.trigger_callback("completed", failed_message)
            return state

    @staticmethod
    def _should_update_doc(feedback: str, base_doc: Dict[str, Any], base_slides: Dict[str, Any]) -> bool:
        text = feedback.lower()
        doc_markers = ["doc", "document", "文档", "需求", "prd", "说明", "总结"]
        slide_markers = ["ppt", "slide", "slides", "deck", "页", "第", "演示", "汇报"]
        if any(marker in text for marker in doc_markers):
            return True
        if any(marker in text for marker in slide_markers):
            return False
        return bool(base_doc) and not base_slides

    @staticmethod
    def _should_update_slides(feedback: str, base_doc: Dict[str, Any], base_slides: Dict[str, Any]) -> bool:
        text = feedback.lower()
        slide_markers = ["ppt", "slide", "slides", "deck", "页", "第", "演示", "汇报"]
        doc_markers = ["doc", "document", "文档", "需求", "prd", "说明", "总结"]
        rehearsal_markers = ["排练", "演练", "讲稿", "speaker", "notes", "q&a", "qa", "问答", "问题"]
        update_markers = ["改", "修改", "调整", "增加", "删除", "优化", "替换", "补充", "更新"]
        if any(marker in text for marker in rehearsal_markers) and not any(marker in text for marker in update_markers):
            return False
        if any(marker in text for marker in slide_markers):
            return True
        if any(marker in text for marker in doc_markers):
            return False
        return bool(base_slides)

    @staticmethod
    def _wants_rehearsal(feedback: str) -> bool:
        text = feedback.lower()
        markers = ["排练", "演练", "讲稿", "speaker", "notes", "q&a", "qa", "问答", "问题"]
        return any(marker in text for marker in markers)

    @classmethod
    def _extract_slide_indexes(cls, feedback: str, slides_count: int) -> List[int]:
        if slides_count <= 0:
            return []
        text = feedback.lower()
        values: List[int] = []
        patterns = [
            r"第\s*([0-9一二两三四五六七八九十百]+)\s*[页張张]",
            r"(?:slide|page|p)\s*#?\s*([0-9]+)",
            r"([0-9]+)\s*[页張张]",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, text, flags=re.IGNORECASE):
                parsed = cls._parse_slide_number(match)
                if parsed is not None:
                    values.append(parsed - 1)
        return sorted({index for index in values if 0 <= index < slides_count})

    @staticmethod
    def _parse_slide_number(value: Any) -> Optional[int]:
        text = str(value).strip()
        if text.isdigit():
            return int(text)
        digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if text in digits:
            return digits[text]
        if "十" in text:
            left, _, right = text.partition("十")
            tens = digits.get(left, 1) if left else 1
            ones = digits.get(right, 0) if right else 0
            return tens * 10 + ones
        return None

    @staticmethod
    def _merge_revised_slides(original_slides: List[Dict[str, Any]], revision: Dict[str, Any]) -> List[Dict[str, Any]]:
        merged = [dict(slide) for slide in original_slides]
        target_indexes = revision.get("target_slide_indexes") or []
        revised_slides = revision.get("revised_slides") or []
        for fallback_index, revised in zip(target_indexes, revised_slides):
            candidate = revised.get("index") if isinstance(revised, dict) else None
            index = int(candidate) if candidate in target_indexes else int(fallback_index)
            if 0 <= index < len(merged):
                merged[index] = {**merged[index], **dict(revised), "index": index}
        return merged

    @staticmethod
    def _fallback_targeted_slides(
        original_slides: List[Dict[str, Any]],
        target_indexes: List[int],
        feedback: str,
    ) -> List[Dict[str, Any]]:
        """当模型不稳定时，至少把反馈安全地落到目标页，不重写整套 PPT。"""
        revised_slides: List[Dict[str, Any]] = []
        for index in target_indexes:
            if not 0 <= index < len(original_slides):
                continue
            slide = dict(original_slides[index])
            slide["index"] = index
            bullets = list(slide.get("bullets") or [])
            if bullets:
                bullets.append(f"补充说明：{feedback}")
                slide["bullets"] = bullets
            else:
                content = str(slide.get("content") or "").strip()
                slide["content"] = f"{content}\n\n补充说明：{feedback}".strip()
            revised_slides.append(slide)
        return revised_slides

    @staticmethod
    def _build_deck_spec(
        title: str,
        base_slides: Dict[str, Any],
        slides: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "title": title,
            "audience": base_slides.get("audience") or "management",
            "duration_minutes": base_slides.get("duration_minutes") or max(len(slides), 1),
            "theme": base_slides.get("theme") or "business_blue",
            "metadata": metadata,
            "slides": [
                nodes._normalize_slide_for_frontend(slide, index)
                for index, slide in enumerate(slides)
            ],
        }

    @staticmethod
    def _updated_slide_metadata(
        previous: Dict[str, Any],
        feedback: str,
        target_indexes: List[int],
        old_file_path: Optional[str],
        mode: str,
    ) -> Dict[str, Any]:
        metadata = dict(previous or {})
        history = list(metadata.get("feedback_history") or [])
        versions = list(metadata.get("versions") or [])
        updated_at = datetime.utcnow().isoformat()
        history.append({
            "feedback": feedback,
            "target_slide_indexes": target_indexes,
            "target_slide_numbers": [index + 1 for index in target_indexes],
            "mode": mode,
            "created_at": updated_at,
        })
        if old_file_path:
            versions.append({
                "version": len(versions) + 1,
                "file_path": old_file_path,
                "created_at": updated_at,
            })
        metadata["feedback_history"] = history
        metadata["versions"] = versions
        metadata["revision_count"] = len(history)
        metadata["last_feedback_at"] = updated_at
        return metadata


agent_orchestrator = AgentOrchestrator()
