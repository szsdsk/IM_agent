import logging
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
from backend.services.rocket_chat_service import (
    fetch_im_context,
    post_delivery_to_im,
    rocket_chat_service,
)
from backend.services.sync_service import EventType, sync_service
from backend.tools.tool_factory import ToolFactory

logger = logging.getLogger(__name__)


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

        current_state: AgentState = state
        try:
            async for event in self._workflow.astream(state, stream_mode="updates"):
                for node_name, node_update in event.items():
                    if node_name == END:
                        continue
                    if isinstance(node_update, dict):
                        current_state = AgentState(**{**current_state, **node_update})
                    await self._publish_progress(room_id, task_id, current_state, ws_sender)
        except Exception as exc:
            logger.exception("LangGraph workflow failed for task %s", task_id)
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
                    # Fallback to text
                    text = (
                        "Agent-Pilot 任务进行中\n"
                        f"进度: {int(float(state.get('progress', 0)) * 100)}%\n"
                        f"步骤: {state.get('current_step')}\n"
                        f"任务: {task_id}"
                    )
                    await lark_bot_service.send_text(room_id, text)
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

                card = build_delivery_card(
                    task_id=state["task_id"],
                    doc_title=doc_info.get("title") if isinstance(doc_info, dict) else None,
                    doc_url=doc_info.get("doc_url") if isinstance(doc_info, dict) else None,
                    slides_title=slides_info.get("title") if isinstance(slides_info, dict) else None,
                    slides_count=slides_info.get("slides_count", 0) if isinstance(slides_info, dict) else 0,
                    chat_id=room_id,
                )
                card_result = await lark_bot_service.send_card(room_id, card)
                if not card_result.get("success"):
                    await lark_bot_service.send_text(room_id, self._build_lark_delivery_text(state))

                await self._push_lark_delivery_files(room_id, state)
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

    async def handle_user_feedback(self, task_id: str, feedback: str) -> AgentState:
        logger.info("Handling feedback for task %s: %s", task_id, feedback)

        return AgentState(
            session_id="",
            task_id=task_id,
            intent="",
            user_id=None,
            room_id=None,
            status="waiting",
            current_step="confirm_or_modify",
            messages=[],
            context_messages=[],
            doc_content=None,
            slides_content=None,
            extracted_tasks=None,
            workflow_plan=None,
            result=None,
            error=None,
            progress=0.8,
            updated_at=datetime.utcnow().isoformat(),
        )


agent_orchestrator = AgentOrchestrator()
