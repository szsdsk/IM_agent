import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
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
    VoiceTranscriptionResponse,
)
from backend.database.connection import async_session_maker, get_db
from backend.database.models import Document, Event, Session, Slide, Task
from backend.services.lark_bot_service import lark_bot_service
from backend.services.speech_service import speech_service
from backend.services.sync_service import sync_service

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


def _extract_result_payload(task: Task) -> Dict[str, Any]:
    if isinstance(task.result_json, dict):
        result = task.result_json.get("result")
        if isinstance(result, dict):
            return result
    return {}


def _looks_like_feedback(content: str) -> bool:
    text = (content or "").lower()
    markers = [
        "改",
        "修改",
        "调整",
        "优化",
        "替换",
        "删掉",
        "删除",
        "增加",
        "补充",
        "把第",
        "第",
        "page",
        "slide",
        "ppt",
        "文档",
        "doc",
    ]
    return any(marker in text for marker in markers)


async def _persist_task_outputs(db: AsyncSession, task: Task, state: Dict[str, Any]) -> None:
    task.status = state["status"]
    task.current_step = state["current_step"]
    task.result_json = {
        "progress": state["progress"],
        "result": state.get("result"),
        "error": state.get("error"),
        "im_provider": task.result_json.get("im_provider") if isinstance(task.result_json, dict) else None,
        "chat_id": task.result_json.get("chat_id") if isinstance(task.result_json, dict) else None,
    }
    task.updated_at = datetime.utcnow()

    if state.get("doc_content"):
        existing_doc_result = await db.execute(select(Document).where(Document.task_id == task.id))
        document = existing_doc_result.scalar_one_or_none()
        if not document:
            document = Document(task_id=task.id)
            db.add(document)
            document.version = 1
        else:
            document.version = (document.version or 1) + 1
        document.content = state["doc_content"].get("content")
        document.updated_at = datetime.utcnow()

    if state.get("slides_content"):
        existing_slide_result = await db.execute(select(Slide).where(Slide.task_id == task.id))
        slide = existing_slide_result.scalar_one_or_none()
        if not slide:
            slide = Slide(task_id=task.id)
            db.add(slide)
        slide.slides_json = state["slides_content"].get("slides", [])
        slide.file_path = state["slides_content"].get("file_path")
        slide.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(task)


async def _find_feedback_target(
    db: AsyncSession,
    session_id: str,
    explicit_task_id: Optional[str],
    content: str,
) -> Optional[Task]:
    if explicit_task_id:
        result = await db.execute(select(Task).where(Task.id == explicit_task_id, Task.session_id == session_id))
        return result.scalar_one_or_none()

    if not _looks_like_feedback(content):
        return None

    result = await db.execute(
        select(Task)
        .where(Task.session_id == session_id)
        .order_by(Task.updated_at.desc())
    )
    for task in result.scalars().all():
        payload = _extract_result_payload(task)
        if payload and task.status in {"completed", "pending"}:
            return task
    return None


async def _run_lark_message_task(message: Dict[str, Any]) -> None:
    """把飞书消息转换为一次独立的 Agent 任务。"""
    text = (message.get("text") or "").strip()
    voice_resource = message.get("voice_resource")

    if not text and voice_resource:
        message_type = str((voice_resource or {}).get("message_type") or "").lower()
        resource_type = "audio" if message_type in {"audio", "voice"} else "media" if message_type == "media" else "file"
        download_result = await lark_bot_service.download_message_resource(
            message_id=message.get("message_id", ""),
            file_key=voice_resource.get("file_key", ""),
            resource_type=resource_type,
        )
        if not download_result.get("success"):
            if message.get("chat_id") and lark_bot_service.is_configured:
                await lark_bot_service.send_text(
                    message["chat_id"],
                    f"语音文件下载失败：{download_result.get('error') or 'unknown error'}",
                )
            return

        transcription = await speech_service.transcribe(
            audio_bytes=download_result.get("content") or b"",
            filename=f"feishu-{message.get('message_id', 'voice')}.ogg",
            content_type=download_result.get("content_type"),
            language="zh",
        )
        if not transcription.get("success"):
            if message.get("chat_id") and lark_bot_service.is_configured:
                await lark_bot_service.send_text(
                    message["chat_id"],
                    f"语音转写失败：{transcription.get('error') or 'unknown error'}",
                )
            return

        text = transcription["text"]
        message["text"] = text
        if message.get("chat_id") and lark_bot_service.is_configured:
            await lark_bot_service.send_text(message["chat_id"], f"语音已转写：{text}")

    if not text:
        return

    async with async_session_maker() as db:
        session_result = await db.execute(
            select(Session)
            .where(Session.user_id == message.get("user_id"))
            .order_by(Session.updated_at.desc())
        )
        session = session_result.scalar_one_or_none()
        if not session:
            session = Session(
                id=str(uuid.uuid4()),
                user_id=message.get("user_id"),
                status="active",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

        async def ws_sender(data: dict):
            await manager.broadcast({
                **data,
                "session_id": session.id,
                "source": "lark",
            })

        feedback_target = await _find_feedback_target(
            db=db,
            session_id=session.id,
            explicit_task_id=None,
            content=text,
        )

        if feedback_target:
            await manager.broadcast({
                "type": "agent.message",
                "task_id": feedback_target.id,
                "session_id": session.id,
                "timestamp": datetime.utcnow().isoformat(),
                "data": {
                    "content": f"收到修改意见：{text}",
                    "source": "lark",
                    "chat_id": message.get("chat_id"),
                },
            })
            state = await agent_orchestrator.handle_user_feedback(
                session_id=session.id,
                task_id=feedback_target.id,
                feedback=text,
                base_result=_extract_result_payload(feedback_target),
                user_id=message.get("user_id"),
                room_id=message.get("chat_id"),
                ws_sender=ws_sender,
            )
            feedback_target.result_json = {
                "im_provider": "lark",
                "chat_id": message.get("chat_id"),
                "message_id": message.get("message_id"),
            }
            await _persist_task_outputs(db, feedback_target, state)
            return

        task = Task(
            id=str(uuid.uuid4()),
            session_id=session.id,
            intent=text,
            status="pending",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        await manager.broadcast({
            "type": "agent.message",
            "task_id": task.id,
            "session_id": session.id,
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "content": f"来自飞书的需求：{text}",
                "source": "lark",
                "chat_id": message.get("chat_id"),
            },
        })

        state = await agent_orchestrator.execute_workflow(
            session_id=session.id,
            task_id=task.id,
            intent=text,
            user_id=message.get("user_id"),
            room_id=message.get("chat_id"),
            ws_sender=ws_sender,
        )

        task.result_json = {
            "im_provider": "lark",
            "chat_id": message.get("chat_id"),
            "message_id": message.get("message_id"),
        }
        await _persist_task_outputs(db, task, state)


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
    if message and message.get("chat_id") and (message.get("text") or message.get("voice_resource")):
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

    elif action_name == "doc_edited":
        # Forward to the doc event handler for writeback
        doc_id = action_value.get("lark_doc_id")
        if doc_id:
            # Extract the task_id from the action value or look it up
            found_task_id = task_id
            if not found_task_id:
                async with async_session_maker() as db:
                    result = await db.execute(
                        select(Document).where(Document.lark_doc_id == doc_id)
                    )
                    doc_record = result.scalar_one_or_none()
                    if doc_record:
                        found_task_id = doc_record.task_id

            if found_task_id:
                # Update doc record and broadcast
                async with async_session_maker() as db:
                    result = await db.execute(
                        select(Document).where(Document.lark_doc_id == doc_id)
                    )
                    doc_record = result.scalar_one_or_none()
                    if doc_record:
                        doc_record.last_edited_by = payload.get("open_id")
                        doc_record.last_edited_at = datetime.utcnow()
                        doc_record.version = (doc_record.version or 1) + 1
                        await db.commit()

                        try:
                            await sync_service.broadcast_doc_update(
                                session_id=found_task_id,
                                task_id=found_task_id,
                                doc_id=doc_id,
                                changes={
                                    "last_edited_by": payload.get("open_id"),
                                    "last_edited_at": datetime.utcnow().isoformat(),
                                    "version": doc_record.version,
                                    "source": "card_callback",
                                },
                            )
                        except Exception:
                            pass

                chat_id = action_value.get("chat_id", "")
                if chat_id and lark_bot_service.is_configured:
                    await lark_bot_service.send_text(chat_id, f"文档已更新，版本 v{doc_record.version}，状态已同步 ✅")

    return {"code": 0, "msg": "ok"}


@router.post("/im/lark/doc/events")
async def lark_doc_event_callback(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    """飞书文档变更事件回调，处理文档编辑后的状态回写。

    支持两种触发方式：
    1. 卡片回调：用户在飞书中编辑文档后，点击卡片上的"已编辑完成"按钮触发
       卡片 payload 包含 action.value.lark_doc_id、task_id 等字段
    2. 事件订阅：飞书文档变更事件推送（需在飞书开放平台配置文档订阅）
       payload 包含 event.doc.document_id、event.operator 等

    收到后：
    - 查询本地 Document 记录，更新 last_edited_by、last_edited_at
    - 通过 SyncService 广播 doc.updated 事件给所有在线客户端
    """
    if not lark_bot_service.verify_event(payload):
        raise HTTPException(status_code=403, detail="Invalid verification token")

    doc_info = lark_bot_service.extract_doc_event(payload)
    if not doc_info or not doc_info.get("doc_id"):
        return {"code": 0, "msg": "No doc event found in payload"}

    doc_id = doc_info["doc_id"]
    user_id = doc_info.get("user_id")
    task_id = doc_info.get("task_id")
    source = doc_info.get("source", "unknown")

    logger.info(
        "Lark doc event: doc_id=%s, user=%s, task=%s, source=%s",
        doc_id, user_id, task_id, source,
    )

    # Find task_id if not provided via card
    if not task_id:
        async with async_session_maker() as db:
            result = await db.execute(
                select(Document).where(Document.lark_doc_id == doc_id)
            )
            doc_record = result.scalar_one_or_none()
            if doc_record:
                task_id = doc_record.task_id

    # Update Document record
    if task_id:
        async with async_session_maker() as db:
            result = await db.execute(select(Document).where(Document.lark_doc_id == doc_id))
            doc_record = result.scalar_one_or_none()
            if doc_record:
                doc_record.last_edited_by = user_id
                doc_record.last_edited_at = datetime.utcnow()
                doc_record.version = (doc_record.version or 1) + 1
                await db.commit()

                # Broadcast doc update to all clients
                try:
                    await sync_service.broadcast_doc_update(
                        session_id=doc_record.task_id,
                        task_id=task_id,
                        doc_id=doc_id,
                        changes={
                            "last_edited_by": user_id,
                            "last_edited_at": datetime.utcnow().isoformat(),
                            "version": doc_record.version,
                            "source": source,
                        },
                    )
                except Exception as sync_exc:
                    logger.warning("Failed to broadcast doc update: %s", sync_exc)

    return {"code": 0, "msg": "ok"}


@router.post("/voice/transcriptions", response_model=VoiceTranscriptionResponse)
async def transcribe_voice(
    file: UploadFile = File(...),
    language: str = "zh",
):
    audio_bytes = await file.read()
    result = await speech_service.transcribe(
        audio_bytes=audio_bytes,
        filename=file.filename or "voice.ogg",
        content_type=file.content_type,
        language=language,
    )
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Voice transcription failed.")
    return VoiceTranscriptionResponse(
        success=True,
        text=result.get("text"),
        model=result.get("model"),
        provider=result.get("provider"),
    )



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

    async def ws_sender(data: dict):
        await manager.send_to_session(session_id, data)
        if request.room_id:
            await manager.broadcast({
                **data,
                "session_id": session_id,
                "source": "lark",
                "room_id": request.room_id,
            })

    feedback_target = await _find_feedback_target(
        db=db,
        session_id=session_id,
        explicit_task_id=request.feedback_task_id,
        content=request.content,
    )

    if feedback_target:
        state = await agent_orchestrator.handle_user_feedback(
            session_id=session_id,
            task_id=feedback_target.id,
            feedback=request.content,
            base_result=_extract_result_payload(feedback_target),
            user_id=request.user_id,
            room_id=request.room_id or (
                feedback_target.result_json.get("chat_id")
                if isinstance(feedback_target.result_json, dict)
                else None
            ),
            ws_sender=ws_sender,
        )
        await _persist_task_outputs(db, feedback_target, state)
        return feedback_target

    task = Task(
        id=str(uuid.uuid4()),
        session_id=session_id,
        intent=request.content,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    state = await agent_orchestrator.execute_workflow(
        session_id=session_id,
        task_id=task.id,
        intent=request.content,
        user_id=request.user_id,
        room_id=request.room_id,
        presentation_scene=request.presentation_scene,
        ws_sender=ws_sender,
    )

    if request.room_id:
        task.result_json = {"im_provider": "lark", "chat_id": request.room_id}
    await _persist_task_outputs(db, task, state)
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
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        return task

    if request.feedback:
        state = await agent_orchestrator.handle_user_feedback(
            session_id=task.session_id,
            task_id=task.id,
            feedback=request.feedback,
            base_result=_extract_result_payload(task),
        )
        await _persist_task_outputs(db, task, state)
        return task
    else:
        task.status = "pending"
        task.current_step = "confirm_or_modify"
        task.updated_at = datetime.utcnow()

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
                request = SendMessageRequest(
                    content=data.get("content", ""),
                    presentation_scene=data.get("presentation_scene"),
                )
                async with async_session_maker() as session_result:
                    result = await session_result.execute(select(Session).where(Session.id == session_id))
                    session = result.scalar_one_or_none()
                    if session:
                        async def ws_sender(msg: dict):
                            await websocket.send_json(msg)

                        feedback_target = await _find_feedback_target(
                            db=session_result,
                            session_id=session_id,
                            explicit_task_id=request.feedback_task_id,
                            content=request.content,
                        )

                        if feedback_target:
                            state = await agent_orchestrator.handle_user_feedback(
                                session_id=session_id,
                                task_id=feedback_target.id,
                                feedback=request.content,
                                base_result=_extract_result_payload(feedback_target),
                                user_id=request.user_id,
                                room_id=request.room_id,
                                ws_sender=ws_sender,
                            )
                            await _persist_task_outputs(session_result, feedback_target, state)
                            continue

                        task = Task(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            intent=request.content,
                            status="pending",
                        )
                        session_result.add(task)
                        await session_result.commit()
                        await session_result.refresh(task)

                        state = await agent_orchestrator.execute_workflow(
                            session_id=session_id,
                            task_id=task.id,
                            intent=request.content,
                            user_id=request.user_id,
                            room_id=request.room_id,
                            presentation_scene=request.presentation_scene,
                            ws_sender=ws_sender,
                        )

                        await _persist_task_outputs(session_result, task, state)
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception:
        manager.disconnect(websocket, session_id)
