import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.orchestrator import agent_orchestrator
from backend.api.schemas import (
    CreateSessionRequest,
    DocumentResponse,
    HealthResponse,
    MessageResponse,
    SendMessageRequest,
    SessionResponse,
    SlidesResponse,
    TaskConfirmRequest,
    TaskResponse,
)
from backend.database.connection import async_session_maker, get_db
from backend.database.models import Document, Event, Session, Slide, Task
from backend.services.lark_bot_service import lark_bot_service

router = APIRouter()

logger = logging.getLogger(__name__)


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
    """把飞书消息转换为一次独立的 Agent 任务。"""
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
    # 网页端只需要知道后端是否存活，飞书同步状态不再作为网页能力暴露。
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
    )


@router.post("/im/lark/events")
async def lark_event_callback(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """飞书事件订阅入口，bot 收到文本消息后异步触发 Agent 流程。"""
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


@router.post("/im/lark/card/action")
async def lark_card_action(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """飞书卡片交互回调，处理按钮点击等操作。"""
    if not lark_bot_service.verify_event(payload):
        raise HTTPException(status_code=403, detail="Invalid verification token")

    action = payload.get("action", {})
    action_type = action.get("tag", "")
    action_value = action.get("value", {})
    open_id = payload.get("open_id", "")
    token = payload.get("token", "")

    logger.info(
        "Lark card action: type=%s, value=%s, user=%s",
        action_type, action_value, open_id,
    )

    task_id = action_value.get("task_id", "")
    action_name = action_value.get("action", "")

    if action_name == "confirm_delivery" and task_id:
        async with async_session_maker() as db:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task:
                task.status = "completed"
                task.updated_at = datetime.utcnow()
                await db.commit()

        chat_id = action_value.get("chat_id", "")
        if chat_id and lark_bot_service.is_configured:
            await lark_bot_service.send_text(chat_id, f"任务 {task_id} 已确认交付 ✅")

    elif action_name == "request_modification" and task_id:
        async with async_session_maker() as db:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task:
                task.status = "pending"
                task.current_step = "confirm_or_modify"
                task.updated_at = datetime.utcnow()
                await db.commit()

        chat_id = action_value.get("chat_id", "")
        if chat_id and lark_bot_service.is_configured:
            await lark_bot_service.send_text(chat_id, f"任务 {task_id} 已标记为需修改，请发送修改意见。")

    return {"code": 0, "msg": "ok"}


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
):
    session = Session(
        id=str(uuid.uuid4()),
        user_id=request.user_id,
        status="active",
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
            timestamp=e.created_at,
        )
        for e in events
    ]


@router.post("/sessions/{session_id}/messages", response_model=TaskResponse)
async def send_message(
    session_id: str,
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(select(Session).where(Session.id == session_id))
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task = Task(
        id=str(uuid.uuid4()),
        session_id=session_id,
        intent=request.content,
        status="pending",
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
        ws_sender=ws_sender,
    )

    task.status = state["status"]
    task.current_step = state["current_step"]
    task.result_json = {
        "progress": state["progress"],
        "result": state.get("result"),
        "error": state.get("error"),
        "im_provider": "lark" if request.room_id else None,
        "chat_id": request.room_id,
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
    db: AsyncSession = Depends(get_db),
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


@router.get("/files/slides/{filename}")
async def download_slide_file(filename: str):
    """下载后端生成的本地 PPT 文件。"""
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
                            status="pending",
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
                            ws_sender=ws_sender,
                        )

                        task.status = state["status"]
                        task.current_step = state["current_step"]
                        task.result_json = {
                            "progress": state["progress"],
                            "result": state.get("result"),
                            "error": state.get("error"),
                        }
                        task.updated_at = datetime.utcnow()
                        await session_result.commit()
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception:
        manager.disconnect(websocket, session_id)
