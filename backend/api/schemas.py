from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    user_id: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    user_id: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    content: str
    user_id: Optional[str] = None
    room_id: Optional[str] = None
    feedback_task_id: Optional[str] = None
    presentation_scene: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    timestamp: datetime


class TaskCreateRequest(BaseModel):
    session_id: str
    intent: str


class TaskResponse(BaseModel):
    id: str
    session_id: str
    intent: str
    status: str
    current_step: Optional[str]
    progress: float
    result_json: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskConfirmRequest(BaseModel):
    confirmed: bool = True
    feedback: Optional[str] = None


class DocumentResponse(BaseModel):
    id: str
    task_id: str
    content: Optional[str]
    version: int
    created_at: datetime

    class Config:
        from_attributes = True


class SlidesResponse(BaseModel):
    id: str
    task_id: str
    # slides_json 既可能是 DeckSpec 对象，也可能是页面数组，所以这里保持宽松。
    slides_json: Optional[Any]
    file_path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class WebSocketMessage(BaseModel):
    type: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    step: Optional[str] = None
    message: Optional[str] = None
    progress: Optional[float] = None
    status: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str = "1.0.0"


class VoiceTranscriptionResponse(BaseModel):
    success: bool
    text: Optional[str] = None
    error: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
