from typing import TypedDict, List, Optional, Dict, Any
from datetime import datetime


class AgentState(TypedDict):
    session_id: str
    task_id: str
    intent: str
    status: str
    current_step: str
    messages: List[Dict[str, Any]]
    doc_content: Optional[Dict[str, Any]]
    slides_content: Optional[Dict[str, Any]]
    extracted_tasks: Optional[List[str]]
    workflow_plan: Optional[List[str]]
    result: Optional[Dict[str, Any]]
    error: Optional[str]
    progress: float
    updated_at: str


def create_initial_state(session_id: str, task_id: str, intent: str) -> AgentState:
    return AgentState(
        session_id=session_id,
        task_id=task_id,
        intent=intent,
        status="pending",
        current_step="receive_input",
        messages=[],
        doc_content=None,
        slides_content=None,
        extracted_tasks=None,
        workflow_plan=None,
        result=None,
        error=None,
        progress=0.0,
        updated_at=datetime.utcnow().isoformat()
    )
