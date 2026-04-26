import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class LarkBotService:
    """Feishu/Lark bot client based on tenant access token."""

    def __init__(self):
        self.app_id = settings.LARK_APP_ID
        self.app_secret = settings.LARK_APP_SECRET
        self.verification_token = settings.LARK_VERIFICATION_TOKEN
        self.base_url = "https://open.feishu.cn/open-apis"
        self._tenant_access_token: Optional[str] = None
        self._token_expires_at = 0.0
        self._processed_message_ids: Set[str] = set()
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def is_configured(self) -> bool:
        return bool(settings.LARK_BOT_ENABLED and self.app_id and self.app_secret)

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_tenant_access_token(self) -> Optional[str]:
        if self._tenant_access_token and time.time() < self._token_expires_at:
            return self._tenant_access_token

        if not self.app_id or not self.app_secret:
            logger.warning("Lark bot is not configured")
            return None

        response = await self.client.post(
            "/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            logger.error("Failed to get Lark tenant token: %s", data)
            return None

        self._tenant_access_token = data.get("tenant_access_token")
        self._token_expires_at = time.time() + max(int(data.get("expire", 7200)) - 300, 60)
        return self._tenant_access_token

    async def send_text(self, chat_id: str, text: str) -> Dict[str, Any]:
        if not self.is_configured:
            return {"success": False, "provider": "lark_bot", "error": "Lark bot is not configured."}
        if not chat_id:
            return {"success": False, "provider": "lark_bot", "error": "Missing chat_id."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "provider": "lark_bot", "error": "Failed to get tenant access token."}

        response = await self.client.post(
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": data.get("code") == 0,
            "provider": "lark_bot",
            "message_id": (data.get("data") or {}).get("message_id"),
            "error": None if data.get("code") == 0 else data.get("msg"),
            "raw": data,
        }

    async def upload_file(self, file_path: str, file_name: Optional[str] = None) -> Dict[str, Any]:
        if not self.is_configured:
            return {"success": False, "provider": "lark_bot", "error": "Lark bot is not configured."}

        path = self._resolve_local_file(file_path)
        if not path:
            return {"success": False, "provider": "lark_bot", "error": "Missing file_path."}
        if not path.is_file():
            return {"success": False, "provider": "lark_bot", "error": f"File not found: {path}"}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "provider": "lark_bot", "error": "Failed to get tenant access token."}

        upload_name = file_name or path.name
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as file_obj:
            response = await self.client.post(
                "/im/v1/files",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "file_type": self._file_type(path),
                    "file_name": upload_name,
                },
                files={"file": (upload_name, file_obj, mime_type)},
            )

        response.raise_for_status()
        data = response.json()
        file_key = (data.get("data") or {}).get("file_key")
        return {
            "success": data.get("code") == 0 and bool(file_key),
            "provider": "lark_bot",
            "file_key": file_key,
            "file_name": upload_name,
            "error": None if data.get("code") == 0 else data.get("msg"),
            "raw": data,
        }

    async def send_file(self, chat_id: str, file_key: str) -> Dict[str, Any]:
        if not self.is_configured:
            return {"success": False, "provider": "lark_bot", "error": "Lark bot is not configured."}
        if not chat_id:
            return {"success": False, "provider": "lark_bot", "error": "Missing chat_id."}
        if not file_key:
            return {"success": False, "provider": "lark_bot", "error": "Missing file_key."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "provider": "lark_bot", "error": "Failed to get tenant access token."}

        response = await self.client.post(
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
            },
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": data.get("code") == 0,
            "provider": "lark_bot",
            "message_id": (data.get("data") or {}).get("message_id"),
            "error": None if data.get("code") == 0 else data.get("msg"),
            "raw": data,
        }

    async def send_local_file(self, chat_id: str, file_path: str, file_name: Optional[str] = None) -> Dict[str, Any]:
        upload_result = await self.upload_file(file_path, file_name=file_name)
        if not upload_result.get("success"):
            return upload_result

        send_result = await self.send_file(chat_id, upload_result["file_key"])
        return {
            **send_result,
            "file_key": upload_result.get("file_key"),
            "file_name": upload_result.get("file_name"),
            "upload": upload_result,
        }

    def verify_event(self, payload: Dict[str, Any]) -> bool:
        if not self.verification_token:
            return True

        token = payload.get("token")
        header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
        return token == self.verification_token or header.get("token") == self.verification_token

    def is_url_verification(self, payload: Dict[str, Any]) -> bool:
        return payload.get("type") == "url_verification" and bool(payload.get("challenge"))

    def extract_message_event(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event = payload.get("event") if isinstance(payload.get("event"), dict) else None
        if not event:
            return None

        message = event.get("message") if isinstance(event.get("message"), dict) else {}
        sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
        message_id = message.get("message_id")
        if not message_id:
            return None
        if message_id in self._processed_message_ids:
            return None

        text = self._extract_text(message)
        if not text:
            return None

        if settings.LARK_BOT_REQUIRE_MENTION and message.get("chat_type") == "group":
            mentions = message.get("mentions") or []
            if not mentions:
                return None
            text = self._strip_mentions(text, mentions)

        self._processed_message_ids.add(message_id)
        if len(self._processed_message_ids) > 1000:
            self._processed_message_ids = set(list(self._processed_message_ids)[-500:])

        return {
            "message_id": message_id,
            "chat_id": message.get("chat_id"),
            "chat_type": message.get("chat_type"),
            "text": text.strip(),
            "user_id": self._sender_id(sender),
        }

    def _extract_text(self, message: Dict[str, Any]) -> str:
        if message.get("message_type") != "text":
            return ""

        content = message.get("content") or ""
        try:
            parsed = json.loads(content)
            return str(parsed.get("text") or "")
        except (json.JSONDecodeError, TypeError):
            return str(content)

    def _strip_mentions(self, text: str, mentions: Any) -> str:
        cleaned = text
        for mention in mentions if isinstance(mentions, list) else []:
            name = mention.get("name") if isinstance(mention, dict) else None
            key = mention.get("key") if isinstance(mention, dict) else None
            if name:
                cleaned = cleaned.replace(f"@{name}", "")
            if key:
                cleaned = cleaned.replace(str(key), "")
        return re.sub(r"@\S+", "", cleaned).strip()

    def _sender_id(self, sender: Dict[str, Any]) -> Optional[str]:
        sender_id = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
        return sender_id.get("open_id") or sender_id.get("user_id") or sender_id.get("union_id")

    def _resolve_local_file(self, value: Optional[str]) -> Optional[Path]:
        if not value:
            return None

        if value.startswith("/api/files/slides/"):
            filename = Path(value).name
            return Path(__file__).resolve().parents[1] / "data" / "slides" / filename

        path = Path(value)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    def _file_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".ppt", ".pptx"}:
            return "ppt"
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".doc", ".docx"}:
            return "doc"
        if suffix in {".xls", ".xlsx"}:
            return "xls"
        if suffix in {".mp4", ".mov"}:
            return "mp4"
        if suffix in {".opus", ".ogg", ".mp3", ".wav"}:
            return "opus"
        return "stream"


lark_bot_service = LarkBotService()
