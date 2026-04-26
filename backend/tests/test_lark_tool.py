import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.tools.lark_tool import LarkTool


class FakeCompletedProcess:
    """模拟 subprocess.run 的返回值，避免测试时真的调用 lark-cli。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LarkToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_sync_does_not_call_cli(self):
        # 默认关闭真实同步时，应返回可展示错误，而不是尝试执行 CLI。
        tool = LarkTool(mock_mode=False, cli_enabled=False)

        result = await tool.execute(
            action="sync_artifact",
            entity_id="artifact-1",
            data={"artifact_type": "document", "title": "测试", "content": "内容"},
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["enabled"])
        self.assertIn("disabled", result["error"])

    async def test_status_reports_missing_cli(self):
        # CLI 未安装时，健康检查需要明确告诉前端 available=false。
        tool = LarkTool(mock_mode=False, cli_enabled=True, cli_bin="missing-lark-cli")

        with patch("backend.tools.lark_tool.shutil.which", return_value=None):
            result = await tool.get_status(check_auth=True)

        self.assertFalse(result["success"])
        self.assertFalse(result["available"])
        self.assertFalse(result["authenticated"])

    async def test_create_document_parses_json_response(self):
        # CLI 成功返回 JSON 时，工具层要提取出统一的 lark_url/lark_token。
        stdout = '{"data":{"url":"https://example.feishu.cn/docx/abc","document_id":"doc-token"}}'
        process = FakeCompletedProcess(returncode=0, stdout=stdout)
        tool = LarkTool(mock_mode=False, cli_enabled=True, cli_bin="lark-cli")

        with patch("backend.tools.lark_tool.shutil.which", return_value=r"C:\Users\tester\AppData\Roaming\npm\lark-cli.cmd"):
            with patch(
                "backend.tools.lark_tool.subprocess.run",
                return_value=process,
            ) as run_mock:
                result = await tool.execute(
                    action="create_document",
                    data={"title": "测试文档", "content": "正文"},
                )

        self.assertTrue(result["success"])
        self.assertEqual(result["lark_url"], "https://example.feishu.cn/docx/abc")
        self.assertEqual(result["lark_token"], "doc-token")
        self.assertEqual(run_mock.call_args.args[0][0], r"C:\Users\tester\AppData\Roaming\npm\lark-cli.cmd")
        self.assertNotIn("--format", run_mock.call_args.args[0])

    async def test_upload_file_uses_relative_path_inside_file_directory(self):
        # lark-cli drive +upload 拒绝绝对路径，所以后端必须切到文件目录并传 ./文件名。
        stdout = '{"data":{"file_token":"file-token","url":"https://example.feishu.cn/file/abc"}}'
        process = FakeCompletedProcess(returncode=0, stdout=stdout)
        tool = LarkTool(mock_mode=False, cli_enabled=True, cli_bin="lark-cli")

        with tempfile.TemporaryDirectory() as temp_dir:
            local_file = Path(temp_dir) / "demo.pptx"
            local_file.write_bytes(b"pptx")

            with patch("backend.tools.lark_tool.shutil.which", return_value="lark-cli"):
                with patch("backend.tools.lark_tool.subprocess.run", return_value=process) as run_mock:
                    result = await tool.execute(
                        action="upload_file",
                        data={"file_path": str(local_file), "title": "Demo PPT"},
                    )

        command = run_mock.call_args.args[0]
        self.assertTrue(result["success"])
        self.assertEqual(result["lark_url"], "https://example.feishu.cn/file/abc")
        self.assertIn("--file", command)
        self.assertEqual(command[command.index("--file") + 1], "./demo.pptx")
        self.assertIn("--name", command)
        self.assertEqual(command[command.index("--name") + 1], "Demo PPT.pptx")
        self.assertEqual(run_mock.call_args.kwargs["cwd"], str(local_file.parent))

    async def test_command_timeout_returns_failure(self):
        # 外部命令超时必须返回失败，避免 FastAPI 请求被长期挂住。
        tool = LarkTool(mock_mode=False, cli_enabled=True, cli_bin="lark-cli")

        with patch("backend.tools.lark_tool.shutil.which", return_value="lark-cli"):
            with patch(
                "backend.tools.lark_tool.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["lark-cli"], timeout=0.001),
            ):
                result = await tool._run_command(["auth", "status"], timeout_seconds=0.001)

        self.assertFalse(result["success"])
        self.assertIn("timed out", result["error"])

    async def test_upload_unknown_file_flag_returns_upgrade_hint(self):
        # 本机 CLI 版本过旧时，应提示升级，而不是只暴露生硬的 unknown flag。
        process = FakeCompletedProcess(returncode=1, stderr="Error: unknown flag: --file")
        tool = LarkTool(mock_mode=False, cli_enabled=True, cli_bin="lark-cli")

        with patch("backend.tools.lark_tool.shutil.which", return_value="lark-cli"):
            with patch("backend.tools.lark_tool.subprocess.run", return_value=process):
                result = await tool._run_command(["drive", "+upload", "--file", "demo.pptx"])

        self.assertFalse(result["success"])
        self.assertIn("请升级 @larksuite/cli", result["error"])


if __name__ == "__main__":
    unittest.main()
