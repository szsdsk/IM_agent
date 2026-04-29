import unittest
from unittest.mock import AsyncMock, patch

from backend.agent.orchestrator import AgentOrchestrator
from backend.agent import nodes
from backend.tools.tool_factory import ToolFactory


class LangGraphRoutingTests(unittest.TestCase):
    def test_routes_to_doc_when_document_is_required(self):
        state = {"content_types": ["doc"], "steps": [{"module": "DOC"}], "error": None}

        self.assertEqual(AgentOrchestrator._route_after_extract(state), "generate_doc")

    def test_routes_to_slides_when_only_deck_is_required(self):
        state = {"content_types": ["slides"], "steps": [{"module": "DECK"}], "error": None}

        self.assertEqual(AgentOrchestrator._route_after_extract(state), "generate_slides")

    def test_routes_error_to_delivery(self):
        state = {"content_types": ["slides"], "steps": [{"module": "DECK"}], "error": "failed"}

        self.assertEqual(AgentOrchestrator._route_after_extract(state), "deliver_result")

    def test_extracts_chinese_slide_feedback_target(self):
        self.assertEqual(AgentOrchestrator._extract_slide_indexes("第 3 页改成风险分析", 8), [2])

    def test_extracts_english_slide_feedback_target(self):
        self.assertEqual(AgentOrchestrator._extract_slide_indexes("slide 5 add Q&A", 8), [4])

    def test_rehearsal_request_does_not_force_slide_rewrite(self):
        should_update = AgentOrchestrator._should_update_slides(
            "帮我生成排练讲稿和 Q&A",
            {},
            {"slides": [{"title": "封面"}]},
        )

        self.assertFalse(should_update)

    def test_predicts_slides_after_canvas(self):
        orchestrator = AgentOrchestrator()
        state = {"content_types": ["canvas", "slides"], "steps": [{"module": "CANVAS"}, {"module": "DECK"}], "error": None}

        self.assertEqual(orchestrator._next_step_after("generate_canvas", state), "generate_slides")


class FeedbackRevisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slide_feedback_handles_deck_without_document(self):
        orchestrator = AgentOrchestrator()
        base_result = {
            "slides": {
                "title": "原神汇报",
                "slides": [
                    {"index": 0, "title": "封面", "content": "原神"},
                    {"index": 1, "title": "背景", "content": "游戏背景"},
                    {"index": 2, "title": "角色", "content": "角色介绍"},
                    {"index": 3, "title": "数据", "content": "基础数据"},
                ],
                "metadata": {},
            }
        }

        # 只测反馈编排对空文档的兼容，PPT 文件导出由工具层单测覆盖。
        with (
            patch(
                "backend.agent.orchestrator.revise_targeted_slides",
                new=AsyncMock(return_value={
                    "target_slide_indexes": [3],
                    "global_change": False,
                    "summary": "Updated target slide.",
                    "revised_slides": [{"index": 3, "title": "数据", "content": "更详细的数据说明"}],
                }),
            ),
            patch(
                "backend.agent.orchestrator.generate_rehearsal",
                new=AsyncMock(return_value={"slides": [], "total_duration_minutes": 1, "tips": []}),
            ),
            patch(
                "backend.agent.orchestrator.generate_qa",
                new=AsyncMock(return_value={"items": []}),
            ),
            patch.object(
                ToolFactory,
                "invoke_tool",
                new=AsyncMock(return_value={"success": True, "slide_id": "slide_1", "file_path": "deck.pptx"}),
            ),
            patch("backend.agent.orchestrator.sync_service.broadcast_delivery", new=AsyncMock()),
        ):
            state = await orchestrator.handle_user_feedback(
                session_id="session_1",
                task_id="task_1",
                feedback="第四页数据更详细一点",
                base_result=base_result,
            )

        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["slides_content"]["slide_id"], "slide_1")

    async def test_explicit_slide_feedback_never_rewrites_whole_deck(self):
        orchestrator = AgentOrchestrator()
        base_result = {
            "slides": {
                "title": "策划案 PPT",
                "slides": [
                    {"index": 0, "title": "封面", "bullets": ["项目标题"]},
                    {"index": 1, "title": "背景", "bullets": ["背景说明"]},
                ],
                "metadata": {},
            }
        }

        revise_deck = AsyncMock(return_value={"title": "错误的新主题", "slides": []})
        with (
            patch(
                "backend.agent.orchestrator.revise_targeted_slides",
                new=AsyncMock(return_value={
                    "target_slide_indexes": [0],
                    "global_change": True,
                    "summary": "Model incorrectly requested global rewrite.",
                    "revised_slides": [],
                }),
            ),
            patch("backend.agent.orchestrator.revise_deck_spec", new=revise_deck),
            patch.object(
                ToolFactory,
                "invoke_tool",
                new=AsyncMock(return_value={"success": True, "slide_id": "slide_1", "file_path": "deck.pptx"}),
            ),
            patch("backend.agent.orchestrator.sync_service.broadcast_delivery", new=AsyncMock()),
        ):
            state = await orchestrator.handle_user_feedback(
                session_id="session_1",
                task_id="task_1",
                feedback="第一页再详细一点",
                base_result=base_result,
            )

        revise_deck.assert_not_awaited()
        self.assertEqual(state["slides_content"]["slides"][1]["title"], "背景")
        self.assertIn("第一页再详细一点", state["slides_content"]["slides"][0]["bullets"][-1])


class CanvasGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_canvas_does_not_call_llm(self):
        state = {
            "task_id": "task_canvas",
            "intent": "生成系统架构图 canvas",
            "doc_content": None,
            "steps": [{"module": "CANVAS", "action": "generate_canvas"}],
            "messages": [],
            "updated_at": "",
        }

        with patch("backend.agent.nodes.generate_canvas_spec", new=AsyncMock(return_value={
            "title": "系统架构图",
            "diagram_type": "flow",
            "nodes": [{"id": "n1", "text": "开始", "type": "start"}],
            "edges": [],
            "layers": [],
        })) as canvas_spec:
            result = await nodes.generate_canvas(state)

        canvas_spec.assert_awaited_once()
        self.assertFalse(canvas_spec.await_args.kwargs["use_llm"])
        self.assertEqual(result["canvas_content"]["provider"], "local_mock")


class DeliveryResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_result_keeps_lark_doc_fields(self):
        state = {
            "task_id": "task_doc",
            "status": "running",
            "current_step": "confirm_or_modify",
            "progress": 0.9,
            "messages": [],
            "updated_at": "",
            "doc_content": {
                "doc_id": "doc_1",
                "title": "飞书文档",
                "content": "正文",
                "content_preview": "正文",
                "doc_url": "https://example.feishu.cn/docx/doc_1",
                "lark_doc_id": "doc_1",
                "lark_doc_url": "https://example.feishu.cn/docx/doc_1",
                "version": 1,
            },
        }

        result = await nodes.deliver_result(state)

        document = result["result"]["document"]
        self.assertEqual(document["lark_doc_id"], "doc_1")
        self.assertEqual(document["lark_doc_url"], "https://example.feishu.cn/docx/doc_1")


if __name__ == "__main__":
    unittest.main()
