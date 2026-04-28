import unittest

from backend.services.llm_service import IntentAnalysis, LLMService


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


if __name__ == "__main__":
    unittest.main()
