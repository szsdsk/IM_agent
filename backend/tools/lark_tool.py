import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.tools.base import BaseTool


class LarkTool(BaseTool):
    """飞书 CLI 适配器，负责把项目内部动作转换成 lark-cli 命令。"""

    def __init__(
        self,
        mock_mode: bool = False,
        cli_enabled: Optional[bool] = None,
        cli_bin: Optional[str] = None,
        as_identity: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        default_chat_id: Optional[str] = None,
    ):
        super().__init__("LarkTool", mock_mode)
        # 支持测试注入配置；生产默认从 settings 读取，避免把飞书授权写进代码。
        self._cli_enabled = settings.LARK_CLI_ENABLED if cli_enabled is None else cli_enabled
        self._cli_bin = cli_bin or settings.LARK_CLI_BIN
        self._as_identity = as_identity or settings.LARK_CLI_AS
        self._timeout_seconds = timeout_seconds or settings.LARK_CLI_TIMEOUT_SECONDS
        self._default_chat_id = default_chat_id if default_chat_id is not None else settings.LARK_DEFAULT_CHAT_ID

    async def execute(
        self,
        action: str,
        entity_type: str = None,
        entity_id: str = None,
        data: Dict = None,
        **kwargs,
    ) -> Dict[str, Any]:
        self._log("info", f"Lark action: {action}", {"entity_type": entity_type, "entity_id": entity_id})

        # 所有对外结果都带 provider，前端和日志可以明确知道当前走的是 CLI 通道。
        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "provider": "lark_cli", "error": "Missing required parameter: action"}

        # data 和 kwargs 合并后再分发，方便 API 层按业务字段传参。
        payload = {**(data or {}), **kwargs}

        if self.mock_mode:
            return await self._mock_execute(action, entity_type, entity_id, payload)

        # status 即使关闭同步也可以调用，用于健康检查展示真实配置状态。
        if action == "status":
            return await self.get_status(check_auth=True)

        # 默认不启用真实飞书，确保本地文档/PPT 生成闭环不被外部依赖拖垮。
        if not self._cli_enabled:
            return self._disabled_result(action)

        try:
            if action == "create_document":
                return await self._create_document(payload)
            if action == "upload_file":
                return await self._upload_file(payload)
            if action == "send_message":
                return await self._send_message(payload)
            if action == "sync_artifact":
                return await self._sync_artifact(entity_id, payload)
            return {"success": False, "provider": "lark_cli", "error": f"Unknown action: {action}"}
        except Exception as exc:
            self._log("error", f"Lark CLI action failed: {str(exc)}")
            return {"success": False, "provider": "lark_cli", "error": str(exc)}

    async def get_status(self, check_auth: bool = False) -> Dict[str, Any]:
        """返回 CLI 可用性和登录状态，供健康检查和前端按钮使用。"""
        available = self._cli_available()
        status = {
            "success": True,
            "provider": "lark_cli",
            "enabled": self._cli_enabled,
            "available": available,
            "authenticated": False,
            "bin": self._cli_bin,
            "as_identity": self._as_identity,
        }

        if not self._cli_enabled:
            status["message"] = "Lark CLI sync is disabled. Set LARK_CLI_ENABLED=true after configuring lark-cli."
            return status

        if not available:
            status.update({
                "success": False,
                "error": f"Lark CLI binary not found: {self._cli_bin}",
            })
            return status

        if check_auth:
            # 登录状态检查控制在较短超时内，避免 /health 被 CLI 卡住。
            auth_result = await self._run_command(["auth", "status"], timeout_seconds=min(self._timeout_seconds, 5))
            status["authenticated"] = auth_result.get("success", False)
            if not auth_result.get("success"):
                status["error"] = auth_result.get("error") or "Lark CLI is not authenticated."
            else:
                status["message"] = "Lark CLI is available and authenticated."
                status["details"] = auth_result.get("data")

        return status

    async def _mock_execute(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        await self._simulate_delay(0.2)
        self._log("info", f"Mock Lark action executed: {action}")

        # Mock 返回保持与真实返回同形，前端无需区分 mock/real。
        if action == "status":
            return {
                "success": True,
                "provider": "lark_cli",
                "enabled": True,
                "available": True,
                "authenticated": True,
                "bin": self._cli_bin,
                "as_identity": self._as_identity,
            }

        if action == "create_document":
            return {
                "success": True,
                "provider": "lark_cli",
                "document_id": f"lark_doc_{int(time.time() * 1000)}",
                "lark_token": f"doc_token_{int(time.time() * 1000)}",
                "lark_url": "https://example.feishu.cn/docx/mock",
                "title": data.get("title") or "Agent-Pilot Document",
            }

        if action == "upload_file":
            return {
                "success": True,
                "provider": "lark_cli",
                "file_key": f"file_key_{int(time.time() * 1000)}",
                "lark_token": f"file_token_{int(time.time() * 1000)}",
                "lark_url": "https://example.feishu.cn/file/mock",
            }

        if action == "send_message":
            return {
                "success": True,
                "provider": "lark_cli",
                "message_id": f"message_{int(time.time() * 1000)}",
            }

        if action == "sync_artifact":
            return {
                "success": True,
                "provider": "lark_cli",
                "artifact_id": entity_id,
                "lark_url": "https://example.feishu.cn/docx/mock",
                "message": "Mock artifact synced to Lark.",
            }

        return {"success": True, "provider": "lark_cli", "action": action}

    async def _create_document(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """通过 lark-cli docs +create 创建飞书云文档。"""
        title = data.get("title") or "Agent-Pilot 文档"
        # CLI 文档创建使用 markdown 内容，标题缺失时由 _document_content 补齐一级标题。
        content = self._document_content(title, data.get("content") or "")
        result = await self._run_command([
            "docs",
            "+create",
            "--api-version",
            "v2",
            "--doc-format",
            "markdown",
            "--content",
            content,
            *self._identity_args(),
        ])
        return self._with_lark_fields(result, title=title)

    async def _upload_file(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """通过飞书 Drive 命令上传本地文件，当前主要用于 PPTX 交付物。"""
        file_path = self._resolve_local_file(data.get("file_path") or data.get("path"))
        if not file_path:
            return {"success": False, "provider": "lark_cli", "error": "Missing file_path for Lark upload."}
        if not file_path.is_file():
            return {"success": False, "provider": "lark_cli", "error": f"File not found: {file_path}"}

        title = data.get("title") or file_path.name
        # lark-cli 不同版本的 upload 参数可能略有差异，按最明确到最宽松逐个尝试。
        command_candidates = [
            ["drive", "+upload", "--file", str(file_path), "--name", title, *self._identity_args()],
            ["drive", "+upload", "--file", str(file_path), *self._identity_args()],
            ["drive", "upload", "--file", str(file_path), "--name", title, *self._identity_args()],
            ["drive", "upload", "--file", str(file_path), *self._identity_args()],
        ]

        last_result: Dict[str, Any] = {}
        for command in command_candidates:
            result = await self._run_command(command)
            if result.get("success"):
                return self._with_lark_fields(result, title=title)
            last_result = result

        return last_result or {"success": False, "provider": "lark_cli", "error": "Lark file upload failed."}

    async def _send_message(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """向默认或指定飞书群发送交付通知。"""
        chat_id = data.get("chat_id") or self._default_chat_id
        text = data.get("text") or data.get("message")
        if not chat_id:
            return {"success": False, "provider": "lark_cli", "error": "LARK_DEFAULT_CHAT_ID is not configured."}
        if not text:
            return {"success": False, "provider": "lark_cli", "error": "Missing message text."}

        result = await self._run_command([
            "im",
            "+messages-send",
            "--chat-id",
            chat_id,
            "--text",
            text,
            *self._identity_args(),
        ])
        return self._with_lark_fields(result)

    async def _sync_artifact(self, artifact_id: Optional[str], data: Dict[str, Any]) -> Dict[str, Any]:
        """根据 artifact 类型选择文档创建或文件上传，并可选发送飞书消息。"""
        artifact_type = str(data.get("artifact_type") or "").lower()
        if artifact_type in {"document", "doc"}:
            sync_result = await self._create_document(data)
        elif artifact_type in {"slide", "slides", "deck", "ppt", "file"}:
            sync_result = await self._upload_file(data)
        else:
            return {
                "success": False,
                "provider": "lark_cli",
                "artifact_id": artifact_id,
                "error": f"Unsupported artifact type: {artifact_type or 'unknown'}",
            }

        if not sync_result.get("success"):
            # 同步失败不能反向污染本地生成结果，只把失败信息返回给同步接口。
            return {
                **sync_result,
                "artifact_id": artifact_id,
                "message": "本地生成成功，但同步到飞书失败。",
            }

        notify_result = None
        if data.get("notify", True):
            # 通知是附加动作，失败时保留同步成功结果并在 message 中提示。
            message_text = data.get("message") or self._delivery_message(data, sync_result)
            notify_result = await self._send_message({
                "chat_id": data.get("chat_id"),
                "text": message_text,
            })

        return {
            "success": True,
            "provider": "lark_cli",
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "lark_url": sync_result.get("lark_url"),
            "lark_token": sync_result.get("lark_token"),
            "message": "已同步到飞书。" if not notify_result else self._notify_message(notify_result),
            "details": {
                "sync": sync_result,
                "notify": notify_result,
            },
        }

    async def _run_command(self, args: List[str], timeout_seconds: Optional[int] = None) -> Dict[str, Any]:
        """统一执行 lark-cli，并把 stdout/stderr 归一化成项目内部结果。"""
        cli_path = self._cli_path()
        if not cli_path:
            return {
                "success": False,
                "provider": "lark_cli",
                "error": f"Lark CLI binary not found: {self._cli_bin}",
            }

        command = [cli_path, *args, "--format", "json"]
        timeout = timeout_seconds or self._timeout_seconds

        try:
            # Windows 下部分事件循环不支持 asyncio 子进程，所以把同步 subprocess 放进线程池。
            completed = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "provider": "lark_cli",
                "error": f"Lark CLI command timed out after {timeout} seconds.",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "provider": "lark_cli",
                "error": f"Lark CLI binary not found: {self._cli_bin}",
            }
        except OSError as exc:
            return {
                "success": False,
                "provider": "lark_cli",
                "error": self._redact(str(exc)),
            }

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        # 有些 CLI 会在 JSON 外打印提示文案，所以解析失败时还会尝试提取花括号片段。
        parsed = self._parse_output(stdout)
        success = completed.returncode == 0

        if success:
            return {
                "success": True,
                "provider": "lark_cli",
                "data": parsed,
                "stdout": stdout if parsed is None else None,
            }

        return {
            "success": False,
            "provider": "lark_cli",
            "data": parsed,
            "error": self._redact(stderr or stdout or f"Lark CLI exited with code {completed.returncode}"),
        }

    def _with_lark_fields(self, result: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
        """从不同 CLI 返回结构中提取统一的 lark_url 和 lark_token。"""
        data = result.get("data")
        return {
            **result,
            **extra,
            "lark_url": self._extract_first(data, {"url", "doc_url", "file_url", "presentation_url", "share_url", "web_url"}),
            "lark_token": self._extract_first(data, {"token", "file_token", "document_id", "document_token", "obj_token"}),
        }

    def _identity_args(self) -> List[str]:
        """给所有 CLI 命令追加授权身份参数。"""
        return ["--as", self._as_identity] if self._as_identity else []

    def _cli_available(self) -> bool:
        """同时支持 PATH 命令和显式可执行文件路径。"""
        return bool(self._cli_path())

    def _cli_path(self) -> Optional[str]:
        """解析真实 CLI 路径，Windows 下 npm 全局命令通常会落到 lark-cli.cmd。"""
        resolved = shutil.which(self._cli_bin)
        if resolved:
            return resolved

        explicit_path = Path(self._cli_bin)
        if explicit_path.is_file():
            return str(explicit_path)

        return None

    def _disabled_result(self, action: str) -> Dict[str, Any]:
        """同步未启用时返回可展示的失败原因，不抛异常。"""
        return {
            "success": False,
            "provider": "lark_cli",
            "action": action,
            "enabled": False,
            "error": "Lark CLI sync is disabled. Set LARK_CLI_ENABLED=true after installing and logging in with lark-cli.",
        }

    def _document_content(self, title: str, content: str) -> str:
        """保证同步到飞书的 Markdown 至少有一个标题。"""
        stripped = content.strip()
        if stripped.startswith("#"):
            return stripped
        return f"# {title}\n\n{stripped}" if stripped else f"# {title}"

    def _delivery_message(self, data: Dict[str, Any], sync_result: Dict[str, Any]) -> str:
        """生成发送到飞书群的默认交付消息。"""
        title = data.get("title") or "Agent-Pilot 交付物"
        url = sync_result.get("lark_url")
        if url:
            return f"Agent-Pilot 已生成并同步：{title}\n{url}"
        return f"Agent-Pilot 已生成并同步：{title}"

    def _notify_message(self, notify_result: Dict[str, Any]) -> str:
        """把飞书消息发送结果压缩成适合前端展示的一句话。"""
        if notify_result.get("success"):
            return "已同步到飞书，并已发送交付消息。"
        return f"已同步到飞书，但消息发送失败：{notify_result.get('error')}"

    def _resolve_local_file(self, value: Optional[str]) -> Optional[Path]:
        """把前端可访问的下载 URL 或本地路径解析回后端文件路径。"""
        if not value:
            return None

        if value.startswith("/api/files/slides/"):
            # 下载 URL 只允许映射到后端 slides 输出目录，避免任意路径访问。
            filename = Path(value).name
            return Path(__file__).resolve().parents[1] / "data" / "slides" / filename

        path = Path(value)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    def _parse_output(self, stdout: str) -> Any:
        """解析 CLI JSON 输出，兼容前后带提示文本的情况。"""
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            start = stdout.find("{")
            end = stdout.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(stdout[start:end + 1])
                except json.JSONDecodeError:
                    return None
        return None

    def _extract_first(self, value: Any, keys: set[str]) -> Optional[str]:
        """递归查找飞书返回中的 URL 或 token 字段。"""
        if isinstance(value, dict):
            for key, item in value.items():
                if key in keys and item:
                    return str(item)
            for item in value.values():
                found = self._extract_first(item, keys)
                if found:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._extract_first(item, keys)
                if found:
                    return found
        return None

    def _redact(self, text: str) -> str:
        """日志和错误返回中隐藏本地配置里的敏感值。"""
        redacted = text
        for secret in (settings.LARK_APP_SECRET, settings.OPENAI_API_KEY):
            if secret:
                redacted = redacted.replace(secret, "***")
        return redacted[:2000]

    async def _simulate_delay(self, seconds: float):
        await asyncio.sleep(seconds)
