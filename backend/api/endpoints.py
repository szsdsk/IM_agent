import uuid
from datetime import datetime
from typing import Dict, Set
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database.connection import get_db
from backend.database.connection import async_session_maker
from backend.database.models import Session, Task, Event
from backend.api.schemas import (
    CreateSessionRequest, SessionResponse,
    SendMessageRequest, MessageResponse,
    TaskCreateRequest, TaskResponse, TaskConfirmRequest,
    DocumentResponse, SlidesResponse, HealthResponse
)
from backend.agent.orchestrator import agent_orchestrator

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


@router.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow()
    )


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

    state = await agent_orchestrator.execute_workflow(
        session_id=session_id,
        task_id=task.id,
        intent=request.content,
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
    from backend.database.models import Document
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/slides/{slide_id}", response_model=SlidesResponse)
async def get_slides(slide_id: str, db: AsyncSession = Depends(get_db)):
    from backend.database.models import Slide
    result = await db.execute(select(Slide).where(Slide.id == slide_id))
    slides = result.scalar_one_or_none()
    if not slides:
        raise HTTPException(status_code=404, detail="Slides not found")
    return slides


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
