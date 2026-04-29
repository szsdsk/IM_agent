import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.tools.base import BaseTool


class DocToolInput(BaseModel):
    action: str = Field(description="Document action, such as create_doc, update_doc, or get_doc.")
    task_id: Optional[str] = None
    content: Optional[str] = None
    title: Optional[str] = None
    doc_id: Optional[str] = None


class DocTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("DocTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)

    def _build_langchain_tool(self):
        from langchain_core.tools import StructuredTool

        return StructuredTool.from_function(
            name="doc_tool",
            description="Create, update, or read an Agent-Pilot document artifact.",
            coroutine=self._run,
            args_schema=DocToolInput,
        )

    async def _run(
        self,
        action: str,
        task_id: str = None,
        content: str = None,
        title: str = None,
        doc_id: str = None,
    ) -> Dict[str, Any]:
        self._log("info", f"Doc action: {action}", {"task_id": task_id, "doc_id": doc_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_run(action, task_id, content, title, doc_id)
        return await self._real_run(action, task_id, content, title, doc_id)

    async def _mock_run(self, action: str, task_id: str, content: str, title: str, doc_id: str) -> Dict[str, Any]:
        await self._simulate_delay(0.3)
        self._log("info", f"Mock Doc action executed: {action}")

        mock_responses = {
            "create_doc": {
                "success": True,
                "doc_id": f"doc_{int(time.time() * 1000)}",
                "title": title or "Untitled Document",
                "content": content or "",
                "created_at": time.time(),
            },
            "update_doc": {
                "success": True,
                "doc_id": doc_id,
                "updated": True,
                "version": 2,
            },
            "get_doc": {
                "success": True,
                "doc_id": doc_id,
                "title": title or "Document",
                "content": content or "Sample content...",
                "version": 1,
            },
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_run(self, action: str, task_id: str, content: str, title: str, doc_id: str) -> Dict[str, Any]:
        try:
            if action == "create_doc":
                return await self._create_document(task_id, title, content)
            if action == "update_doc":
                return await self._update_document(doc_id, content)
            if action == "get_doc":
                return await self._get_document(doc_id)
            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            self._log("error", f"Doc action failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _create_document(self, task_id: str, title: str, content: str) -> Dict[str, Any]:
        self._log("info", f"Creating document for task {task_id}")

        # Try Feishu Docx API first
        from backend.services.lark_bot_service import lark_bot_service
        from backend.database.connection import async_session_maker
        from backend.database.models import Document

        doc_id = f"doc_{int(time.time() * 1000)}"
        doc_url = None
        provider = "local"

        if lark_bot_service.is_configured:
            try:
                doc_result = await lark_bot_service.create_doc(title=title or "未命名文档")
                if doc_result.get("success") and doc_result.get("document_id"):
                    doc_id = doc_result["document_id"]
                    doc_url = doc_result.get("url", "")
                    provider = "lark_docx"

                    # Write content
                    if content:
                        write_result = await lark_bot_service.write_markdown_to_doc(
                            doc_id, content
                        )
                        self._log("info", f"Wrote {write_result.get('blocks_written', 0)} blocks to Feishu doc")
            except Exception as exc:
                self._log("warning", f"Feishu Docx API failed, falling back: {str(exc)}")

        # Persist to local DB for all providers (including Feishu docs)
        try:
            async with async_session_maker() as db:
                doc_record = Document(
                    id=doc_id,
                    task_id=task_id,
                    content=content,
                    lark_doc_id=doc_id if provider == "lark_docx" else None,
                    lark_doc_url=doc_url,
                )
                db.add(doc_record)
                await db.commit()
                self._log("info", f"Saved Document record: {doc_id}, lark_doc_id={doc_id if provider == 'lark_docx' else None}")
        except Exception as db_exc:
            self._log("warning", f"Failed to persist Document record: {db_exc}")

        return {
            "success": True,
            "doc_id": doc_id,
            "title": title,
            "content": content,
            "doc_url": doc_url,
            "provider": provider,
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
