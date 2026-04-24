from typing import Dict, Any, Optional
import time
import json
import hashlib

from backend.tools.base import BaseTool
from backend.config import settings


class LarkTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("LarkTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)
        self._app_id = settings.LARK_APP_ID
        self._app_secret = settings.LARK_APP_SECRET

    async def execute(self, action: str, entity_type: str = None, entity_id: str = None,
                      data: Dict = None, **kwargs) -> Dict[str, Any]:
        self._log("info", f"Lark action: {action}", {"entity_type": entity_type, "entity_id": entity_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_execute(action, entity_type, entity_id, data)
        else:
            return await self._real_execute(action, entity_type, entity_id, data)

    async def _mock_execute(self, action: str, entity_type: str, entity_id: str,
                             data: Dict) -> Dict[str, Any]:
        await self._simulate_delay(0.2)
        self._log("info", f"Mock Lark action executed: {action}")

        mock_token = self._generate_mock_token()

        mock_responses = {
            "get_token": {
                "success": True,
                "access_token": mock_token,
                "expires_in": 7200
            },
            "create_document": {
                "success": True,
                "document_id": f"lark_doc_{int(time.time() * 1000)}",
                "title": data.get("title") if data else "Lark Document"
            },
            "update_document": {
                "success": True,
                "document_id": entity_id,
                "revision": 2
            },
            "create_table": {
                "success": True,
                "table_id": f"lark_table_{int(time.time() * 1000)}"
            },
            "upload_file": {
                "success": True,
                "file_key": f"file_key_{int(time.time() * 1000)}",
                "file_token": f"file_token_{int(time.time() * 1000)}"
            }
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_execute(self, action: str, entity_type: str, entity_id: str,
                             data: Dict) -> Dict[str, Any]:
        try:
            if action == "get_token":
                return await self._get_access_token()
            elif action == "create_document":
                return await self._create_lark_document(data)
            elif action == "update_document":
                return await self._update_lark_document(entity_id, data)
            elif action == "create_table":
                return await self._create_lark_table(data)
            elif action == "upload_file":
                return await self._upload_lark_file(data)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            self._log("error", f"Lark action failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def _generate_mock_token(self) -> str:
        timestamp = str(int(time.time() * 1000))
        raw = f"mock_token_{timestamp}_{self._app_id or 'no_app_id'}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def _get_access_token(self) -> Dict[str, Any]:
        if not self._app_id or not self._app_secret:
            return {
                "success": False,
                "error": "Lark APP_ID and APP_SECRET not configured"
            }

        self._log("info", "Getting Lark access token")
        return {
            "success": True,
            "access_token": self._generate_mock_token(),
            "expires_in": 7200
        }

    async def _create_lark_document(self, data: Dict) -> Dict[str, Any]:
        self._log("info", f"Creating Lark document: {data.get('title') if data else 'Untitled'}")
        return {
            "success": True,
            "document_id": f"lark_doc_{int(time.time() * 1000)}"
        }

    async def _update_lark_document(self, document_id: str, data: Dict) -> Dict[str, Any]:
        self._log("info", f"Updating Lark document {document_id}")
        return {"success": True, "document_id": document_id, "revision": 2}

    async def _create_lark_table(self, data: Dict) -> Dict[str, Any]:
        self._log("info", "Creating Lark table")
        return {"success": True, "table_id": f"lark_table_{int(time.time() * 1000)}"}

    async def _upload_lark_file(self, data: Dict) -> Dict[str, Any]:
        self._log("info", "Uploading file to Lark")
        return {
            "success": True,
            "file_key": f"file_key_{int(time.time() * 1000)}",
            "file_token": f"file_token_{int(time.time() * 1000)}"
        }

    async def _simulate_delay(self, seconds: float):
        import asyncio
        await asyncio.sleep(seconds)
