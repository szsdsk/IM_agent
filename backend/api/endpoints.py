import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database.connection import get_db
from backend.database.connection import async_session_maker
from backend.database.models import Document, Event, Session, Slide, Task
from backend.api.schemas import (
    CreateSessionRequest, SessionResponse,
    SendMessageRequest, MessageResponse,
    TaskResponse, TaskConfirmRequest,
    DocumentResponse, SlidesResponse, HealthResponse,
    LarkSyncRequest, LarkSyncResponse
)
from backend.agent.orchestrator import agent_orchestrator
from backend.tools.lark_tool import LarkTool
from backend.services.lark_bot_service import lark_bot_service

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)

    async def send_to_session(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    async def broadcast(self, message: dict):
        for session_id in self.active_connections:
            await self.send_to_session(session_id, message)


manager = ConnectionManager()


async def _run_lark_message_task(message: Dict[str, Any]) -> None:
    async with async_session_maker() as db:
        session = Session(
            id=str(uuid.uuid4()),
            user_id=message.get("user_id"),
            status="active",
        )
        task = Task(
            id=str(uuid.uuid4()),
            session_id=session.id,
            intent=message["text"],
            status="pending",
        )
        db.add(session)
        db.add(task)
        await db.commit()
        await db.refresh(task)

        await manager.broadcast({
            "type": "agent.message",
            "task_id": task.id,
            "session_id": session.id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "content": f"来自飞书的需求：{message['text']}",
                "source": "lark",
                "chat_id": message.get("chat_id"),
            },
        })

        async def ws_sender(data: dict):
            await manager.broadcast({
                **data,
                "session_id": session.id,
                "source": "lark",
            })

        state = await agent_orchestrator.execute_workflow(
            session_id=session.id,
            task_id=task.id,
            intent=message["text"],
            user_id=message.get("user_id"),
            room_id=message.get("chat_id"),
            ws_sender=ws_sender,
        )

        task.status = state["status"]
        task.current_step = state["current_step"]
        task.result_json = {
            "progress": state["progress"],
            "result": state.get("result"),
            "error": state.get("error"),
            "im_provider": "lark",
            "chat_id": message.get("chat_id"),
            "message_id": message.get("message_id"),
        }
        task.updated_at = datetime.utcnow()
        await db.commit()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    # 健康检查同时返回飞书 CLI 状态，前端据此决定同步按钮是否可用。
    lark_status = await LarkTool(mock_mode=False).get_status(check_auth=True)
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        lark_cli=lark_status,
    )


@router.post("/im/lark/events")
async def lark_event_callback(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    if lark_bot_service.is_url_verification(payload):
        if not lark_bot_service.verify_event(payload):
            raise HTTPException(status_code=403, detail="Invalid Lark verification token")
        return {"challenge": payload["challenge"]}

    if not lark_bot_service.verify_event(payload):
        raise HTTPException(status_code=403, detail="Invalid Lark verification token")

    message = lark_bot_service.extract_message_event(payload)
    if message and message.get("chat_id") and message.get("text"):
        background_tasks.add_task(_run_lark_message_task, message)

    return {"code": 0, "msg": "ok"}


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    db: AsyncSession = Depends(get_db)
):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=request.user_id,
        status="active"
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Event).where(
            Event.task_id.in_(
                select(Task.id).where(Task.session_id == session_id)
            )
        ).order_by(Event.created_at)
    )
    events = result.scalars().all()
    return [
        MessageResponse(
            id=e.id,
            session_id=session_id,
            role="system",
            content=e.payload.get("content", "") if e.payload else "",
            timestamp=e.created_at
        )
        for e in events
    ]


@router.post("/sessions/{session_id}/messages", response_model=TaskResponse)
async def send_message(
    session_id: str,
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db)
):
    session_result = await db.execute(select(Session).where(Session.id == session_id))
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task = Task(
        id=str(uuid.uuid4()),
        session_id=session_id,
        intent=request.content,
        status="pending"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    async def ws_sender(data: dict):
        await manager.send_to_session(session_id, data)
        if request.room_id:
            await manager.broadcast({
                **data,
                "session_id": session_id,
                "source": "lark",
                "room_id": request.room_id,
            })

    if request.room_id:
        await manager.broadcast({
            "type": "agent.message",
            "task_id": task.id,
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "content": f"来自飞书的需求：{request.content}",
                "source": "lark",
                "chat_id": request.room_id,
            },
        })

    state = await agent_orchestrator.execute_workflow(
        session_id=session_id,
        task_id=task.id,
        intent=request.content,
        user_id=request.user_id,
        room_id=request.room_id,
        ws_sender=ws_sender
    )

    task.status = state["status"]
    task.current_step = state["current_step"]
    task.result_json = {
        "progress": state["progress"],
        "result": state.get("result"),
        "error": state.get("error")
    }
    task.updated_at = datetime.utcnow()
    await db.commit()

    await db.refresh(task)
    return task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/tasks/{task_id}/confirm", response_model=TaskResponse)
async def confirm_task(
    task_id: str,
    request: TaskConfirmRequest,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if request.confirmed:
        task.status = "completed"
    else:
        task.status = "pending"
        task.current_step = "confirm_or_modify"

    await db.commit()
    await db.refresh(task)
    return task


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/slides/{slide_id}", response_model=SlidesResponse)
async def get_slides(slide_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Slide).where(Slide.id == slide_id))
    slides = result.scalar_one_or_none()
    if not slides:
        raise HTTPException(status_code=404, detail="Slides not found")
    return slides


def _task_result_artifact(task: Task, request: LarkSyncRequest) -> Optional[Dict[str, Any]]:
    """从任务最终结果中提取可同步到飞书的文档或 PPT 交付物。"""
    result_json = task.result_json if isinstance(task.result_json, dict) else {}
    result = result_json.get("result") if isinstance(result_json.get("result"), dict) else {}
    slides = result.get("slides") or result.get("deck")
    document = result.get("document") or result.get("doc")

    if isinstance(slides, dict) and slides.get("file_path"):
        # 任务结果里同时可能有 document 和 slides，PPT 有文件时优先同步 PPT。
        return {
            "artifact_type": "slides",
            "title": request.title or slides.get("title") or task.intent,
            "file_path": slides.get("file_path"),
            "chat_id": request.chat_id,
            "notify": request.notify,
            "message": request.message,
        }

    if isinstance(document, dict):
        # 没有可下载 PPT 时，退回同步文档内容。
        return {
            "artifact_type": "document",
            "title": request.title or document.get("title") or task.intent,
            "content": document.get("content") or document.get("preview") or "",
            "chat_id": request.chat_id,
            "notify": request.notify,
            "message": request.message,
        }

    return None


async def _load_artifact_payload(
    artifact_id: str,
    request: LarkSyncRequest,
    db: AsyncSession,
) -> Optional[Dict[str, Any]]:
    """兼容 task_id、document_id、slide_id 三种 artifact_id 输入。"""
    # 前端当前从任务结果入口同步，所以优先按 task_id 查。
    task_result = await db.execute(select(Task).where(Task.id == artifact_id))
    task = task_result.scalar_one_or_none()
    if task:
        return _task_result_artifact(task, request)

    document_result = await db.execute(select(Document).where(Document.id == artifact_id))
    document = document_result.scalar_one_or_none()
    if document:
        # 直接同步文档表记录时，只依赖数据库里的正文内容。
        return {
            "artifact_type": "document",
            "title": request.title or "Agent-Pilot 文档",
            "content": document.content or "",
            "chat_id": request.chat_id,
            "notify": request.notify,
            "message": request.message,
        }

    slide_result = await db.execute(select(Slide).where(Slide.id == artifact_id))
    slide = slide_result.scalar_one_or_none()
    if slide:
        # 直接同步 slides 表记录时，需要把本地 PPT 文件路径传给 LarkTool。
        title = request.title or "Agent-Pilot 演示稿"
        if isinstance(slide.slides_json, dict):
            title = request.title or slide.slides_json.get("title") or title
        return {
            "artifact_type": "slides",
            "title": title,
            "file_path": slide.file_path,
            "chat_id": request.chat_id,
            "notify": request.notify,
            "message": request.message,
        }

    return None


@router.post("/artifacts/{artifact_id}/sync/lark", response_model=LarkSyncResponse)
async def sync_artifact_to_lark(
    artifact_id: str,
    request: Optional[LarkSyncRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """把本地已生成的文档或 PPT 同步到飞书。"""
    sync_request = request or LarkSyncRequest()
    # 接口层只负责加载 artifact 和组装响应，具体 CLI 命令交给 LarkTool。
    payload = await _load_artifact_payload(artifact_id, sync_request, db)
    if not payload:
        raise HTTPException(status_code=404, detail="Artifact not found or has no syncable content")

    result = await LarkTool(mock_mode=False).execute(
        action="sync_artifact",
        entity_id=artifact_id,
        data=payload,
    )

    return LarkSyncResponse(
        success=result.get("success", False),
        provider=result.get("provider", "lark_cli"),
        artifact_id=artifact_id,
        artifact_type=result.get("artifact_type") or payload.get("artifact_type"),
        lark_url=result.get("lark_url"),
        lark_token=result.get("lark_token"),
        message=result.get("message"),
        error=result.get("error"),
    )


@router.get("/files/slides/{filename}")
async def download_slide_file(filename: str):
    """下载后端生成的 PPT 文件。"""
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid file name")

    slides_dir = Path(__file__).resolve().parents[1] / "data" / "slides"
    file_path = (slides_dir / filename).resolve()

    # 只允许访问 slides 输出目录，避免通过文件名跳出目录。
    if slides_dir.resolve() not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Slide file not found")

    return FileResponse(
        path=file_path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )


@router.websocket("/ws/sessions/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
            elif data.get("type") == "message":
                request = SendMessageRequest(content=data.get("content", ""))
                async with async_session_maker() as session_result:
                    result = await session_result.execute(select(Session).where(Session.id == session_id))
                    session = result.scalar_one_or_none()
                    if session:
                        task = Task(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            intent=request.content,
                            status="pending"
                        )
                        session_result.add(task)
                        await session_result.commit()
                        await session_result.refresh(task)

                        async def ws_sender(msg: dict):
                            await websocket.send_json(msg)

                        state = await agent_orchestrator.execute_workflow(
                            session_id=session_id,
                            task_id=task.id,
                            intent=request.content,
                            user_id=request.user_id,
                            room_id=request.room_id,
                            ws_sender=ws_sender
                        )

                        task.status = state["status"]
                        task.current_step = state["current_step"]
                        task.result_json = {
                            "progress": state["progress"],
                            "result": state.get("result"),
                            "error": state.get("error")
                        }
                        task.updated_at = datetime.utcnow()
                        await session_result.commit()
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception:
        manager.disconnect(websocket, session_id)
