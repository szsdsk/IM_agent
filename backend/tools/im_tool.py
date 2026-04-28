import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.services.lark_bot_service import lark_bot_service
from backend.services.rocket_chat_service import fetch_im_context, send_to_im
from backend.tools.base import BaseTool


class IMToolInput(BaseModel):
    action: str = Field(description="IM action, such as send_message, get_messages, or send_notification.")
    user_id: Optional[str] = None
    content: Optional[str] = None
    room_id: Optional[str] = None
    limit: Optional[int] = 30


class IMTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("IMTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)

    def _build_langchain_tool(self):
        from langchain_core.tools import StructuredTool

        return StructuredTool.from_function(
            name="im_tool",
            description="Send or fetch IM messages for Agent-Pilot delivery and context.",
            coroutine=self._run,
            args_schema=IMToolInput,
        )

    async def _run(
        self,
        action: str,
        user_id: str = None,
        content: str = None,
        room_id: str = None,
        limit: int = 30,
    ) -> Dict[str, Any]:
        self._log("info", f"IM action: {action}", {"user_id": user_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_run(action, user_id, content)
        return await self._real_run(action, user_id, content, room_id=room_id, limit=limit)

    async def _mock_run(self, action: str, user_id: str, content: str) -> Dict[str, Any]:
        await self._simulate_delay(0.1)
        self._log("info", f"Mock IM action executed: {action}")

        mock_responses = {
            "send_message": {
                "success": True,
                "message_id": f"msg_{int(time.time() * 1000)}",
                "content": content,
                "sent_at": time.time(),
            },
            "get_messages": {
                "success": True,
                "messages": [
                    {"message_id": "msg_001", "content": "Hello from IM", "timestamp": time.time()}
                ],
            },
            "send_notification": {
                "success": True,
                "notification_id": f"notif_{int(time.time() * 1000)}",
            },
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_run(
        self,
        action: str,
        user_id: str,
        content: str,
        room_id: str = None,
        limit: int = 30,
    ) -> Dict[str, Any]:
        try:
            if action == "send_message":
                return await self._send_to_im(user_id, content, room_id=room_id)
            if action == "get_messages":
                return await self._fetch_messages(room_id or user_id, limit=limit)
            if action == "send_notification":
                return await self._send_notification(user_id, content, room_id=room_id)
            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            self._log("error", f"IM action failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _send_to_im(self, user_id: str, content: str, room_id: str = None) -> Dict[str, Any]:
        self._log("info", f"Sending message to user {user_id}: {content}")
        if settings.IM_PROVIDER == "lark":
            result = await lark_bot_service.send_text(room_id or user_id, content or "")
            return {
                "success": result.get("success", False),
                "message_id": result.get("message_id", f"msg_{int(time.time() * 1000)}"),
                "provider": "lark",
                "error": result.get("error"),
            }

        result = await send_to_im(user_id=user_id or "", content=content or "", room_id=room_id)
        return {
            "success": result.get("success", False),
            "message_id": result.get("message", {}).get("_id", f"msg_{int(time.time() * 1000)}"),
            "provider": "rocket_chat",
        }

    async def _fetch_messages(self, room_id: str, limit: int = 30) -> Dict[str, Any]:
        self._log("info", f"Fetching messages for room {room_id}")
        if settings.IM_PROVIDER == "lark":
            return {
                "success": True,
                "messages": [],
                "provider": "lark",
                "message": "Lark bot receives messages by event callback; history fetch is not implemented.",
            }

        messages = await fetch_im_context(room_id, limit=limit)
        return {"success": True, "messages": messages, "provider": "rocket_chat"}

    async def _send_notification(self, user_id: str, content: str, room_id: str = None) -> Dict[str, Any]:
        self._log("info", f"Sending notification to user {user_id}")
        return await self._send_to_im(user_id, content, room_id=room_id)

    async def _simulate_delay(self, seconds: float):
        import asyncio

        await asyncio.sleep(seconds)
