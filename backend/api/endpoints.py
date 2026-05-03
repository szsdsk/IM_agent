import json
import logging
import re
import socket
import uuid
from difflib import unified_diff
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.agent.orchestrator import agent_orchestrator
from backend.config import settings
from backend.api.schemas import (
    CanvasUpdateRequest,
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
from backend.services.lark_bot_service import build_delivery_status_card, lark_bot_service
from backend.services.speech_service import speech_service
from backend.services.sync_service import EventType, sync_service

router = APIRouter()

logger = logging.getLogger(__name__)


def _extract_lark_card_action(payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    """兼容飞书卡片回调的新旧 payload 结构，统一取出按钮 action、value 和操作者 open_id。"""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = payload.get("action") if isinstance(payload.get("action"), dict) else event.get("action", {})
    if not isinstance(action, dict):
        action = {}

    action_value = action.get("value", {})
    if isinstance(action_value, str):
        try:
            action_value = json.loads(action_value)
        except json.JSONDecodeError:
            action_value = {}
    if not isinstance(action_value, dict):
        action_value = {}

    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    operator_id = operator.get("operator_id") if isinstance(operator.get("operator_id"), dict) else {}
    open_id = (
        payload.get("open_id")
        or operator.get("open_id")
        or operator_id.get("open_id")
        or operator_id.get("user_id")
        or ""
    )

    return action, action_value, open_id


def _lark_card_toast(content: str, toast_type: str = "success", card: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """飞书卡片回调需要快速返回 toast；传入 card 时会同步替换原卡片。"""
    response: Dict[str, Any] = {
        "toast": {
            "type": toast_type,
            "content": content,
            "i18n": {
                "zh_cn": content,
                "en_us": content,
            },
        }
    }
    if card:
        # 飞书卡片回调要求用 raw/data 包一层，客户端才会把原卡片替换为新卡片。
        response["card"] = {"type": "raw", "data": card}
    return response


def _build_lark_delivery_status_card(
    task: Task,
    status_text: str,
    detail: str = None,
    template: str = "green",
) -> Dict[str, Any]:
    """从任务结果中提取交付摘要，生成用于替换旧卡片的只读状态卡。"""
    result = _extract_result_payload(task)
    doc_info = result.get("document") or result.get("doc") or {}
    slides_info = result.get("slides") or result.get("deck") or {}

    return build_delivery_status_card(
        task_id=task.id,
        status_text=status_text,
        detail=detail,
        template=template,
        doc_title=doc_info.get("title") if isinstance(doc_info, dict) else None,
        doc_url=(
            doc_info.get("lark_doc_url")
            or doc_info.get("doc_url")
            or doc_info.get("url")
            if isinstance(doc_info, dict)
            else None
        ),
        slides_title=slides_info.get("title") if isinstance(slides_info, dict) else None,
        slides_count=slides_info.get("slides_count", 0) if isinstance(slides_info, dict) else 0,
    )


def _build_doc_diff_summary(old_content: str, new_content: str, limit: int = 12) -> Dict[str, Any]:
    """生成轻量级文本差异摘要，避免把完整远端文档 diff 推给前端。"""
    diff_lines = list(
        unified_diff(
            (old_content or "").splitlines(),
            (new_content or "").splitlines(),
            fromfile="local",
            tofile="feishu",
            lineterm="",
        )
    )
    changed_lines = [
        line for line in diff_lines
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    return {
        "changed_lines": len(changed_lines),
        "diff_summary": "\n".join(changed_lines[:limit]) if changed_lines else "内容无变化",
    }


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


def _task_canvas_payload(task: Task) -> Optional[Dict[str, Any]]:
    """从任务结果中取出画布产物，供快照恢复和本地编辑保存复用。"""
    result = _extract_result_payload(task)
    canvas = result.get("canvas")
    return canvas if isinstance(canvas, dict) else None


def _has_slide_pages(payload: Any) -> bool:
    """判断结果中是否真的包含可预览的 PPT 页面。"""
    return isinstance(payload, dict) and bool(payload.get("slides"))


def _iso(value: Any) -> Optional[str]:
    """把 datetime 安全转换成前端可消费的 ISO 字符串。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()
    return str(value)


def _utc_datetime(value: datetime) -> datetime:
    """把数据库中的 naive UTC datetime 转成带时区对象，避免前端误按本地时间解析。"""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _task_to_dict(task: Task) -> Dict[str, Any]:
    """序列化任务，供 session 快照和 WebSocket 同步使用。"""
    return {
        "id": task.id,
        "session_id": task.session_id,
        "intent": task.intent,
        "status": task.status,
        "current_step": task.current_step,
        "progress": task.progress,
        "result_json": task.result_json,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
    }


def _document_to_dict(document: Document) -> Dict[str, Any]:
    """序列化文档产物。"""
    return {
        "id": document.id,
        "task_id": document.task_id,
        "content": document.content,
        "version": document.version,
        "lark_doc_id": document.lark_doc_id,
        "lark_doc_url": document.lark_doc_url,
        "doc_url": document.lark_doc_url,
        "last_edited_by": document.last_edited_by,
        "last_edited_at": _iso(document.last_edited_at),
        "created_at": _iso(document.created_at),
    }


def _slide_to_dict(slide: Slide) -> Dict[str, Any]:
    """序列化 PPT 产物。"""
    return {
        "id": slide.id,
        "task_id": slide.task_id,
        "slides_json": slide.slides_json,
        "file_path": slide.file_path,
        "created_at": _iso(slide.created_at),
    }


def _event_to_message(event: Event, session_id: str) -> Optional[MessageResponse]:
    """把 message.created 事件还原为聊天消息。"""
    payload = event.payload or {}
    content = payload.get("content")
    if not content:
        return None
    return MessageResponse(
        id=event.id,
        session_id=event.session_id or session_id,
        role=payload.get("role", "system"),
        content=content,
        timestamp=_utc_datetime(event.created_at),
    )


def _compact_memory_text(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _task_memory_summary(task: Task) -> Optional[Dict[str, str]]:
    if not isinstance(task.result_json, dict):
        return None
    result = task.result_json.get("result")
    if not isinstance(result, dict):
        return None

    lines = [f"Previous task: {task.intent}"]
    doc = result.get("document") or result.get("doc") or {}
    if isinstance(doc, dict) and (doc.get("title") or doc.get("preview") or doc.get("content")):
        lines.append(f"Document: {doc.get('title') or 'untitled'}")
        preview = doc.get("preview") or doc.get("content")
        if preview:
            lines.append(f"Document preview: {_compact_memory_text(preview, 500)}")

    slides = result.get("slides") or result.get("deck") or {}
    if isinstance(slides, dict) and (slides.get("title") or slides.get("slides")):
        lines.append(f"Slides: {slides.get('title') or 'untitled'}")
        slide_titles = [
            str(slide.get("title") or "").strip()
            for slide in (slides.get("slides") or [])[:8]
            if isinstance(slide, dict) and str(slide.get("title") or "").strip()
        ]
        if slide_titles:
            lines.append("Slide titles: " + " / ".join(slide_titles))

    canvas = result.get("canvas") or {}
    if isinstance(canvas, dict) and canvas.get("title"):
        lines.append(f"Canvas: {canvas.get('title')}")

    if len(lines) <= 1:
        return None
    return {
        "role": "system",
        "content": "\n".join(lines),
        "source": "short_term_memory",
    }


async def _build_short_term_memory(
    db: AsyncSession,
    session_id: str,
    message_limit: int = 12,
    task_limit: int = 3,
) -> list[Dict[str, str]]:
    """Build lightweight GPT-style window memory from this session."""
    task_result = await db.execute(
        select(Task)
        .where(Task.session_id == session_id)
        .order_by(Task.updated_at.desc(), Task.created_at.desc())
        .limit(task_limit)
    )
    task_summaries = [
        summary
        for summary in (_task_memory_summary(task) for task in reversed(task_result.scalars().all()))
        if summary
    ]

    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id, Event.event_type == "message.created")
        .order_by(Event.created_at.desc())
        .limit(message_limit)
    )
    chat_messages: list[Dict[str, str]] = []
    for event in reversed(event_result.scalars().all()):
        payload = event.payload or {}
        content = _compact_memory_text(payload.get("content"), 900)
        if not content:
            continue
        role = str(payload.get("role") or "user")
        chat_messages.append({
            "role": role if role in {"user", "assistant", "system"} else "user",
            "content": content,
            "source": "session_message",
        })

    return (task_summaries + chat_messages)[-24:]


def _task_delivery_confirmed(task: Task) -> bool:
    """判断任务是否已经确认交付，确认后不再允许继续修改。"""
    return isinstance(task.result_json, dict) and bool(task.result_json.get("delivery_confirmed"))


def _get_local_lan_ip() -> Optional[str]:
    """获取本机局域网 IP，用于前端生成手机可访问的同步链接。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # UDP connect 不会真正发送数据，只用于让系统选择默认出网网卡。
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        return None
    return None


async def _build_session_state(db: AsyncSession, session_id: str) -> Dict[str, Any]:
    """构建完整 session 快照，供刷新恢复和新设备加入时同步。"""
    session_result = await db.execute(select(Session).where(Session.id == session_id))
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task_result = await db.execute(
        select(Task).where(Task.session_id == session_id).order_by(Task.created_at)
    )
    tasks = task_result.scalars().all()
    task_ids = [task.id for task in tasks]

    documents: list[Document] = []
    slides: list[Slide] = []
    events: list[Event] = []
    if task_ids:
        doc_result = await db.execute(select(Document).where(Document.task_id.in_(task_ids)))
        documents = doc_result.scalars().all()
        slide_result = await db.execute(select(Slide).where(Slide.task_id.in_(task_ids)))
        slides = slide_result.scalars().all()
        event_result = await db.execute(
            select(Event)
            .where(or_(Event.session_id == session_id, Event.task_id.in_(task_ids)))
            .order_by(Event.created_at)
        )
        events = event_result.scalars().all()
    else:
        event_result = await db.execute(
            select(Event).where(Event.session_id == session_id).order_by(Event.created_at)
        )
        events = event_result.scalars().all()

    messages = [
        message
        for message in (_event_to_message(event, session_id) for event in events if event.event_type == "message.created")
        if message is not None
    ]
    latest_task = tasks[-1] if tasks else None
    latest_doc = documents[-1] if documents else None
    latest_slide = slides[-1] if slides else None
    latest_canvas = next(
        (canvas for canvas in (_task_canvas_payload(task) for task in reversed(tasks)) if canvas),
        None,
    )

    return {
        "session": {
            "id": session.id,
            "user_id": session.user_id,
            "status": session.status,
            "created_at": _iso(session.created_at),
            "updated_at": _iso(session.updated_at),
        },
        "tasks": [_task_to_dict(task) for task in tasks],
        "task": _task_to_dict(latest_task) if latest_task else None,
        "documents": [_document_to_dict(document) for document in documents],
        "doc": _document_to_dict(latest_doc) if latest_doc else None,
        "slides_artifacts": [_slide_to_dict(slide) for slide in slides],
        "slides": _slide_to_dict(latest_slide) if latest_slide else None,
        "canvas": latest_canvas,
        "messages": [message.model_dump(mode="json") for message in messages],
        "events": [
            {
                "event_id": event.id,
                "type": event.event_type,
                "task_id": event.task_id,
                "session_id": event.session_id or session_id,
                "payload": event.payload or {},
                "timestamp": _iso(event.created_at),
            }
            for event in events[-80:]
        ],
        "last_event_id": events[-1].id if events else None,
    }


async def _publish_user_message(
    session_id: str,
    task_id: str,
    content: str,
    request: SendMessageRequest,
    exclude_source: bool = True,
) -> None:
    """把用户输入作为 message.created 事件广播并落库。"""
    await sync_service.publish(
        event_type=EventType.MESSAGE_CREATED,
        session_id=session_id,
        task_id=task_id,
        user_id=request.user_id,
        source_client_id=request.client_id,
        device_type=request.device_type,
        exclude_client=request.client_id if exclude_source else None,
        data={
            "role": "user",
            "content": content,
            "feedback_task_id": request.feedback_task_id,
            "presentation_scene": request.presentation_scene,
            "room_id": request.room_id,
        },
    )


async def _build_feedback_base_result(db: AsyncSession, task: Task) -> Dict[str, Any]:
    """从任务结果和独立产物表恢复反馈修改所需的基准内容。"""
    result = dict(_extract_result_payload(task))

    slide_payload = result.get("slides") or result.get("deck")
    if not _has_slide_pages(slide_payload):
        slide_result = await db.execute(select(Slide).where(Slide.task_id == task.id))
        slide_record = slide_result.scalar_one_or_none()
        if slide_record and _has_slide_pages(slide_record.slides_json):
            slide_payload = dict(slide_record.slides_json)
            slide_payload["file_path"] = slide_payload.get("file_path") or slide_record.file_path
            result["slides"] = slide_payload
            result["deck"] = slide_payload

    doc_payload = result.get("document") or result.get("doc")
    if not isinstance(doc_payload, dict) or not doc_payload.get("content"):
        doc_result = await db.execute(select(Document).where(Document.task_id == task.id))
        doc_record = doc_result.scalar_one_or_none()
        if doc_record and doc_record.content:
            doc_payload = {
                "doc_id": doc_record.id,
                "title": task.intent,
                "content": doc_record.content,
                "preview": doc_record.content[:500],
                "doc_url": doc_record.lark_doc_url,
                "lark_doc_id": doc_record.lark_doc_id,
                "lark_doc_url": doc_record.lark_doc_url,
                "version": doc_record.version,
                "last_edited_by": doc_record.last_edited_by,
                "last_edited_at": doc_record.last_edited_at.isoformat() if doc_record.last_edited_at else None,
            }
            result["document"] = doc_payload
            result["doc"] = doc_payload

    return result


def _has_slide_reference(text: str) -> bool:
    """识别“第 N 页 / slide N / page N”这类局部修改目标。"""
    return bool(
        re.search(r"第\s*[0-9一二两三四五六七八九十百]+\s*[页張张]", text)
        or re.search(r"(slide|page|p)\s*#?\s*[0-9]+", text, flags=re.IGNORECASE)
    )


def _looks_like_new_generation(content: str) -> bool:
    """区分“新建一个 PPT”和“修改上一份 PPT”，避免新任务被误判成反馈。"""
    text = (content or "").lower()
    create_markers = ["生成", "创建", "制作", "做一个", "做一份", "新建", "写一个", "来一个", "create", "generate", "make"]
    artifact_markers = ["ppt", "演示", "幻灯片", "deck", "slides", "文档", "报告", "画布", "流程图"]
    revision_markers = ["修改", "调整", "优化", "替换", "删掉", "删除", "补充", "改成", "更详细", "丰富", "具体一点"]
    return (
        any(marker in text for marker in create_markers)
        and any(marker in text for marker in artifact_markers)
        and not _has_slide_reference(text)
        and not any(marker in text for marker in revision_markers)
    )


def _looks_like_feedback(content: str) -> bool:
    text = (content or "").lower()
    if _looks_like_new_generation(text):
        return False

    revision_markers = [
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
        "更详细",
        "丰富",
        "具体一点",
        "换成",
    ]
    rehearsal_markers = [
        "排练",
        "演练",
        "讲稿",
        "问答",
        "q&a",
        "qa",
        "问题",
    ]
    return (
        _has_slide_reference(text)
        or any(marker in text for marker in revision_markers)
        or any(marker in text for marker in rehearsal_markers)
    )


def _room_can_mutate_task(task: Task, room_id: Optional[str]) -> bool:
    """限制飞书侧跨群修改任务；网页本地请求不带 room_id 时保持兼容。"""
    if not room_id:
        return True
    task_chat_id = None
    if isinstance(task.result_json, dict):
        task_chat_id = task.result_json.get("chat_id")
    allowed_rooms = {item for item in [task_chat_id, settings.LARK_DEFAULT_CHAT_ID] if item}
    return not allowed_rooms or room_id in allowed_rooms


def _task_matches_pending_lark_feedback(task: Task, room_id: Optional[str], user_id: Optional[str]) -> bool:
    """判断飞书任务是否正等待当前聊天里的下一条修改意见。"""
    if not room_id or not isinstance(task.result_json, dict):
        return False

    pending = task.result_json.get("pending_feedback")
    if not isinstance(pending, dict):
        return False
    if pending.get("chat_id") != room_id:
        return False

    requested_by = pending.get("user_id")
    return not requested_by or not user_id or requested_by == user_id


async def _sync_lark_doc_edit(
    doc_id: str,
    task_id: Optional[str] = None,
    editor: Optional[str] = None,
    source: str = "card_callback",
    chat_id: Optional[str] = None,
) -> Dict[str, Any]:
    """拉取飞书文档最新内容，更新本地文档版本，并广播差异摘要。"""
    resolved_task_id = task_id
    session_id = None
    doc_record_id = None

    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.lark_doc_id == doc_id))
        doc_record = result.scalar_one_or_none()
        if not doc_record:
            logger.warning("Lark doc sync skipped: document %s is not linked locally", doc_id)
            return {"success": False, "error": "Document is not linked locally."}

        resolved_task_id = resolved_task_id or doc_record.task_id
        task_result = await db.execute(select(Task).where(Task.id == resolved_task_id))
        task_record = task_result.scalar_one_or_none()
        if task_record and not _room_can_mutate_task(task_record, chat_id):
            logger.warning("Lark doc sync rejected: room %s cannot mutate task %s", chat_id, resolved_task_id)
            return {"success": False, "error": "Room is not allowed to modify the task."}

        session_id = task_record.session_id if task_record else resolved_task_id
        doc_record_id = doc_record.id

    remote_result = await lark_bot_service.get_doc_raw_content(doc_id)
    if not remote_result.get("success"):
        logger.warning("Lark doc sync failed: %s", remote_result.get("error"))
        if chat_id and lark_bot_service.is_configured:
            await lark_bot_service.send_text(chat_id, f"飞书文档同步失败：{remote_result.get('error') or '未知错误'}")
        return {"success": False, "error": remote_result.get("error") or "Failed to fetch Feishu doc content."}

    remote_content = remote_result.get("content") or ""
    now = datetime.utcnow()

    async with async_session_maker() as db:
        result = await db.execute(select(Document).where(Document.id == doc_record_id))
        doc_record = result.scalar_one_or_none()
        if not doc_record:
            return {"success": False, "error": "Document disappeared during sync."}

        old_content = doc_record.content or ""
        old_version = doc_record.version or 1
        diff_info = _build_doc_diff_summary(old_content, remote_content)
        new_version = old_version + 1

        doc_record.content = remote_content
        doc_record.version = new_version
        doc_record.last_edited_by = editor
        doc_record.last_edited_at = now

        event_payload = {
            "doc_id": doc_id,
            "document_id": doc_record.id,
            "old_version": old_version,
            "new_version": new_version,
            "source": source,
            "editor": editor,
            "changed_lines": diff_info["changed_lines"],
            "diff_summary": diff_info["diff_summary"],
        }
        db.add(Event(
            id=str(uuid.uuid4()),
            task_id=resolved_task_id or doc_record.task_id,
            session_id=session_id,
            event_type="document.version_updated",
            client_id=None,
            device_type="lark",
            payload=event_payload,
        ))
        await db.commit()

    changes = {
        "lark_doc_id": doc_id,
        "content": remote_content,
        "last_edited_by": editor,
        "last_edited_at": now.isoformat(),
        "version": new_version,
        "source": source,
        "changed_lines": diff_info["changed_lines"],
        "diff_summary": diff_info["diff_summary"],
    }

    await sync_service.broadcast_doc_update(
        session_id=session_id or resolved_task_id or doc_id,
        task_id=resolved_task_id,
        doc_id=doc_record_id or doc_id,
        changes=changes,
    )

    if chat_id and lark_bot_service.is_configured:
        await lark_bot_service.send_text(chat_id, f"文档已更新，版本 v{new_version}，状态已同步。")

    return {"success": True, "version": new_version, **diff_info}


async def _persist_task_outputs(db: AsyncSession, task: Task, state: Dict[str, Any]) -> None:
    updated_document: Optional[Document] = None
    updated_slide: Optional[Slide] = None
    task.status = state["status"]
    task.current_step = state["current_step"]
    task.result_json = {
        "progress": state["progress"],
        "result": state.get("result"),
        "error": state.get("error"),
        "im_context_summary": state.get("im_context_summary"),
        "agent_plan": state.get("agent_plan"),
        "active_agent": state.get("active_agent"),
        "task_results": state.get("task_results"),
        "artifacts": state.get("artifacts"),
        "replans": state.get("replans"),
        "im_provider": task.result_json.get("im_provider") if isinstance(task.result_json, dict) else None,
        "chat_id": task.result_json.get("chat_id") if isinstance(task.result_json, dict) else None,
    }
    task.updated_at = datetime.utcnow()

    if state.get("doc_content"):
        existing_doc_result = await db.execute(
            select(Document)
            .where(Document.task_id == task.id)
            .order_by(Document.updated_at.desc(), Document.created_at.desc())
            .limit(1)
        )
        document = existing_doc_result.scalar_one_or_none()
        if not document:
            document = Document(task_id=task.id)
            db.add(document)
            document.version = 1
        else:
            document.version = (document.version or 1) + 1
        document.content = state["doc_content"].get("content")
        document.lark_doc_id = state["doc_content"].get("lark_doc_id") or document.lark_doc_id
        document.lark_doc_url = state["doc_content"].get("lark_doc_url") or state["doc_content"].get("doc_url") or document.lark_doc_url
        document.updated_at = datetime.utcnow()
        updated_document = document

    if state.get("slides_content"):
        existing_slide_result = await db.execute(
            select(Slide)
            .where(Slide.task_id == task.id)
            .order_by(Slide.updated_at.desc(), Slide.created_at.desc())
            .limit(1)
        )
        slide = existing_slide_result.scalar_one_or_none()
        if not slide:
            slide = Slide(task_id=task.id)
            db.add(slide)
        slide.slides_json = state["slides_content"]
        slide.file_path = state["slides_content"].get("file_path")
        slide.updated_at = datetime.utcnow()
        updated_slide = slide

    await db.commit()
    await db.refresh(task)
    if updated_document:
        await db.refresh(updated_document)
        await sync_service.broadcast_artifact_update(
            session_id=task.session_id,
            task_id=task.id,
            artifact_type="document",
            artifact=_document_to_dict(updated_document),
            artifact_id=updated_document.id,
        )
    if updated_slide:
        await db.refresh(updated_slide)
        await sync_service.broadcast_artifact_update(
            session_id=task.session_id,
            task_id=task.id,
            artifact_type="slides",
            artifact=_slide_to_dict(updated_slide),
            artifact_id=updated_slide.id,
        )


async def _find_feedback_target(
    db: AsyncSession,
    session_id: str,
    explicit_task_id: Optional[str],
    content: str,
    room_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Task]:
    if explicit_task_id:
        if _looks_like_new_generation(content):
            return None
        result = await db.execute(select(Task).where(Task.id == explicit_task_id, Task.session_id == session_id))
        return result.scalar_one_or_none()

    if not _looks_like_feedback(content):
        return None

    if room_id:
        # 飞书卡片点“需要修改”后，下一条同聊天消息应优先绑定该任务；
        # 不能只按个人 session 找，否则群聊/网页混用时容易被当作新需求。
        pending_result = await db.execute(
            select(Task)
            .where(Task.status == "pending", Task.current_step == "confirm_or_modify")
            .order_by(Task.updated_at.desc())
        )
        for task in pending_result.scalars().all():
            if _task_matches_pending_lark_feedback(task, room_id, user_id):
                return task

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
        context_messages = await _build_short_term_memory(db, session.id)

        feedback_target = await _find_feedback_target(
            db=db,
            session_id=session.id,
            explicit_task_id=None,
            content=text,
            room_id=message.get("chat_id"),
            user_id=message.get("user_id"),
        )

        if feedback_target:
            if not _room_can_mutate_task(feedback_target, message.get("chat_id")):
                if message.get("chat_id") and lark_bot_service.is_configured:
                    await lark_bot_service.send_text(message["chat_id"], "该任务不属于当前聊天，已拒绝修改请求。")
                return
            if _task_delivery_confirmed(feedback_target):
                if message.get("chat_id") and lark_bot_service.is_configured:
                    await lark_bot_service.send_text(message["chat_id"], "任务已经确认交付，不能继续修改。请发送一个新的需求重新生成。")
                return

            lark_request = SendMessageRequest(
                content=text,
                user_id=message.get("user_id"),
                room_id=message.get("chat_id"),
                client_id=f"lark-{message.get('message_id') or message.get('user_id') or uuid.uuid4()}",
                device_type="bot",
            )
            await _publish_user_message(session.id, feedback_target.id, text, lark_request)
            state = await agent_orchestrator.handle_user_feedback(
                session_id=session.id,
                task_id=feedback_target.id,
                feedback=text,
                base_result=await _build_feedback_base_result(db, feedback_target),
                user_id=message.get("user_id"),
                room_id=message.get("chat_id"),
                context_messages=context_messages,
                ws_sender=None,
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

        lark_request = SendMessageRequest(
            content=text,
            user_id=message.get("user_id"),
            room_id=message.get("chat_id"),
            client_id=f"lark-{message.get('message_id') or message.get('user_id') or uuid.uuid4()}",
            device_type="bot",
        )
        await _publish_user_message(session.id, task.id, text, lark_request)
        await sync_service.publish(
            event_type=EventType.TASK_CREATED,
            session_id=session.id,
            task_id=task.id,
            user_id=message.get("user_id"),
            source_client_id=lark_request.client_id,
            device_type="bot",
            data={"task": _task_to_dict(task)},
        )

        state = await agent_orchestrator.execute_workflow(
            session_id=session.id,
            task_id=task.id,
            intent=text,
            user_id=message.get("user_id"),
            room_id=message.get("chat_id"),
            context_messages=context_messages,
            ws_sender=None,
        )

        task.result_json = {
            "im_provider": "lark",
            "chat_id": message.get("chat_id"),
            "message_id": message.get("message_id"),
        }
        await _persist_task_outputs(db, task, state)


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    # 网页端只需要知道后端是否存活，飞书同步状态不再作为网页能力暴露。
    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow(),
        local_ip=_get_local_lan_ip(),
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
    if lark_bot_service.is_url_verification(payload):
        if not lark_bot_service.verify_event(payload):
            raise HTTPException(status_code=403, detail="Invalid verification token")
        return {"challenge": payload["challenge"]}

    if not lark_bot_service.verify_event(payload):
        raise HTTPException(status_code=403, detail="Invalid verification token")

    action, action_value, open_id = _extract_lark_card_action(payload)
    action_type = action.get("tag", "")

    logger.info(
        "Lark card action: type=%s, value=%s, user=%s",
        action_type, action_value, open_id,
    )

    task_id = action_value.get("task_id", "")
    action_name = action_value.get("action", "")
    if not action_name:
        return _lark_card_toast("未识别的卡片操作，请重试", "warning")

    if action_name == "confirm_delivery" and task_id:
        task_found = False
        allowed = True
        status_card: Optional[Dict[str, Any]] = None
        async with async_session_maker() as db:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task:
                task_found = True
                if not _room_can_mutate_task(task, action_value.get("chat_id", "")):
                    allowed = False
                else:
                    result_json = dict(task.result_json) if isinstance(task.result_json, dict) else {}
                    result_json["delivery_confirmed"] = {
                        "chat_id": action_value.get("chat_id", ""),
                        "user_id": open_id,
                        "confirmed_at": datetime.utcnow().isoformat(),
                    }
                    result_json.pop("pending_feedback", None)
                    task.status = "completed"
                    task.result_json = result_json
                    task.updated_at = datetime.utcnow()
                    status_card = _build_lark_delivery_status_card(
                        task,
                        "已确认交付",
                        "任务已锁定。如需重新制作，请直接发送一个新的需求。",
                        "green",
                    )
                    await db.commit()
                    await sync_service.publish(
                        event_type=EventType.DELIVERY_CREATED,
                        session_id=task.session_id,
                        task_id=task.id,
                        user_id=open_id,
                        device_type="bot",
                        data={
                            "delivery": {
                                "status": "confirmed",
                                "confirmed_by": open_id,
                                "confirmed_at": result_json["delivery_confirmed"]["confirmed_at"],
                            }
                        },
                    )

        if not task_found:
            return _lark_card_toast("没有找到对应任务", "error")
        if not allowed:
            return _lark_card_toast("当前会话无权操作该任务", "error")

        chat_id = action_value.get("chat_id", "")
        if chat_id and lark_bot_service.is_configured:
            background_tasks.add_task(lark_bot_service.send_text, chat_id, f"任务 {task_id} 已确认交付")
        return _lark_card_toast("已确认交付", card=status_card)

    if action_name == "request_modification" and task_id:
        task_found = False
        allowed = True
        already_confirmed = False
        status_card: Optional[Dict[str, Any]] = None
        async with async_session_maker() as db:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if task:
                task_found = True
                if not _room_can_mutate_task(task, action_value.get("chat_id", "")):
                    allowed = False
                else:
                    result_json = dict(task.result_json) if isinstance(task.result_json, dict) else {}
                    already_confirmed = bool(result_json.get("delivery_confirmed"))
                    if not already_confirmed:
                        task.status = "pending"
                        task.current_step = "confirm_or_modify"
                        result_json["pending_feedback"] = {
                            "chat_id": action_value.get("chat_id", ""),
                            "user_id": open_id,
                            "requested_at": datetime.utcnow().isoformat(),
                        }
                        task.result_json = result_json
                        task.updated_at = datetime.utcnow()
                        status_card = _build_lark_delivery_status_card(
                            task,
                            "等待修改意见",
                            "请直接在当前聊天发送修改意见，例如：第 1 页再详细一点。",
                            "yellow",
                        )
                        await db.commit()
                        await sync_service.publish(
                            event_type=EventType.TASK_PROGRESS,
                            session_id=task.session_id,
                            task_id=task.id,
                            user_id=open_id,
                            device_type="bot",
                            data={
                                "step": "confirm_or_modify",
                                "progress": task.progress,
                                "status": "running",
                                "message": "等待飞书侧修改意见",
                            },
                        )

        if not task_found:
            return _lark_card_toast("没有找到对应任务", "error")
        if not allowed:
            return _lark_card_toast("当前会话无权操作该任务", "error")
        if already_confirmed:
            return _lark_card_toast("任务已确认交付，不能再切换为需要修改", "warning")

        chat_id = action_value.get("chat_id", "")
        if chat_id and lark_bot_service.is_configured:
            background_tasks.add_task(lark_bot_service.send_text, chat_id, f"任务 {task_id} 已标记为需要修改，请发送修改意见。")
        return _lark_card_toast("已标记为需要修改", card=status_card)

    if action_name == "doc_edited":
        # 卡片按钮会携带飞书文档 ID，这里负责把“已编辑完成”状态回写到本地任务。
        doc_id = action_value.get("lark_doc_id")
        if not doc_id:
            return _lark_card_toast("卡片缺少飞书文档 ID", "warning")

        found_task_id = task_id
        if not found_task_id:
            async with async_session_maker() as db:
                result = await db.execute(select(Document).where(Document.lark_doc_id == doc_id))
                doc_record = result.scalar_one_or_none()
                if doc_record:
                    found_task_id = doc_record.task_id
        if not found_task_id:
            return _lark_card_toast("没有找到可同步的飞书文档", "warning")

        async with async_session_maker() as db:
            task_result = await db.execute(select(Task).where(Task.id == found_task_id))
            task_record = task_result.scalar_one_or_none()
            if task_record and not _room_can_mutate_task(task_record, action_value.get("chat_id", "")):
                return _lark_card_toast("当前会话无权操作该任务", "error")
            status_card = (
                _build_lark_delivery_status_card(
                    task_record,
                    "同步飞书编辑中",
                    "已收到飞书文档编辑完成信号，后端正在拉取最新内容并记录版本差异。",
                    "blue",
                )
                if task_record
                else None
            )

        chat_id = action_value.get("chat_id", "")
        background_tasks.add_task(
            _sync_lark_doc_edit,
            doc_id,
            found_task_id,
            open_id,
            "card_callback",
            chat_id,
        )
        return _lark_card_toast("已开始同步飞书文档编辑状态", card=status_card)

    return _lark_card_toast("操作已接收")


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
    if lark_bot_service.is_url_verification(payload):
        if not lark_bot_service.verify_event(payload):
            raise HTTPException(status_code=403, detail="Invalid verification token")
        return {"challenge": payload["challenge"]}

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

    background_tasks.add_task(
        _sync_lark_doc_edit,
        doc_id,
        task_id,
        user_id,
        source,
        None,
    )

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


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task_ids_result = await db.execute(select(Task.id).where(Task.session_id == session_id))
    task_ids = [row[0] for row in task_ids_result.all()]

    if task_ids:
        await db.execute(delete(Document).where(Document.task_id.in_(task_ids)))
        await db.execute(delete(Slide).where(Slide.task_id.in_(task_ids)))
        await db.execute(delete(Event).where(or_(Event.session_id == session_id, Event.task_id.in_(task_ids))))
        await db.execute(delete(Task).where(Task.id.in_(task_ids)))
    else:
        await db.execute(delete(Event).where(Event.session_id == session_id))

    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()
    return {"success": True, "session_id": session_id}


@router.get("/sessions/{session_id}/state")
async def get_session_state(session_id: str, db: AsyncSession = Depends(get_db)):
    """返回完整会话快照，用于多端首次进入、刷新和 WebSocket 重连恢复。"""
    return await _build_session_state(db, session_id)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    task_ids_result = await db.execute(select(Task.id).where(Task.session_id == session_id))
    task_ids = [row[0] for row in task_ids_result.all()]
    result = await db.execute(
        select(Event)
        .where(
            Event.event_type == "message.created",
            or_(Event.session_id == session_id, Event.task_id.in_(task_ids)) if task_ids else Event.session_id == session_id,
        )
        .order_by(Event.created_at)
    )
    events = result.scalars().all()
    return [message for message in (_event_to_message(event, session_id) for event in events) if message]


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
    context_messages = await _build_short_term_memory(db, session_id)

    feedback_target = await _find_feedback_target(
        db=db,
        session_id=session_id,
        explicit_task_id=request.feedback_task_id,
        content=request.content,
        room_id=request.room_id,
        user_id=request.user_id,
    )

    if feedback_target:
        if not _room_can_mutate_task(feedback_target, request.room_id):
            raise HTTPException(status_code=403, detail="This room is not allowed to modify the task")
        if _task_delivery_confirmed(feedback_target):
            raise HTTPException(status_code=409, detail="Task has been confirmed and cannot be modified")
        await _publish_user_message(session_id, feedback_target.id, request.content, request)
        state = await agent_orchestrator.handle_user_feedback(
            session_id=session_id,
            task_id=feedback_target.id,
            feedback=request.content,
            base_result=await _build_feedback_base_result(db, feedback_target),
            user_id=request.user_id,
            room_id=request.room_id or (
                feedback_target.result_json.get("chat_id")
                if isinstance(feedback_target.result_json, dict)
                else None
            ),
            context_messages=context_messages,
            ws_sender=None,
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
    await _publish_user_message(session_id, task.id, request.content, request)
    await sync_service.publish(
        event_type=EventType.TASK_CREATED,
        session_id=session_id,
        task_id=task.id,
        user_id=request.user_id,
        source_client_id=request.client_id,
        device_type=request.device_type,
        data={"task": _task_to_dict(task)},
    )

    state = await agent_orchestrator.execute_workflow(
        session_id=session_id,
        task_id=task.id,
        intent=request.content,
        user_id=request.user_id,
        room_id=request.room_id,
        presentation_scene=request.presentation_scene,
        context_messages=context_messages,
        ws_sender=None,
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


@router.patch("/tasks/{task_id}/canvas")
async def update_task_canvas(
    task_id: str,
    request: CanvasUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """保存网页端本地画布编辑结果，并把最新画布广播给同一 session 的客户端。"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if _task_delivery_confirmed(task):
        raise HTTPException(status_code=409, detail="Task has been confirmed and cannot be modified")

    old_canvas = _task_canvas_payload(task) or {}
    old_metadata = old_canvas.get("metadata") if isinstance(old_canvas.get("metadata"), dict) else {}
    canvas = dict(request.canvas or {})
    if not canvas:
        raise HTTPException(status_code=400, detail="Canvas payload is required")

    metadata = dict(canvas.get("metadata") or {})
    try:
        next_version = int(old_metadata.get("version") or metadata.get("version") or 1) + 1
    except (TypeError, ValueError):
        next_version = 2
    metadata.update({
        "version": next_version,
        "sync_status": metadata.get("sync_status") or old_metadata.get("sync_status") or "local_only",
        "last_edited_at": datetime.utcnow().isoformat(),
        "last_edited_by": request.client_id or "web",
    })
    canvas["metadata"] = metadata
    canvas["provider"] = canvas.get("provider") or old_canvas.get("provider") or "local_canvas"
    canvas["canvas_id"] = canvas.get("canvas_id") or old_canvas.get("canvas_id") or f"canvas_{task.id}"
    canvas["exportable"] = canvas.get("exportable", True)

    result_json = dict(task.result_json) if isinstance(task.result_json, dict) else {}
    result_payload = dict(result_json.get("result")) if isinstance(result_json.get("result"), dict) else {}
    result_payload["canvas"] = canvas
    result_json["result"] = result_payload
    result_json.setdefault("progress", task.progress)
    task.result_json = result_json
    task.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(task)
    await sync_service.broadcast_artifact_update(
        session_id=task.session_id,
        task_id=task.id,
        artifact_type="canvas",
        artifact=canvas,
        artifact_id=canvas.get("canvas_id"),
    )
    return {"success": True, "canvas": canvas, "task": _task_to_dict(task)}


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
        result_json = dict(task.result_json) if isinstance(task.result_json, dict) else {}
        result_json["delivery_confirmed"] = {
            "source": "web",
            "confirmed_at": datetime.utcnow().isoformat(),
        }
        task.status = "completed"
        task.result_json = result_json
        task.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(task)
        await sync_service.publish(
            event_type=EventType.DELIVERY_CREATED,
            session_id=task.session_id,
            task_id=task.id,
            data={"delivery": result_json["delivery_confirmed"]},
        )
        return task

    if request.feedback:
        if _task_delivery_confirmed(task):
            raise HTTPException(status_code=409, detail="Task has been confirmed and cannot be modified")
        state = await agent_orchestrator.handle_user_feedback(
            session_id=task.session_id,
            task_id=task.id,
            feedback=request.feedback,
            base_result=await _build_feedback_base_result(db, task),
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
    result = await db.execute(
        select(Document).where((Document.id == document_id) | (Document.lark_doc_id == document_id))
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}/history")
async def get_document_history(document_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document).where((Document.id == document_id) | (Document.lark_doc_id == document_id))
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    history_result = await db.execute(
        select(Event)
        .where(Event.task_id == document.task_id, Event.event_type == "document.version_updated")
        .order_by(Event.created_at.desc())
        .limit(20)
    )
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "payload": event.payload or {},
            "created_at": event.created_at.isoformat(),
        }
        for event in history_result.scalars().all()
    ]


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
    client_id = websocket.query_params.get("client_id") or str(uuid.uuid4())
    device_type = websocket.query_params.get("device_type") or "web"
    await websocket.accept()
    await sync_service.subscribe(
        session_id=session_id,
        client_id=client_id,
        device_type=device_type,
        send=websocket.send_json,
    )
    try:
        async with async_session_maker() as db:
            snapshot = await _build_session_state(db, session_id)
        await websocket.send_json({
            "type": "session.sync",
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "source_client_id": "server",
            "device_type": device_type,
            "state": snapshot,
            "timestamp": datetime.utcnow().isoformat(),
        })

        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "event_id": str(uuid.uuid4()),
                    "session_id": session_id,
                    "timestamp": datetime.utcnow().isoformat(),
                })
            elif data.get("type") == "message":
                request = SendMessageRequest(
                    content=data.get("content", ""),
                    presentation_scene=data.get("presentation_scene"),
                    feedback_task_id=data.get("feedback_task_id"),
                    user_id=data.get("user_id"),
                    room_id=data.get("room_id"),
                    client_id=client_id,
                    device_type=device_type,
                )
                async with async_session_maker() as session_result:
                    result = await session_result.execute(select(Session).where(Session.id == session_id))
                    session = result.scalar_one_or_none()
                    if session:
                        context_messages = await _build_short_term_memory(session_result, session_id)
                        feedback_target = await _find_feedback_target(
                            db=session_result,
                            session_id=session_id,
                            explicit_task_id=request.feedback_task_id,
                            content=request.content,
                            room_id=request.room_id,
                            user_id=request.user_id,
                        )

                        if feedback_target:
                            if _task_delivery_confirmed(feedback_target):
                                await websocket.send_json({
                                    "type": "task.failed",
                                    "event_id": str(uuid.uuid4()),
                                    "session_id": session_id,
                                    "task_id": feedback_target.id,
                                    "status": "failed",
                                    "error": "Task has been confirmed and cannot be modified",
                                    "timestamp": datetime.utcnow().isoformat(),
                                })
                                continue
                            await _publish_user_message(
                                session_id,
                                feedback_target.id,
                                request.content,
                                request,
                                exclude_source=False,
                            )
                            state = await agent_orchestrator.handle_user_feedback(
                                session_id=session_id,
                                task_id=feedback_target.id,
                                feedback=request.content,
                                base_result=await _build_feedback_base_result(session_result, feedback_target),
                                user_id=request.user_id,
                                room_id=request.room_id,
                                context_messages=context_messages,
                                ws_sender=None,
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
                        await _publish_user_message(
                            session_id,
                            task.id,
                            request.content,
                            request,
                            exclude_source=False,
                        )
                        await sync_service.publish(
                            event_type=EventType.TASK_CREATED,
                            session_id=session_id,
                            task_id=task.id,
                            user_id=request.user_id,
                            source_client_id=client_id,
                            device_type=device_type,
                            data={"task": _task_to_dict(task)},
                        )

                        state = await agent_orchestrator.execute_workflow(
                            session_id=session_id,
                            task_id=task.id,
                            intent=request.content,
                            user_id=request.user_id,
                            room_id=request.room_id,
                            presentation_scene=request.presentation_scene,
                            context_messages=context_messages,
                            ws_sender=None,
                        )

                        await _persist_task_outputs(session_result, task, state)
    except WebSocketDisconnect:
        await sync_service.unsubscribe(client_id)
    except Exception as exc:
        logger.exception("WebSocket session %s client %s failed: %s", session_id, client_id, exc)
        await sync_service.unsubscribe(client_id)
