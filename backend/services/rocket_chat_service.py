"""
Rocket.Chat Service - IM 集成
支持消息监听、@Pilot 指令处理、消息卡片发送
"""
import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from enum import Enum

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class MessageType(Enum):
    TEXT = "text"
    CARD = "card"
    BUTTON = "button"
    COMMENT = "comment"


class RocketChatService:
    """Rocket.Chat API 客户端"""

    def __init__(
        self,
        url: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.url = (url or settings.ROCKET_CHAT_URL or "").rstrip("/")
        self.user = user or settings.ROCKET_CHAT_USER
        self.password = password or settings.ROCKET_CHAT_PASSWORD
        self._auth_token: Optional[str] = None
        self._user_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._message_handlers: List[Callable] = []
        self._running = False

        if not self.url or not self.user or not self.password:
            logger.warning("Rocket.Chat not configured, using mock mode")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.user and self.password)

    async def login(self) -> Dict[str, Any]:
        """登录获取认证 Token"""
        if not self.is_configured:
            return {"success": False, "error": "Not configured"}

        try:
            response = await self.client.post(
                "/api/v1/login",
                json={"user": self.user, "password": self.password},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "success":
                self._auth_token = data["data"]["authToken"]
                self._user_id = data["data"]["userId"]
                self._client.headers["X-Auth-Token"] = self._auth_token
                self._client.headers["X-User-Id"] = self._user_id
                logger.info(f"Logged in as {self.user}")
                return {"success": True, "userId": self._user_id}
            else:
                return {"success": False, "error": "Login failed"}

        except Exception as e:
            logger.error(f"Login error: {e}")
            return {"success": False, "error": str(e)}

    async def logout(self):
        """登出"""
        if self._auth_token:
            try:
                await self.client.post("/api/v1/logout")
            except:
                pass
            self._auth_token = None
            self._user_id = None

    async def get_messages(
        self,
        room_id: str,
        limit: int = 30,
        oldest: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取房间消息"""
        if not self.is_configured:
            return self._mock_get_messages(room_id, limit)

        try:
            params = {"roomId": room_id, "limit": limit}
            if oldest:
                params["oldest"] = oldest

            response = await self.client.get("/api/v1/channels.messages", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                return data.get("messages", [])
            return []
        except Exception as e:
            logger.error(f"Get messages error: {e}")
            return []

    async def send_message(
        self,
        room_id: str,
        text: str,
        msg_type: MessageType = MessageType.TEXT,
    ) -> Dict[str, Any]:
        """发送消息"""
        if not self.is_configured:
            return self._mock_send_message(room_id, text)

        try:
            payload = {
                "roomId": room_id,
                "text": text,
            }

            # 如果是卡片消息，使用 attachment
            if msg_type == MessageType.CARD:
                payload["attachments"] = [{
                    "color": "#00ff00",
                    "text": text,
                    "title": "Agent-Pilot",
                }]

            response = await self.client.post("/api/v1/chat.sendMessage", json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                return {"success": True, "message": data.get("message", {})}
            return {"success": False, "error": "Send failed"}

        except Exception as e:
            logger.error(f"Send message error: {e}")
            return {"success": False, "error": str(e)}

    async def send_delivery_card(
        self,
        room_id: str,
        delivery: Dict[str, Any],
    ) -> Dict[str, Any]:
        """发送交付卡片"""
        card_text = self._build_delivery_card(delivery)
        return await self.send_message(room_id, card_text, MessageType.CARD)

    def _build_delivery_card(self, delivery: Dict[str, Any]) -> str:
        """构建交付卡片文本"""
        lines = ["🎉 **Agent-Pilot 任务完成！**\n"]

        if delivery.get("document"):
            doc = delivery["document"]
            lines.append(f"📄 **文档**: {doc.get('title', '未命名')}")
            if doc.get("preview"):
                lines.append(f"```\n{doc['preview'][:200]}...\n```")

        if delivery.get("slides"):
            slides = delivery["slides"]
            lines.append(f"📊 **演示稿**: {slides.get('title', '未命名')}")
            lines.append(f"   页数: {slides.get('slides_count', 0)} 页")

        if delivery.get("canvas"):
            lines.append("🎨 **架构图**: 已生成")

        lines.append("\n💡 输入\"排练\"获取演讲提示")
        return "\n".join(lines)

    async def send_progress_update(
        self,
        room_id: str,
        task_id: str,
        step: str,
        progress: float,
        message: str,
    ) -> Dict[str, Any]:
        """发送进度更新"""
        progress_bar = "█" * int(progress * 10) + "░" * (10 - int(progress * 10))
        text = (
            f"⏳ **任务进行中**\n"
            f"`{progress_bar}` {int(progress * 100)}%\n"
            f"📍 {step}\n"
            f"{message}"
        )
        return await self.send_message(room_id, text)

    async def send_plan_card(
        self,
        room_id: str,
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """发送计划卡片"""
        lines = ["📋 **执行计划**\n"]

        goal = plan.get("goal", "未知目标")
        lines.append(f"🎯 **{goal}**\n")

        steps = plan.get("steps", [])
        for i, step in enumerate(steps):
            module = step.get("module", "UNKNOWN")
            action = step.get("action", "unknown")
            needs_approval = step.get("needs_approval", False)
            icon = "✅" if needs_approval else "➡️"
            approval = " [待确认]" if needs_approval else ""
            lines.append(f"{i+1}. {icon} **{module}** / {action}{approval}")

        text = "\n".join(lines)
        return await self.send_message(room_id, text)

    async def subscribe_to_messages(
        self,
        room_id: str,
        callback: Callable[[Dict], Any],
    ):
        """订阅房间消息（轮询方式）"""
        self._message_handlers.append(callback)
        last_message_id = None

        while self._running:
            try:
                messages = await self.get_messages(room_id, limit=20)
                for msg in messages:
                    msg_id = msg.get("_id")
                    if msg_id != last_message_id and msg.get("u", {}).get("username") != self.user:
                        # 过滤 @Pilot 消息
                        if "@Pilot" in msg.get("msg", "") or "/pilot" in msg.get("msg", ""):
                            await callback({
                                "room_id": room_id,
                                "message_id": msg_id,
                                "user": msg.get("u", {}).get("username"),
                                "text": msg.get("msg", ""),
                                "timestamp": msg.get("ts", {}).get("$date", ""),
                            })
                        last_message_id = msg_id

                await asyncio.sleep(3)  # 轮询间隔

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Subscribe error: {e}")
                await asyncio.sleep(5)

    async def start_listener(self, room_id: str):
        """启动消息监听"""
        self._running = True
        self._listener_task = asyncio.create_task(
            self.subscribe_to_messages(room_id, self._handle_pilot_message)
        )

    async def stop_listener(self):
        """停止消息监听"""
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

    async def _handle_pilot_message(self, msg: Dict[str, Any]):
        """处理 @Pilot 消息"""
        text = msg["text"].replace("@Pilot", "").strip()
        text = text.replace("/pilot", "").strip()

        logger.info(f"Pilot message from {msg['user']}: {text[:100]}")

        # 通知所有处理器
        for handler in self._message_handlers:
            try:
                await handler(msg)
            except Exception as e:
                logger.error(f"Handler error: {e}")

    # ============ Mock Methods ============

    def _mock_get_messages(self, room_id: str, limit: int) -> List[Dict]:
        return [
            {
                "_id": f"mock_{i}",
                "msg": f"Mock message {i}",
                "u": {"username": f"user{i}"},
                "ts": {"$date": datetime.utcnow().isoformat()},
            }
            for i in range(limit)
        ]

    def _mock_send_message(self, room_id: str, text: str) -> Dict[str, Any]:
        logger.info(f"[Mock] Sending to {room_id}: {text[:100]}")
        return {"success": True, "message": {"_id": f"mock_{datetime.utcnow().timestamp()}"}}

    async def close(self):
        await self.stop_listener()
        if self._client:
            await self._client.aclose()
            self._client = None


# 全局实例
rocket_chat_service = RocketChatService()


# ============ IM Tool Extension ============

async def send_to_im(
    user_id: str,
    content: str,
    room_id: Optional[str] = None,
    msg_type: str = "text",
) -> Dict[str, Any]:
    """发送消息到 IM"""
    if settings.MOCK_MODE or not rocket_chat_service.is_configured:
        return await rocket_chat_service._mock_send_message(room_id or user_id, content)

    return await rocket_chat_service.send_message(
        room_id=room_id or user_id,
        text=content,
        msg_type=MessageType(msg_type) if msg_type in [e.value for e in MessageType] else MessageType.TEXT,
    )


async def fetch_im_context(
    room_id: str,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """获取 IM 上下文"""
    if settings.MOCK_MODE or not rocket_chat_service.is_configured:
        return [{"role": "user", "content": f"Mock context from {room_id}"}]

    messages = await rocket_chat_service.get_messages(room_id, limit)
    return [
        {
            "role": msg.get("u", {}).get("username", "unknown"),
            "content": msg.get("msg", ""),
            "timestamp": msg.get("ts", {}).get("$date", ""),
        }
        for msg in messages
        if msg.get("msg")
    ]


async def post_delivery_to_im(
    room_id: str,
    delivery: Dict[str, Any],
) -> Dict[str, Any]:
    """发送交付卡片到 IM"""
    if settings.MOCK_MODE or not rocket_chat_service.is_configured:
        return await rocket_chat_service._mock_send_message(room_id, "🎉 任务完成！")

    return await rocket_chat_service.send_delivery_card(room_id, delivery)
