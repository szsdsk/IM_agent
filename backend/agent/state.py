from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    task_id: str
    intent: str
    user_id: Optional[str]
    room_id: Optional[str]
    status: str
    current_step: str
    messages: List[Dict[str, Any]]
    context_messages: List[Dict[str, Any]]
    im_context_summary: Optional[Dict[str, Any]]
    intent_analysis: Optional[Dict[str, Any]]
    content_types: List[str]
    presentation_scene: Optional[str]
    audience: Optional[str]
    constraints: List[str]
    pending_questions: List[str]
    workflow_plan: Optional[Dict[str, Any]]
    steps: List[Dict[str, Any]]
    agent_plan: Optional[Dict[str, Any]]
    active_agent: Optional[str]
    task_results: Dict[str, Any]
    artifacts: Dict[str, Any]
    replans: List[Dict[str, Any]]
    completed_task_ids: List[str]
    waiting_approval: bool
    extracted_tasks: Optional[List[str]]
    doc_content: Optional[Dict[str, Any]]
    doc_id: Optional[str]
    canvas_content: Optional[Dict[str, Any]]
    deck_spec: Optional[Dict[str, Any]]
    slides_content: Optional[Dict[str, Any]]
    slide_id: Optional[str]
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
        im_context_summary=None,
        intent_analysis=None,
        content_types=[],
        presentation_scene=None,
        audience=None,
        constraints=[],
        pending_questions=[],
        workflow_plan=None,
        steps=[],
        agent_plan=None,
        active_agent=None,
        task_results={},
        artifacts={},
        replans=[],
        completed_task_ids=[],
        waiting_approval=False,
        extracted_tasks=None,
        doc_content=None,
        doc_id=None,
        canvas_content=None,
        deck_spec=None,
        slides_content=None,
        slide_id=None,
        result=None,
        error=None,
        progress=0.0,
        updated_at=datetime.utcnow().isoformat(),
    )
