import unittest
from unittest.mock import AsyncMock, patch

from backend.services.llm_service import IntentAnalysis, LLMService, generate_doc_content


class LLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_uses_mock_without_api_key(self):
        service = LLMService(api_key=None)
        service.mock_mode = True

        result = await service.chat([{"role": "user", "content": "生成一个 PPT"}])

        self.assertIn("content", result)
        self.assertEqual(result["model"], "mock")

    async def test_structured_chat_returns_default_in_mock_mode(self):
        service = LLMService(api_key=None)
        service.mock_mode = True
        default = {"intent_summary": "测试", "content_types": ["doc"]}

        result = await service.structured_chat(
            [{"role": "user", "content": "测试"}],
            IntentAnalysis,
            default=default,
        )

        self.assertEqual(result, default)

    async def test_generate_doc_content_falls_back_when_llm_returns_empty(self):
        with patch(
            "backend.services.llm_service.llm_service.chat",
            new=AsyncMock(return_value={"error": "provider error"}),
        ):
            content = await generate_doc_content(
                "王者荣耀中路英雄介绍",
                "给我做一个王者荣耀中路英雄介绍的PPT",
            )

        self.assertIn("# 王者荣耀中路英雄介绍", content)
        self.assertIn("背景与目标", content)


if __name__ == "__main__":
    unittest.main()
