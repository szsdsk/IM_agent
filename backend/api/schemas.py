from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


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
    slides_json: Optional[Dict[str, Any]]
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
    # 前端用这个字段判断是否展示/启用“同步到飞书”能力。
    lark_cli: Optional[Dict[str, Any]] = None


class LarkSyncRequest(BaseModel):
    # 不传 chat_id 时后端会使用 LARK_DEFAULT_CHAT_ID。
    chat_id: Optional[str] = None
    # 默认同步后尝试发送交付消息；没有群配置时同步本身仍可成功。
    notify: bool = True
    # 允许前端覆盖同步到飞书后的标题。
    title: Optional[str] = None
    # 允许前端自定义发送到飞书群的交付文案。
    message: Optional[str] = None


class LarkSyncResponse(BaseModel):
    success: bool
    # 第一阶段只接入 lark-cli，保留 provider 字段方便以后扩展 OpenAPI 或其它 IM。
    provider: str = "lark_cli"
    artifact_id: str
    artifact_type: Optional[str] = None
    # 飞书返回字段在不同资源类型里名称不一致，接口层统一成 url/token。
    lark_url: Optional[str] = None
    lark_token: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
