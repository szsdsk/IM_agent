import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from collections import defaultdict

from backend.agent.state import AgentState, create_initial_state
from backend.agent import nodes
from backend.tools.tool_factory import ToolFactory
from backend.config import settings
from backend.services.lark_bot_service import lark_bot_service
from backend.services.rocket_chat_service import (
    fetch_im_context,
    post_delivery_to_im,
    rocket_chat_service,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(self):
        self._callbacks: Dict[str, List[callable]] = defaultdict(list)
        self._tools = ToolFactory.get_all_tools()

    def register_callback(self, event: str, callback: callable):
        self._callbacks[event].append(callback)

    async def trigger_callback(self, event: str, data: Dict[str, Any]):
        if event in self._callbacks:
            for callback in self._callbacks[event]:
                try:
                    await callback(data)
                except Exception as e:
                    logger.error(f"Callback error for {event}: {str(e)}")

    async def execute_workflow(
        self,
        session_id: str,
        task_id: str,
        intent: str,
        user_id: Optional[str] = None,
        room_id: Optional[str] = None,
        ws_sender: callable = None,
    ) -> AgentState:
        context_messages: List[Dict[str, Any]] = []
        if room_id and settings.IM_PROVIDER == "rocket_chat":
            try:
                context_messages = await fetch_im_context(room_id, limit=20)
            except Exception as e:
                logger.warning(f"Failed to fetch Rocket.Chat context for room {room_id}: {str(e)}")

        state = create_initial_state(
            session_id,
            task_id,
            intent,
            user_id=user_id,
            room_id=room_id,
            context_messages=context_messages,
        )

        workflow_nodes = [
            nodes.receive_input,
            nodes.parse_intent,
            nodes.plan_workflow,
            nodes.extract_tasks,
            nodes.generate_doc,
            nodes.generate_slides,
            nodes.confirm_or_modify,
            nodes.deliver_result
        ]

        for node in workflow_nodes:
            try:
                state = await node(state)

                progress_message = {
                    "type": "task.progress",
                    "task_id": task_id,
                    "step": state["current_step"],
                    "message": f"Executing: {state['current_step']}",
                    "progress": state["progress"],
                    "status": state["status"],
                    "timestamp": state["updated_at"],
                    "updated_at": state["updated_at"]
                }
                if ws_sender:
                    await ws_sender(progress_message)
                await self.trigger_callback("progress", progress_message)
                await self._push_progress_to_im(room_id, task_id, state)

                if state.get("error"):
                    logger.error(f"Task {task_id} error at {state['current_step']}: {state['error']}")
                    break

            except Exception as e:
                logger.error(f"Error in node {node.__name__}: {str(e)}")
                state["error"] = str(e)
                state["status"] = "failed"
                break

        completed_message = {
            "type": "task.completed" if state["status"] == "completed" else "task.failed",
            "task_id": task_id,
            "result": state.get("result"),
            "status": state["status"],
            "error": state.get("error"),
            "timestamp": state["updated_at"],
            "updated_at": state["updated_at"]
        }
        if ws_sender:
            await ws_sender(completed_message)
        await self.trigger_callback("completed", completed_message)
        await self._push_completion_to_im(room_id, state)

        return state

    async def _push_progress_to_im(self, room_id: Optional[str], task_id: str, state: AgentState) -> None:
        if not room_id:
            return

        try:
            if settings.IM_PROVIDER == "lark":
                if not lark_bot_service.is_configured:
                    return
                text = (
                    f"Agent-Pilot 任务进行中\n"
                    f"进度: {int(state['progress'] * 100)}%\n"
                    f"步骤: {state['current_step']}\n"
                    f"任务: {task_id}"
                )
                await lark_bot_service.send_text(room_id, text)
                return

            if not rocket_chat_service.is_configured:
                return
            await rocket_chat_service.send_progress_update(
                room_id=room_id,
                task_id=task_id,
                step=state["current_step"],
                progress=state["progress"],
                message=f"Executing: {state['current_step']}",
            )

            if state["current_step"] == "plan_workflow" and state.get("workflow_plan"):
                await rocket_chat_service.send_plan_card(room_id, state["workflow_plan"])
        except Exception as e:
            logger.warning(f"Failed to push Rocket.Chat progress for task {task_id}: {str(e)}")

    async def _push_completion_to_im(self, room_id: Optional[str], state: AgentState) -> None:
        if not room_id or not state.get("result"):
            return

        try:
            if settings.IM_PROVIDER == "lark":
                if not lark_bot_service.is_configured:
                    return
                await lark_bot_service.send_text(room_id, self._build_lark_delivery_text(state))
                await self._push_lark_delivery_files(room_id, state)
                return

            if not rocket_chat_service.is_configured:
                return
            await post_delivery_to_im(room_id, state["result"])
        except Exception as e:
            logger.warning(f"Failed to post Rocket.Chat delivery for task {state['task_id']}: {str(e)}")

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
        except Exception as e:
            logger.warning(f"Failed to upload/send Lark PPT for task {state['task_id']}: {str(e)}")

    async def handle_user_feedback(self, task_id: str, feedback: str) -> AgentState:
        logger.info(f"Handling feedback for task {task_id}: {feedback}")

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
            updated_at=datetime.utcnow().isoformat()
        )


agent_orchestrator = AgentOrchestrator()
