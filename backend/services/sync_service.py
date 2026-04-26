"""
Sync Service - 多端状态同步服务
基于 Redis Pub/Sub 和 WebSocket 的实时同步
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, Set, Callable, List
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, asdict

from backend.config import settings

logger = logging.getLogger(__name__)


class EventType(Enum):
    """事件类型"""
    TASK_CREATED = "task.created"
    TASK_PROGRESS = "task.progress"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    DOC_UPDATED = "doc.updated"
    SLIDES_UPDATED = "slides.updated"
    CANVAS_UPDATED = "canvas.updated"
    DELIVERY_CREATED = "delivery.created"
    USER_JOINED = "user.joined"
    USER_LEFT = "user.left"
    SYNC_REQUEST = "sync.request"
    SYNC_RESPONSE = "sync.response"


@dataclass
class SyncEvent:
    """同步事件"""
    type: str
    session_id: str
    task_id: Optional[str] = None
    user_id: Optional[str] = None
    data: Dict[str, Any] = None
    timestamp: str = None
    source: str = "server"

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
        if self.data is None:
            self.data = {}

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


class SyncService:
    """多端同步服务"""

    def __init__(self):
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._redis_client = None
        self._pubsub = None
        self._listener_task: Optional[asyncio.Task] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._connected_clients: Dict[str, Set[str]] = {}  # session_id -> set of client_ids
        self._client_subscriptions: Dict[str, Set[str]] = {}  # client_id -> set of session_ids

        # 内存模式（Redis 不可用时）
        self._use_memory_mode = True

    async def initialize(self):
        """初始化连接"""
        if not settings.DEBUG:
            await self._init_redis()
        else:
            logger.info("Running in memory sync mode (DEBUG=true)")

    async def _init_redis(self):
        """初始化 Redis 连接"""
        try:
            import redis.asyncio as redis
            self._redis_client = redis.Redis(
                host="localhost",
                port=6379,
                decode_responses=True,
            )
            await self._redis_client.ping()
            self._pubsub = self._redis_client.pubsub()
            self._use_memory_mode = False
            logger.info("Redis sync enabled")
        except Exception as e:
            logger.warning(f"Redis not available, using memory mode: {e}")
            self._use_memory_mode = True

    async def subscribe(self, session_id: str, client_id: str) -> None:
        """订阅会话"""
        if session_id not in self._subscribers:
            self._subscribers[session_id] = set()

        if session_id not in self._connected_clients:
            self._connected_clients[session_id] = set()
        self._connected_clients[session_id].add(client_id)

        if client_id not in self._client_subscriptions:
            self._client_subscriptions[client_id] = set()
        self._client_subscriptions[client_id].add(session_id)

        logger.info(f"Client {client_id} subscribed to session {session_id}")

    async def unsubscribe(self, client_id: str) -> None:
        """取消订阅"""
        if client_id in self._client_subscriptions:
            for session_id in self._client_subscriptions[client_id]:
                if session_id in self._connected_clients:
                    self._connected_clients[session_id].discard(client_id)
                if session_id in self._subscribers:
                    self._subscribers[session_id].discard(client_id)
            del self._client_subscriptions[client_id]

        logger.info(f"Client {client_id} unsubscribed")

    async def publish(
        self,
        event_type: EventType,
        session_id: str,
        data: Dict[str, Any],
        task_id: str = None,
        user_id: str = None,
        exclude_client: str = None,
    ) -> None:
        """发布事件"""
        event = SyncEvent(
            type=event_type.value,
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            data=data,
        )

        # 内存模式：直接推送给订阅者
        if self._use_memory_mode:
            await self._publish_to_memory(event, exclude_client)
        else:
            # Redis 模式
            await self._publish_to_redis(event)

    async def _publish_to_memory(self, event: SyncEvent, exclude_client: str = None):
        """内存模式推送"""
        session_id = event.session_id

        if session_id in self._subscribers:
            for callback in self._subscribers[session_id]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event.to_dict())
                    else:
                        callback(event.to_dict())
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        # 通过 WebSocket 推送
        if session_id in self._connected_clients:
            from backend.api.endpoints import manager
            for client_id in self._connected_clients[session_id]:
                if client_id != exclude_client:
                    try:
                        await manager.send_to_session(
                            session_id,
                            event.to_dict()
                        )
                    except Exception as e:
                        logger.error(f"WebSocket send error: {e}")

    async def _publish_to_redis(self, event: SyncEvent):
        """Redis 模式推送"""
        channel = f"sync:{event.session_id}"
        await self._redis_client.publish(channel, event.to_json())

    async def broadcast_task_progress(
        self,
        session_id: str,
        task_id: str,
        step: str,
        progress: float,
        message: str,
        client_id: str = None,
    ) -> None:
        """广播任务进度"""
        await self.publish(
            event_type=EventType.TASK_PROGRESS,
            session_id=session_id,
            task_id=task_id,
            data={
                "step": step,
                "progress": progress,
                "message": message,
            },
            exclude_client=client_id,
        )

    async def broadcast_doc_update(
        self,
        session_id: str,
        task_id: str,
        doc_id: str,
        changes: Dict[str, Any],
        client_id: str = None,
    ) -> None:
        """广播文档更新"""
        await self.publish(
            event_type=EventType.DOC_UPDATED,
            session_id=session_id,
            task_id=task_id,
            data={
                "doc_id": doc_id,
                "changes": changes,
            },
            exclude_client=client_id,
        )

    async def broadcast_delivery(
        self,
        session_id: str,
        task_id: str,
        delivery: Dict[str, Any],
    ) -> None:
        """广播交付"""
        await self.publish(
            event_type=EventType.DELIVERY_CREATED,
            session_id=session_id,
            task_id=task_id,
            data={"delivery": delivery},
        )

    async def request_sync(self, session_id: str, client_id: str) -> Optional[Dict]:
        """请求同步当前状态"""
        await self.publish(
            event_type=EventType.SYNC_REQUEST,
            session_id=session_id,
            user_id=client_id,
            data={"requesting_client": client_id},
        )
        return None

    async def get_session_clients(self, session_id: str) -> List[str]:
        """获取会话当前连接的所有客户端"""
        if session_id in self._connected_clients:
            return list(self._connected_clients[session_id])
        return []

    async def shutdown(self):
        """关闭服务"""
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._redis_client:
            await self._redis_client.close()


# 全局实例
sync_service = SyncService()


# ============ Conflict Resolution ============

class ConflictResolver:
    """冲突解决器"""

    @staticmethod
    def resolve_doc_conflict(
        local_version: Dict,
        remote_version: Dict,
        base_version: Dict = None,
    ) -> Dict:
        """
        解决文档冲突

        策略：
        1. 如果 base_version 为空，使用 remote（服务器优先）
        2. 如果都有修改，尝试合并
        3. 返回合并后的版本
        """
        if base_version is None:
            return remote_version

        # 简单策略：基于时间戳合并
        local_time = local_version.get("updated_at", "")
        remote_time = remote_version.get("updated_at", "")

        if remote_time >= local_time:
            return remote_version

        # 尝试合并 blocks
        if "blocks" in local_version and "blocks" in remote_version:
            merged_blocks = ConflictResolver._merge_blocks(
                local_version["blocks"],
                remote_version["blocks"],
                base_version.get("blocks", [])
            )
            result = remote_version.copy()
            result["blocks"] = merged_blocks
            return result

        return remote_version

    @staticmethod
    def _merge_blocks(local: List, remote: List, base: List) -> List:
        """合并 blocks（简化版本）"""
        # 实际实现应该使用 OT 或 CRDT
        # 这里使用简单的 last-write-wins
        return remote

    @staticmethod
    def create_patch_proposal(
        original: Dict,
        proposed: Dict,
    ) -> Dict:
        """创建修改建议（用于 Agent 修改）"""
        patches = []

        for key in proposed:
            if key not in original:
                patches.append({
                    "type": "add",
                    "key": key,
                    "value": proposed[key],
                })
            elif original[key] != proposed[key]:
                patches.append({
                    "type": "update",
                    "key": key,
                    "old_value": original[key],
                    "new_value": proposed[key],
                })

        return {
            "proposed_by": "agent",
            "patches": patches,
            "timestamp": datetime.utcnow().isoformat(),
        }
