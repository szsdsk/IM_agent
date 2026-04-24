from typing import Dict, Any
import time
import json

from backend.tools.base import BaseTool
from backend.config import settings


class IMTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("IMTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)

    async def execute(self, action: str, user_id: str = None, content: str = None, **kwargs) -> Dict[str, Any]:
        self._log("info", f"IM action: {action}", {"user_id": user_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_execute(action, user_id, content)
        else:
            return await self._real_execute(action, user_id, content)

    async def _mock_execute(self, action: str, user_id: str, content: str) -> Dict[str, Any]:
        await self._simulate_delay(0.1)
        self._log("info", f"Mock IM action executed: {action}")

        mock_responses = {
            "send_message": {
                "success": True,
                "message_id": f"msg_{int(time.time() * 1000)}",
                "content": content,
                "sent_at": time.time()
            },
            "get_messages": {
                "success": True,
                "messages": [
                    {"message_id": "msg_001", "content": "Hello from IM", "timestamp": time.time()}
                ]
            },
            "send_notification": {
                "success": True,
                "notification_id": f"notif_{int(time.time() * 1000)}"
            }
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_execute(self, action: str, user_id: str, content: str) -> Dict[str, Any]:
        try:
            if action == "send_message":
                return await self._send_to_im(user_id, content)
            elif action == "get_messages":
                return await self._fetch_messages(user_id)
            elif action == "send_notification":
                return await self._send_notification(user_id, content)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            self._log("error", f"IM action failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _send_to_im(self, user_id: str, content: str) -> Dict[str, Any]:
        self._log("info", f"Sending message to user {user_id}: {content}")
        return {"success": True, "message_id": f"msg_{int(time.time() * 1000)}"}

    async def _fetch_messages(self, user_id: str) -> Dict[str, Any]:
        self._log("info", f"Fetching messages for user {user_id}")
        return {"success": True, "messages": []}

    async def _send_notification(self, user_id: str, content: str) -> Dict[str, Any]:
        self._log("info", f"Sending notification to user {user_id}")
        return {"success": True}

    async def _simulate_delay(self, seconds: float):
        import asyncio
        await asyncio.sleep(seconds)
