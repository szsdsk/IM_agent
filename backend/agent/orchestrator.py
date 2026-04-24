import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from collections import defaultdict

from backend.agent.state import AgentState, create_initial_state
from backend.agent import nodes
from backend.tools.tool_factory import ToolFactory

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

    async def execute_workflow(self, session_id: str, task_id: str, intent: str,
                                 ws_sender: callable = None) -> AgentState:
        state = create_initial_state(session_id, task_id, intent)

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

        return state

    async def handle_user_feedback(self, task_id: str, feedback: str) -> AgentState:
        logger.info(f"Handling feedback for task {task_id}: {feedback}")

        return AgentState(
            session_id="",
            task_id=task_id,
            intent="",
            status="waiting",
            current_step="confirm_or_modify",
            messages=[],
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
