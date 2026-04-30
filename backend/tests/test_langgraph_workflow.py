import unittest
from unittest.mock import AsyncMock, patch

from backend.agent.orchestrator import AgentOrchestrator
from backend.agent import nodes
from backend.services.llm_service import generate_canvas_spec, generate_deck_spec, llm_service, summarize_im_context
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

    def test_builds_executable_multi_agent_plan(self):
        state = {
            "intent": "create a management deck",
            "workflow_plan": {"goal": "create a management deck"},
            "content_types": ["doc", "slides"],
            "steps": [
                {"module": "DOC", "action": "create_doc"},
                {"module": "DECK", "action": "generate_slides"},
            ],
        }

        plan = nodes._build_agent_plan(state)
        agents = [task["agent"] for task in plan["tasks"]]

        self.assertEqual(plan["architecture"], "plan_and_execute")
        self.assertEqual(agents, ["doc_agent", "deck_agent", "rehearsal_agent", "delivery_agent"])
        self.assertEqual(plan["tasks"][1]["depends_on"], [plan["tasks"][0]["id"]])
        self.assertEqual(plan["tasks"][2]["step"], "generate_rehearsal")
        self.assertEqual(plan["tasks"][3]["step"], "prepare_delivery")
        self.assertIn("sync_agent", plan["agents"])


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


class ContentAwareGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_deck_fallback_uses_document_content(self):
        doc_content = """
        客户续费风险预警功能V1.0 MVP需求文档
        高风险客户识别滞后，平均仅提前3天发现流失风险。
        核心指标：提前14天识别高风险续费客户，上线首月高风险客户召回率提升30%。
        风险信号：登录频次下降、工单数量上升、合同到期时间、核心功能使用率。
        第1-3天需求评审，第4-10天功能开发，第11-12天灰度测试。
        """

        with patch.object(llm_service, "mock_mode", True):
            deck = await generate_deck_spec(
                title="客户续费风险预警",
                doc_content=doc_content,
                audience="管理层",
                presentation_scene="management_briefing",
            )
        all_bullets = "\n".join(
            "\n".join(slide.get("bullets", []))
            for slide in deck.get("slides", [])
        )

        self.assertIn("提前14天", all_bullets)
        self.assertIn("登录频次", all_bullets)

    async def test_canvas_fallback_uses_business_flow(self):
        spec = await generate_canvas_spec(
            title="客户续费风险预警",
            intent="生成流程图画布",
            doc_content="规则引擎计算风险等级，并推送飞书群，客户成功跟进后回流规则。",
            steps=[{"module": "CANVAS", "action": "generate_canvas"}],
            use_llm=False,
        )
        labels = [node["text"] for node in spec["nodes"]]

        self.assertIn("规则引擎计算风险分值", labels)
        self.assertIn("推送飞书群与工作台待办", labels)

    async def test_im_context_summary_extracts_structured_fields(self):
        messages = [
            {"role": "产品经理", "content": "我们要上线客户续费风险预警，目标提前14天发现高风险客户。"},
            {"role": "销售负责人", "content": "希望看到风险等级、关键原因、建议跟进动作，并推送到飞书群。"},
            {"role": "研发负责人", "content": "第一版建议先做规则引擎，两周内完成MVP。"},
        ]

        with patch.object(llm_service, "mock_mode", True):
            summary = await summarize_im_context(messages, "整理成文档和PPT")

        self.assertIn("客户续费风险预警", summary["summary"])
        self.assertTrue(any("规则引擎" in item for item in summary["decisions"]))
        self.assertGreaterEqual(len(summary["requirements"]), 1)

    def test_inline_im_context_adds_im_agent_to_plan(self):
        state = {
            "intent": "群聊上下文：产品经理说要做客户续费风险预警。请生成文档和PPT。",
            "workflow_plan": {"goal": "create artifacts"},
            "content_types": ["doc", "slides"],
            "steps": [
                {"module": "DOC", "action": "create_doc"},
                {"module": "DECK", "action": "generate_slides"},
            ],
        }

        plan = nodes._build_agent_plan(state)

        self.assertEqual(plan["tasks"][0]["agent"], "im_context_agent")


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
