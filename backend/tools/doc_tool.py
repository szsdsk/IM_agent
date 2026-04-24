from typing import Dict, Any, Optional
import time
import json

from backend.tools.base import BaseTool
from backend.config import settings


class DocTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("DocTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)

    async def execute(self, action: str, task_id: str = None, content: str = None,
                      title: str = None, doc_id: str = None, **kwargs) -> Dict[str, Any]:
        self._log("info", f"Doc action: {action}", {"task_id": task_id, "doc_id": doc_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_execute(action, task_id, content, title, doc_id)
        else:
            return await self._real_execute(action, task_id, content, title, doc_id)

    async def _mock_execute(self, action: str, task_id: str, content: str,
                            title: str, doc_id: str) -> Dict[str, Any]:
        await self._simulate_delay(0.3)
        self._log("info", f"Mock Doc action executed: {action}")

        mock_responses = {
            "create_doc": {
                "success": True,
                "doc_id": f"doc_{int(time.time() * 1000)}",
                "title": title or "Untitled Document",
                "content": content or "",
                "created_at": time.time()
            },
            "update_doc": {
                "success": True,
                "doc_id": doc_id,
                "updated": True,
                "version": 2
            },
            "get_doc": {
                "success": True,
                "doc_id": doc_id,
                "title": title or "Document",
                "content": content or "Sample content...",
                "version": 1
            }
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_execute(self, action: str, task_id: str, content: str,
                             title: str, doc_id: str) -> Dict[str, Any]:
        try:
            if action == "create_doc":
                return await self._create_document(task_id, title, content)
            elif action == "update_doc":
                return await self._update_document(doc_id, content)
            elif action == "get_doc":
                return await self._get_document(doc_id)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            self._log("error", f"Doc action failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _create_document(self, task_id: str, title: str, content: str) -> Dict[str, Any]:
        self._log("info", f"Creating document for task {task_id}")
        return {
            "success": True,
            "doc_id": f"doc_{int(time.time() * 1000)}",
            "title": title,
            "content": content
        }

    async def _update_document(self, doc_id: str, content: str) -> Dict[str, Any]:
        self._log("info", f"Updating document {doc_id}")
        return {"success": True, "doc_id": doc_id, "updated": True}

    async def _get_document(self, doc_id: str) -> Dict[str, Any]:
        self._log("info", f"Getting document {doc_id}")
        return {"success": True, "doc_id": doc_id, "content": ""}

    async def _simulate_delay(self, seconds: float):
        import asyncio
        await asyncio.sleep(seconds)
