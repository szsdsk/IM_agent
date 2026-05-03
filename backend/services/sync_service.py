"""多端状态同步服务。

这个模块是 Web 端、多标签页、移动端和飞书 Bot 的统一事件出口。
所有实时消息都先归一化为 SyncEvent，再推送给订阅了同一 session 的客户端。
"""

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.config import settings

logger = logging.getLogger(__name__)

SendCallback = Callable[[Dict[str, Any]], Awaitable[None]]


class EventType(Enum):
    """前后端共享的同步事件类型。"""

    MESSAGE_CREATED = "message.created"
    TASK_CREATED = "task.created"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    ARTIFACT_UPDATED = "artifact.updated"
    DOC_UPDATED = "doc.updated"
    SLIDES_UPDATED = "slides.updated"
    CANVAS_UPDATED = "canvas.updated"
    DELIVERY_CREATED = "delivery.created"
    SESSION_SYNC = "session.sync"
    USER_JOINED = "user.joined"
    USER_LEFT = "user.left"
    SYNC_REQUEST = "sync.request"
    SYNC_RESPONSE = "sync.response"


@dataclass
class SyncEvent:
    """统一同步事件结构。

    data 会同时保留在 data 字段中，并平铺到顶层，兼容旧前端直接读取 step/progress/result 的逻辑。
    """

    type: str
    session_id: str
    event_id: str
    task_id: Optional[str] = None
    artifact_id: Optional[str] = None
    user_id: Optional[str] = None
    source_client_id: Optional[str] = None
    device_type: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    source: str = "server"

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.data is None:
            self.data = {}

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        # 老前端读取 task.progress 的 step/progress/status 是顶层字段，保留平铺避免协议破坏。
        if isinstance(self.data, dict):
            for key, value in self.data.items():
                payload.setdefault(key, value)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class SyncService:
    """多端同步服务。

    内存模式用于本地 Demo；Redis 模式保留扩展点，后续部署多进程时再打开。
    """

    def __init__(self) -> None:
        self._redis_client = None
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._use_memory_mode = True
        self._connected_clients: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._client_subscriptions: Dict[str, str] = {}

    async def initialize(self) -> None:
        """初始化同步服务。"""
        if not settings.DEBUG:
            await self._init_redis()
        else:
            logger.info("Running in memory sync mode (DEBUG=true)")

    async def _init_redis(self) -> None:
        """尝试初始化 Redis；失败时自动退回内存模式。"""
        try:
            import redis.asyncio as redis

            self._redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
            await self._redis_client.ping()
            self._pubsub = self._redis_client.pubsub()
            self._use_memory_mode = False
            logger.info("Redis sync enabled")
        except Exception as exc:
            logger.warning("Redis not available, using memory mode: %s", exc)
            self._use_memory_mode = True

    async def subscribe(
        self,
        session_id: str,
        client_id: str,
        device_type: str = "web",
        send: Optional[SendCallback] = None,
    ) -> None:
        """订阅一个 session 的实时事件。"""
        if not client_id:
            client_id = str(uuid.uuid4())
        self._connected_clients.setdefault(session_id, {})[client_id] = {
            "device_type": device_type or "web",
            "connected_at": datetime.utcnow().isoformat(),
            "send": send,
        }
        self._client_subscriptions[client_id] = session_id
        logger.info("Client %s subscribed to session %s as %s", client_id, session_id, device_type)

    async def unsubscribe(self, client_id: str) -> None:
        """取消客户端订阅。"""
        session_id = self._client_subscriptions.pop(client_id, None)
        if session_id and session_id in self._connected_clients:
            self._connected_clients[session_id].pop(client_id, None)
            if not self._connected_clients[session_id]:
                self._connected_clients.pop(session_id, None)
        logger.info("Client %s unsubscribed", client_id)

    async def publish(
        self,
        event_type: EventType,
        session_id: str,
        data: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
        user_id: Optional[str] = None,
        source_client_id: Optional[str] = None,
        device_type: Optional[str] = None,
        exclude_client: Optional[str] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        """发布一个同步事件，并返回最终发送的事件字典。"""
        event = SyncEvent(
            type=event_type.value,
            session_id=session_id,
            event_id=str(uuid.uuid4()),
            task_id=task_id,
            artifact_id=artifact_id,
            user_id=user_id,
            source_client_id=source_client_id,
            device_type=device_type,
            data=data or {},
        )

        event_dict = event.to_dict()
        if persist and task_id:
            await self._persist_event(event_dict)

        if self._use_memory_mode:
            await self._publish_to_memory(event, exclude_client=exclude_client)
        else:
            await self._publish_to_redis(event)
        return event_dict

    async def _persist_event(self, event: Dict[str, Any]) -> None:
        """将事件写入现有 Event 表，作为刷新恢复和调试的轻量事件日志。"""
        try:
            from backend.database.connection import async_session_maker
            from backend.database.models import Event

            async with async_session_maker() as db:
                db.add(
                    Event(
                        id=event["event_id"],
                        task_id=event.get("task_id"),
                        session_id=event.get("session_id"),
                        event_type=event["type"],
                        client_id=event.get("source_client_id"),
                        device_type=event.get("device_type"),
                        payload={
                            "artifact_id": event.get("artifact_id"),
                            "user_id": event.get("user_id"),
                            "source": event.get("source"),
                            **(event.get("data") or {}),
                        },
                    )
                )
                await db.commit()
        except Exception as exc:
            if "no column named session_id" in str(exc):
                await self._persist_event_legacy(event)
                return
            # 同步推送不能因为事件日志失败而中断主流程。
            logger.warning("Failed to persist sync event %s: %s", event.get("type"), exc)

    async def _persist_event_legacy(self, event: Dict[str, Any]) -> None:
        """兼容测试库或旧 SQLite 表：只写旧 events 表已有字段。"""
        try:
            from backend.database.connection import async_session_maker
            from backend.database.models import Event

            async with async_session_maker() as db:
                await db.execute(
                    Event.__table__.insert().values(
                        id=event["event_id"],
                        task_id=event.get("task_id"),
                        event_type=event["type"],
                        payload={
                            "session_id": event.get("session_id"),
                            "client_id": event.get("source_client_id"),
                            "device_type": event.get("device_type"),
                            "artifact_id": event.get("artifact_id"),
                            "user_id": event.get("user_id"),
                            "source": event.get("source"),
                            **(event.get("data") or {}),
                        },
                    )
                )
                await db.commit()
        except Exception as legacy_exc:
            logger.warning("Failed to persist legacy sync event %s: %s", event.get("type"), legacy_exc)

    async def _publish_to_memory(self, event: SyncEvent, exclude_client: Optional[str] = None) -> None:
        """内存模式下直接把事件推给同 session 的所有 WebSocket 客户端。"""
        clients = self._connected_clients.get(event.session_id, {})
        event_dict = event.to_dict()
        dead_clients: List[str] = []
        for client_id, info in list(clients.items()):
            if exclude_client and client_id == exclude_client:
                continue
            send = info.get("send")
            if not send:
                continue
            try:
                await send(event_dict)
            except Exception as exc:
                logger.warning("WebSocket send failed for client %s: %s", client_id, exc)
                dead_clients.append(client_id)

        for client_id in dead_clients:
            await self.unsubscribe(client_id)

    async def _publish_to_redis(self, event: SyncEvent) -> None:
        """Redis 模式发布事件；本地单进程仍会同时推送内存连接。"""
        if self._redis_client:
            await self._redis_client.publish(f"sync:{event.session_id}", event.to_json())
        await self._publish_to_memory(event)

    async def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        """向单个客户端发送消息，用于连接后的 session.sync 快照。"""
        session_id = self._client_subscriptions.get(client_id)
        if not session_id:
            return False
        client = self._connected_clients.get(session_id, {}).get(client_id)
        send = client.get("send") if client else None
        if not send:
            return False
        await send(message)
        return True

    async def broadcast_task_progress(
        self,
        session_id: str,
        task_id: str,
        step: str,
        progress: float,
        message: str,
        client_id: Optional[str] = None,
    ) -> None:
        """广播任务进度。"""
        await self.publish(
            event_type=EventType.TASK_PROGRESS,
            session_id=session_id,
            task_id=task_id,
            source_client_id=client_id,
            data={
                "step": step,
                "progress": progress,
                "message": message,
                "status": "running",
            },
        )

    async def broadcast_task_finished(
        self,
        session_id: str,
        task_id: str,
        result: Optional[Dict[str, Any]],
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """广播任务完成或失败。"""
        event_type = EventType.TASK_COMPLETED if status == "completed" else EventType.TASK_FAILED
        await self.publish(
            event_type=event_type,
            session_id=session_id,
            task_id=task_id,
            data={
                "result": result,
                "status": status,
                "error": error,
            },
        )

    async def broadcast_artifact_update(
        self,
        session_id: str,
        task_id: str,
        artifact_type: str,
        artifact: Dict[str, Any],
        artifact_id: Optional[str] = None,
    ) -> None:
        """广播文档、PPT、画布等产物更新。"""
        await self.publish(
            event_type=EventType.ARTIFACT_UPDATED,
            session_id=session_id,
            task_id=task_id,
            artifact_id=artifact_id,
            data={
                "artifact_type": artifact_type,
                "artifact": artifact,
            },
        )

    async def broadcast_doc_update(
        self,
        session_id: str,
        task_id: str,
        doc_id: str,
        changes: Dict[str, Any],
        client_id: Optional[str] = None,
    ) -> None:
        """广播飞书或本地文档更新。"""
        await self.publish(
            event_type=EventType.DOC_UPDATED,
            session_id=session_id,
            task_id=task_id,
            artifact_id=doc_id,
            source_client_id=client_id,
            data={
                "doc_id": doc_id,
                "changes": changes,
            },
        )

    async def broadcast_delivery(
        self,
        session_id: str,
        task_id: str,
        delivery: Dict[str, Any],
    ) -> None:
        """广播交付记录。"""
        await self.publish(
            event_type=EventType.DELIVERY_CREATED,
            session_id=session_id,
            task_id=task_id,
            data={"delivery": delivery},
        )

    async def request_sync(self, session_id: str, client_id: str) -> Optional[Dict[str, Any]]:
        """保留旧接口；实际快照由 API 层查询数据库生成。"""
        await self.publish(
            event_type=EventType.SYNC_REQUEST,
            session_id=session_id,
            user_id=client_id,
            source_client_id=client_id,
            data={"requesting_client": client_id},
            persist=False,
        )
        return None

    async def get_session_clients(self, session_id: str) -> List[str]:
        """获取当前 session 的在线客户端 ID。"""
        return list(self._connected_clients.get(session_id, {}).keys())

    async def shutdown(self) -> None:
        """关闭同步服务。"""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._redis_client:
            await self._redis_client.close()


sync_service = SyncService()


class ConflictResolver:
    """轻量冲突解决器。

    Demo 阶段采用服务端最新版本优先，不做 CRDT/OT。
    """

    @staticmethod
    def resolve_doc_conflict(
        local_version: Dict[str, Any],
        remote_version: Dict[str, Any],
        base_version: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """按更新时间选择最新版本。"""
        if base_version is None:
            return remote_version
        local_time = local_version.get("updated_at", "")
        remote_time = remote_version.get("updated_at", "")
        return remote_version if remote_time >= local_time else local_version

    @staticmethod
    def create_patch_proposal(original: Dict[str, Any], proposed: Dict[str, Any]) -> Dict[str, Any]:
        """生成轻量修改建议，供后续人工确认。"""
        patches = []
        for key, value in proposed.items():
            if key not in original:
                patches.append({"type": "add", "key": key, "value": value})
            elif original[key] != value:
                patches.append({"type": "update", "key": key, "old_value": original[key], "new_value": value})
        return {
            "proposed_by": "agent",
            "patches": patches,
            "timestamp": datetime.utcnow().isoformat(),
        }
