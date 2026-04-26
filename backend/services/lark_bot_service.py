import json
import logging
import mimetypes
import re
import time
import uuid
from base64 import b64encode
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class LarkBotService:
    """基于 tenant access token 的飞书 OpenAPI 客户端。"""

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

    async def get_status(self, check_auth: bool = False) -> Dict[str, Any]:
        """返回飞书应用配置和 tenant token 状态，避免健康检查再依赖 CLI。"""
        configured = bool(self.app_id and self.app_secret)
        status = {
            "success": bool(settings.LARK_BOT_ENABLED and configured),
            "provider": "lark_openapi",
            "enabled": settings.LARK_BOT_ENABLED,
            "configured": configured,
            "authenticated": False,
            "app_id_configured": bool(self.app_id),
            "app_secret_configured": bool(self.app_secret),
            "default_chat_id_configured": bool(settings.LARK_DEFAULT_CHAT_ID),
        }

        if not settings.LARK_BOT_ENABLED:
            status["message"] = "飞书 OpenAPI 同步未开启。"
            return status
        if not configured:
            status["error"] = "LARK_APP_ID or LARK_APP_SECRET is not configured."
            return status
        if not check_auth:
            status["message"] = "飞书 OpenAPI 已配置，未检查 token。"
            return status

        try:
            token = await self.get_tenant_access_token()
        except Exception as exc:
            logger.exception("Failed to check Lark OpenAPI status")
            status["success"] = False
            status["error"] = self._redact(str(exc))
            return status

        status["authenticated"] = bool(token)
        status["success"] = bool(token)
        if token:
            status["message"] = "飞书 OpenAPI 已配置，tenant access token 可用。"
        else:
            status["error"] = "Failed to get tenant access token."
        return status

    async def get_tenant_access_token(self) -> Optional[str]:
        if self._tenant_access_token and time.time() < self._token_expires_at:
            return self._tenant_access_token

        if not self.app_id or not self.app_secret:
            logger.warning("Lark OpenAPI is not configured")
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
            return {"success": False, "provider": "lark_openapi", "error": "Lark OpenAPI is not configured."}
        if not chat_id:
            return {"success": False, "provider": "lark_openapi", "error": "Missing chat_id."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "provider": "lark_openapi", "error": "Failed to get tenant access token."}

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
            "provider": "lark_openapi",
            "message_id": (data.get("data") or {}).get("message_id"),
            "error": None if data.get("code") == 0 else data.get("msg"),
            "raw": data,
        }

    async def upload_file(self, file_path: str, file_name: Optional[str] = None) -> Dict[str, Any]:
        """上传 IM 临时文件，返回的 file_key 只能用于发送聊天文件消息。"""
        if not self.is_configured:
            return {"success": False, "provider": "lark_openapi", "error": "Lark OpenAPI is not configured."}

        path = self._resolve_local_file(file_path)
        if not path:
            return {"success": False, "provider": "lark_openapi", "error": "Missing file_path."}
        if not path.is_file():
            return {"success": False, "provider": "lark_openapi", "error": f"File not found: {path}"}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "provider": "lark_openapi", "error": "Failed to get tenant access token."}

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
            "provider": "lark_openapi",
            "file_key": file_key,
            "file_name": upload_name,
            "error": None if data.get("code") == 0 else data.get("msg"),
            "raw": data,
        }

    async def send_file(self, chat_id: str, file_key: str) -> Dict[str, Any]:
        if not self.is_configured:
            return {"success": False, "provider": "lark_openapi", "error": "Lark OpenAPI is not configured."}
        if not chat_id:
            return {"success": False, "provider": "lark_openapi", "error": "Missing chat_id."}
        if not file_key:
            return {"success": False, "provider": "lark_openapi", "error": "Missing file_key."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "provider": "lark_openapi", "error": "Failed to get tenant access token."}

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
            "provider": "lark_openapi",
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

    async def download_message_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str = "file",
    ) -> Dict[str, Any]:
        """Download a Feishu message resource, such as a voice attachment."""
        if not self.is_configured:
            return {"success": False, "error": "Lark OpenAPI is not configured."}
        if not message_id or not file_key:
            return {"success": False, "error": "Missing message_id or file_key."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "error": "Failed to get tenant access token."}

        response = await self.client.get(
            f"/im/v1/messages/{message_id}/resources/{file_key}",
            params={"type": resource_type},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return {
            "success": True,
            "content": response.content,
            "content_type": response.headers.get("content-type", "application/octet-stream"),
        }

    async def recognize_speech_file(
        self,
        audio_bytes: bytes,
        file_id: Optional[str] = None,
        audio_format: Optional[str] = None,
        engine_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Recognize a short audio file with Feishu speech_to_text ASR."""
        if not self.is_configured:
            return {"success": False, "error": "Lark OpenAPI is not configured."}
        if not audio_bytes:
            return {"success": False, "error": "Audio file is empty."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "error": "Failed to get tenant access token."}

        safe_file_id = re.sub(r"[^0-9A-Za-z_]", "_", (file_id or "").strip())
        if len(safe_file_id) != 16:
            safe_file_id = uuid.uuid4().hex[:16]

        payload = {
            "speech": {
                "speech": b64encode(audio_bytes).decode("ascii"),
            },
            "config": {
                "file_id": safe_file_id,
                "format": audio_format or settings.FEISHU_ASR_FORMAT,
                "engine_type": engine_type or settings.FEISHU_ASR_ENGINE_TYPE,
            },
        }

        try:
            response = await self.client.post(
                "/speech_to_text/v1/speech/file_recognize",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = ""
            if exc.response is not None:
                detail = exc.response.text[:1000]
            error_msg = (
                f"HTTP {exc.response.status_code if exc.response is not None else 'error'}; "
                f"format={payload['config']['format']}; engine_type={payload['config']['engine_type']}; "
                f"detail={detail or str(exc)}"
            )
            return {"success": False, "error": error_msg}
        except Exception as exc:
            return {
                "success": False,
                "error": (
                    f"Unexpected ASR error; format={payload['config']['format']}; "
                    f"engine_type={payload['config']['engine_type']}; detail={str(exc)}"
                ),
            }

        text = str(((data.get("data") or {}).get("recognition_text")) or "").strip()
        return {
            "success": data.get("code") == 0 and bool(text),
            "text": text,
            "provider": "feishu_asr",
            "model": payload["config"]["engine_type"],
            "error": None if data.get("code") == 0 else data.get("msg"),
            "raw": data,
        }

    async def send_card(self, chat_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
        """发送飞书交互卡片消息。"""
        if not self.is_configured:
            return {"success": False, "error": "Lark OpenAPI is not configured."}
        if not chat_id:
            return {"success": False, "error": "Missing chat_id."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "error": "Failed to get tenant access token."}

        response = await self.client.post(
            "/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": data.get("code") == 0,
            "provider": "lark_openapi",
            "message_id": (data.get("data") or {}).get("message_id"),
            "error": None if data.get("code") == 0 else data.get("msg"),
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
        voice_resource = self._extract_voice_resource(message)
        if not text and not voice_resource:
            return None

        if text and settings.LARK_BOT_REQUIRE_MENTION and message.get("chat_type") == "group":
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
            "voice_resource": voice_resource,
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

    def _extract_voice_resource(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if message.get("message_type") not in {"audio", "voice", "media"}:
            return None

        content = message.get("content") or ""
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

        file_key = parsed.get("file_key") or parsed.get("key") or parsed.get("fileKey")
        if not file_key:
            return None

        return {
            "file_key": file_key,
            "duration": parsed.get("duration") or parsed.get("duration_ms"),
            "message_type": message.get("message_type"),
        }

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

    def _redact(self, text: str) -> str:
        """错误日志中隐藏应用密钥和 LLM Key。"""
        redacted = text
        for secret in (settings.LARK_APP_SECRET, settings.OPENAI_API_KEY):
            if secret:
                redacted = redacted.replace(secret, "***")
        return redacted[:2000]

    # ============ Docx API ============

    async def create_doc(self, title: str = "未命名文档", folder_token: str = None) -> Dict[str, Any]:
        """创建飞书云文档，返回 document_id 和访问链接。"""
        if not self.is_configured:
            return {"success": False, "error": "Lark OpenAPI is not configured."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "error": "Failed to get tenant access token."}

        payload: Dict[str, Any] = {"title": title}
        if folder_token:
            payload["folder_token"] = folder_token

        response = await self.client.post(
            "/docx/v1/documents",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        doc = (data.get("data") or {}).get("document", {})
        return {
            "success": data.get("code") == 0,
            "document_id": doc.get("document_id"),
            "title": doc.get("title", title),
            "url": (data.get("data") or {}).get("url", ""),
            "revision_id": (data.get("data") or {}).get("revision_id"),
            "error": None if data.get("code") == 0 else data.get("msg"),
        }

    async def create_doc_block(
        self,
        document_id: str,
        block_id: str,
        blocks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """向飞书文档追加 block 内容。block_id 为页面根节点时用 document_id。"""
        if not self.is_configured:
            return {"success": False, "error": "Lark OpenAPI is not configured."}

        token = await self.get_tenant_access_token()
        if not token:
            return {"success": False, "error": "Failed to get tenant access token."}

        payload = {"children": blocks}

        response = await self.client.post(
            f"/docx/v1/documents/{document_id}/blocks/{block_id}/children",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "success": data.get("code") == 0,
            "children": (data.get("data") or {}).get("children", []),
            "error": None if data.get("code") == 0 else data.get("msg"),
        }

    async def write_markdown_to_doc(
        self,
        document_id: str,
        markdown: str,
    ) -> Dict[str, Any]:
        """将 Markdown 内容写入飞书文档。"""
        blocks = markdown_to_lark_blocks(markdown)
        if not blocks:
            return {"success": True, "document_id": document_id, "blocks_written": 0}

        result = await self.create_doc_block(document_id, document_id, blocks)
        return {
            **result,
            "document_id": document_id,
            "blocks_written": len(blocks) if result.get("success") else 0,
        }


def markdown_to_lark_blocks(markdown: str) -> List[Dict[str, Any]]:
    """将 Markdown 转换为飞书 Docx block 结构。"""
    blocks: List[Dict[str, Any]] = []

    def _text_element(content: str, link: str = None) -> Dict:
        elem: Dict[str, Any] = {"text_run": {"content": content}}
        if link:
            elem["text_run"]["link"] = {"url": link}
        return elem

    for line in markdown.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("### "):
            blocks.append({
                "block_type": 5,  # heading3
                "heading3": {"elements": [_text_element(stripped[4:])]},
            })
        elif stripped.startswith("## "):
            blocks.append({
                "block_type": 4,  # heading2
                "heading2": {"elements": [_text_element(stripped[3:])]},
            })
        elif stripped.startswith("# "):
            blocks.append({
                "block_type": 3,  # heading1
                "heading1": {"elements": [_text_element(stripped[2:])]},
            })
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({
                "block_type": 16,  # bullet
                "bullet": {"elements": [_text_element(stripped[2:])]},
            })
        elif stripped.startswith("> "):
            blocks.append({
                "block_type": 18,  # quote
                "quote": {"elements": [_text_element(stripped[2:])]},
            })
        elif stripped == "---":
            blocks.append({"block_type": 22})  # divider
        else:
            # Remove leading number prefix like "1. "
            content = stripped
            if len(content) > 2 and content[0].isdigit() and content[1] in ".)" :
                content = content[2:].strip()
            blocks.append({
                "block_type": 2,  # text
                "text": {"elements": [_text_element(content)]},
            })

    return blocks


def build_progress_card(task_id: str, step: str, progress: float) -> Dict[str, Any]:
    """构建任务进度卡片。"""
    step_names = {
        "receive_input": "接收输入",
        "parse_intent": "分析需求",
        "plan_workflow": "规划流程",
        "extract_tasks": "提取任务",
        "generate_doc": "生成文档",
        "generate_slides": "生成 PPT",
        "confirm_or_modify": "等待确认",
        "deliver_result": "交付结果",
    }
    step_name = step_names.get(step, step)
    pct = int(progress * 100)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Agent-Pilot 任务进行中"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**当前步骤**: {step_name}\n**任务 ID**: `{task_id}`"},
            },
            {
                "tag": "progress_bar",
                "progress_bar": {"percentage": pct, "indicator": True},
            },
        ],
    }


def build_delivery_card(
    task_id: str,
    doc_title: str = None,
    doc_url: str = None,
    slides_title: str = None,
    slides_count: int = 0,
    chat_id: str = None,
) -> Dict[str, Any]:
    """构建任务交付卡片（含交互按钮）。"""
    elements: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**任务 ID**: `{task_id}`"},
        },
    ]

    if doc_title:
        doc_line = f"📄 **文档**: {doc_title}"
        if doc_url:
            doc_line += f"  [查看]({doc_url})"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": doc_line}})

    if slides_title:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"📊 **PPT**: {slides_title} ({slides_count} 页)"},
        })

    elements.append({"tag": "hr"})

    # Interactive buttons
    action_value: Dict[str, str] = {"task_id": task_id}
    if chat_id:
        action_value["chat_id"] = chat_id

    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "确认交付"},
                "type": "primary",
                "value": {**action_value, "action": "confirm_delivery"},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "需要修改"},
                "type": "default",
                "value": {**action_value, "action": "request_modification"},
            },
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "Agent-Pilot 任务完成"},
            "template": "green",
        },
        "elements": elements,
    }


lark_bot_service = LarkBotService()
