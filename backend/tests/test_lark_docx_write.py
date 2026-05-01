import json
import time
import unittest

import httpx

from backend.services.lark_bot_service import LarkBotService, markdown_to_lark_blocks


class LarkDocxWriteTests(unittest.IsolatedAsyncioTestCase):
    def test_markdown_blocks_use_valid_docx_block_types(self):
        blocks = markdown_to_lark_blocks(
            "# 标题\n"
            "## 二级标题\n"
            "### 三级标题\n"
            "- 要点\n"
            "> 引用\n"
            "---\n"
            "正文"
        )
        block_types = [block["block_type"] for block in blocks]

        self.assertEqual(block_types, [3, 4, 5, 12, 15, 22, 2])
        self.assertEqual(blocks[5]["divider"], {})

    async def test_write_markdown_batches_blocks_with_revision_params(self):
        requests = []
        service = LarkBotService()
        service.app_id = "app"
        service.app_secret = "secret"
        service._tenant_access_token = "tenant_token"
        service._token_expires_at = time.time() + 3600

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode("utf-8"))
            requests.append((request.url, payload))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"children": [{"block_id": f"block_{len(requests)}"}]},
                },
            )

        service._client = httpx.AsyncClient(
            base_url=service.base_url,
            transport=httpx.MockTransport(handler),
        )
        markdown = "\n".join(f"- 第 {index} 条" for index in range(61))

        try:
            result = await service.write_markdown_to_doc("doc_1", markdown)
        finally:
            await service.close()

        self.assertTrue(result["success"])
        self.assertEqual(result["blocks_written"], 61)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0][1]["index"], 0)
        self.assertEqual(requests[1][1]["index"], 50)
        self.assertIn("document_revision_id=-1", str(requests[0][0]))
        self.assertIn("client_token=", str(requests[0][0]))


if __name__ == "__main__":
    unittest.main()
