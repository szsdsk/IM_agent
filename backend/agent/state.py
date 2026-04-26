from typing import TypedDict, List, Optional, Dict, Any
from datetime import datetime


class AgentState(TypedDict):
    session_id: str
    task_id: str
    intent: str
    user_id: Optional[str]
    room_id: Optional[str]
    status: str
    current_step: str
    messages: List[Dict[str, Any]]
    context_messages: List[Dict[str, Any]]
    doc_content: Optional[Dict[str, Any]]
    slides_content: Optional[Dict[str, Any]]
    extracted_tasks: Optional[List[str]]
    workflow_plan: Optional[List[str]]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    progress: float
    updated_at: str


def create_initial_state(
    session_id: str,
    task_id: str,
    intent: str,
    user_id: Optional[str] = None,
    room_id: Optional[str] = None,
    context_messages: Optional[List[Dict[str, Any]]] = None,
) -> AgentState:
    return AgentState(
        session_id=session_id,
        task_id=task_id,
        intent=intent,
        user_id=user_id,
        room_id=room_id,
        status="pending",
        current_step="receive_input",
        messages=[],
        context_messages=context_messages or [],
        doc_content=None,
        slides_content=None,
        extracted_tasks=None,
        workflow_plan=None,
        result=None,
        error=None,
        progress=0.0,
        updated_at=datetime.utcnow().isoformat()
    )
