"""PPT Agent 子图单元测试。

覆盖 S1 outline / S2 structure / S3 content / S4 render 四个节点，
以及 layout 映射表和公共入口 run_ppt_agent()。
"""
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.ppt_agent import (
    PPTAgentState,
    LAYOUT_TO_MCK_METHOD,
    outline_node,
    structure_node,
    content_node,
    render_node,
    run_ppt_agent,
)


class TestLayoutMapping(unittest.TestCase):
    """S2 布局映射表正确性验证。"""

    def test_hero_maps_to_cover(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["hero"], "cover")

    def test_title_maps_to_cover(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["title"], "cover")

    def test_metrics_maps_to_metric_comparison(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["metrics"], "metric_comparison")

    def test_timeline_maps_to_timeline(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["timeline"], "timeline")

    def test_process_maps_to_process_chevron(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["process"], "process_chevron")
        self.assertEqual(LAYOUT_TO_MCK_METHOD["diagram"], "process_chevron")

    def test_comparison_maps_to_two_column_compare(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["comparison"], "two_column_compare")
        self.assertEqual(LAYOUT_TO_MCK_METHOD["two_column"], "two_column_compare")

    def test_closing_maps_to_closing(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["closing"], "closing")

    def test_cards_maps_to_four_column(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["cards"], "four_column")

    def test_chart_default_is_column_comparison(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["chart"], "column_comparison")

    def test_content_default_is_table_insight(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["content"], "table_insight")

    def test_blank_fallback_to_agenda(self):
        self.assertEqual(LAYOUT_TO_MCK_METHOD["blank"], "agenda")

    def test_all_valid_layouts_have_mapping(self):
        valid = {
            "title", "content", "two_column", "diagram", "blank",
            "hero", "section_divider", "metrics", "timeline", "comparison",
            "process", "cards", "closing", "chart",
        }
        for layout in valid:
            self.assertIn(layout, LAYOUT_TO_MCK_METHOD, f"layout '{layout}' missing mapping")


class TestOutlineNode(unittest.TestCase):
    """S1: brief 生成节点。"""

    def _base_state(self) -> PPTAgentState:
        return {
            "deck_spec": {
                "title": "Test Deck",
                "audience": "管理层",
                "slides": [
                    {"index": 0, "title": "封面", "layout": "title"},
                    {"index": 1, "title": "背景", "layout": "content", "bullets": ["要点A"]},
                    {"index": 2, "title": "Q&A", "layout": "closing"},
                ],
            },
            "doc_content": "测试文档内容",
            "intent": "帮我做一个PPT",
            "audience": "管理层",
            "presentation_scene": None,
            "messages": [],
        }

    @patch("backend.agent.ppt_agent._generate_brief_via_llm")
    async def test_outline_generates_brief(self, mock_llm):
        mock_llm.return_value = {
            "title": "Test Deck",
            "subtitle": "Subtitle",
            "slide_count": 3,
            "key_messages": ["msg1"],
            "tone": "formal",
            "date": "2026-05-04",
            "sections": [],
        }
        state = self._base_state()
        result = await outline_node(state)
        self.assertIsNotNone(result.get("ppt_brief"))
        self.assertEqual(result["ppt_brief"]["title"], "Test Deck")
        self.assertIsNone(result.get("error"))

    @patch("backend.agent.ppt_agent._generate_brief_via_llm")
    async def test_outline_falls_back_on_llm_error(self, mock_llm):
        mock_llm.side_effect = Exception("LLM unavailable")
        state = self._base_state()
        result = await outline_node(state)
        # Should have fallback brief, not error
        self.assertIsNotNone(result.get("ppt_brief"))
        self.assertIn("fallback", result.get("ppt_brief", {}).get("title", "").lower())


class TestStructureNode(unittest.TestCase):
    """S2: 结构映射节点。"""

    def _state_with_brief(self) -> PPTAgentState:
        return {
            "deck_spec": {
                "title": "Q1 Review",
                "slides": [
                    {"index": 0, "title": "封面", "layout": "title"},
                    {"index": 1, "title": "背景", "layout": "content", "bullets": ["A", "B"]},
                    {"index": 2, "title": "指标", "layout": "metrics", "highlight_metrics": [{"value": "+23%", "label": "增长"}]},
                    {"index": 3, "title": "收入", "layout": "chart", "chart": {"type": "bar", "categories": ["Q1"], "series": [{"name": "收入", "values": [100]}]}},
                    {"index": 4, "title": "占比", "layout": "chart", "chart": {"type": "pie", "categories": ["A", "B"], "series": [{"values": [40, 60]}]}},
                    {"index": 5, "title": "路线图", "layout": "timeline", "timeline": [{"label": "Q1", "text": "启动"}]},
                    {"index": 6, "title": "对比", "layout": "comparison", "bullets": ["旧方案", "新方案"]},
                    {"index": 7, "title": "流程", "layout": "process", "process_steps": [{"label": "01", "text": "步骤1"}]},
                    {"index": 8, "title": "卡片", "layout": "cards", "sections": [{"title": "卡1", "body": "内容1"}]},
                    {"index": 9, "title": "分隔页", "layout": "section_divider"},
                    {"index": 10, "title": "谢谢", "layout": "closing"},
                    {"index": 11, "title": "空白", "layout": "blank", "bullets": ["X"]},
                ],
            },
            "ppt_brief": {
                "title": "Q1 Review Brief",
                "slide_count": 12,
            },
            "messages": [],
        }

    async def test_first_slide_always_cover(self):
        state = self._state_with_brief()
        result = await structure_node(state)
        outline = result["ppt_outline"]
        self.assertEqual(outline[0]["mck_method"], "cover")

    async def test_last_slide_closing_detected(self):
        state = self._state_with_brief()
        result = await structure_node(state)
        outline = result["ppt_outline"]
        closing_idx = [i for i, o in enumerate(outline) if o["mck_method"] == "closing"]
        self.assertTrue(any(closing_idx))

    async def test_pie_chart_maps_to_donut(self):
        state = self._state_with_brief()
        result = await structure_node(state)
        pie_slide = [o for o in result["ppt_outline"] if o["title"] == "占比"][0]
        self.assertEqual(pie_slide["mck_method"], "donut")

    async def test_bar_chart_stays_column_comparison(self):
        state = self._state_with_brief()
        result = await structure_node(state)
        bar_slide = [o for o in result["ppt_outline"] if o["title"] == "收入"][0]
        self.assertEqual(bar_slide["mck_method"], "column_comparison")

    async def test_preserves_slide_order(self):
        state = self._state_with_brief()
        result = await structure_node(state)
        indices = [o["index"] for o in result["ppt_outline"]]
        self.assertEqual(indices, sorted(indices))

    async def test_unknown_layout_fallbacks(self):
        state = {
            "deck_spec": {"slides": [{"index": 0, "title": "Test", "layout": "nonexistent_layout"}]},
            "ppt_brief": {"title": "T", "slide_count": 1},
            "messages": [],
        }
        result = await structure_node(state)
        self.assertEqual(result["ppt_outline"][0]["mck_method"], "table_insight")


class TestContentNode(unittest.TestCase):
    """S3: 内容填充节点。"""

    def _state_with_outline(self) -> PPTAgentState:
        return {
            "deck_spec": {
                "title": "Test Deck",
                "slides": [
                    {"index": 0, "title": "封面", "layout": "title", "bullets": ["副标题"]},
                    {"index": 1, "title": "内容页", "layout": "content", "bullets": ["要点1", "要点2", "要点3"]},
                    {"index": 2, "title": "指标", "layout": "metrics", "highlight_metrics": [
                        {"value": "+23%", "label": "增长"}, {"value": "$14M", "label": "ARR"}
                    ]},
                    {"index": 3, "title": "对比", "layout": "comparison", "bullets": ["旧:A", "新:B", "旧:C", "新:D"]},
                    {"index": 4, "title": "时间线", "layout": "timeline", "timeline": [
                        {"label": "Q1", "text": "启动"}, {"label": "Q2", "text": "扩展"}
                    ]},
                    {"index": 5, "title": "流程", "layout": "process", "process_steps": [
                        {"label": "01", "text": "分析"}, {"label": "02", "text": "设计"}
                    ]},
                    {"index": 6, "title": "卡片", "layout": "cards", "sections": [
                        {"title": "机会", "body": "描述1"}, {"title": "风险", "body": "描述2"}
                    ]},
                    {"index": 7, "title": "柱状图", "layout": "chart", "chart": {
                        "type": "bar", "categories": ["Q1", "Q2"],
                        "series": [{"name": "2025", "values": [100, 120]}, {"name": "2026", "values": [130, 150]}]
                    }},
                    {"index": 8, "title": "饼图", "layout": "chart", "chart": {
                        "type": "pie", "categories": ["产品A", "产品B", "其他"],
                        "series": [{"values": [45, 35, 20]}]
                    }},
                    {"index": 9, "title": "结束", "layout": "closing"},
                ],
            },
            "ppt_outline": [
                {"index": 0, "title": "封面", "mck_method": "cover", "content_hint": ""},
                {"index": 1, "title": "内容页", "mck_method": "table_insight", "content_hint": ""},
                {"index": 2, "title": "指标", "mck_method": "metric_comparison", "content_hint": ""},
                {"index": 3, "title": "对比", "mck_method": "two_column_compare", "content_hint": ""},
                {"index": 4, "title": "时间线", "mck_method": "timeline", "content_hint": ""},
                {"index": 5, "title": "流程", "mck_method": "process_chevron", "content_hint": ""},
                {"index": 6, "title": "卡片", "mck_method": "four_column", "content_hint": ""},
                {"index": 7, "title": "柱状图", "mck_method": "column_comparison", "content_hint": ""},
                {"index": 8, "title": "饼图", "mck_method": "donut", "content_hint": ""},
                {"index": 9, "title": "结束", "mck_method": "closing", "content_hint": ""},
            ],
            "ppt_brief": {"title": "T", "subtitle": "S", "date": "2026-05-04"},
            "messages": [],
        }

    async def test_all_slides_get_params(self):
        state = self._state_with_outline()
        result = await content_node(state)
        filled = result["ppt_filled_slides"]
        self.assertEqual(len(filled), 10)
        for slide in filled:
            self.assertIn("rendered_params", slide)

    async def test_cover_has_subtitle_from_bullets(self):
        state = self._state_with_outline()
        result = await content_node(state)
        cover = [s for s in result["ppt_filled_slides"] if s["mck_method"] == "cover"][0]
        self.assertIn("subtitle", cover["rendered_params"])

    async def test_table_insight_converts_bullets(self):
        state = self._state_with_outline()
        result = await content_node(state)
        table = [s for s in result["ppt_filled_slides"] if s["mck_method"] == "table_insight"][0]
        params = table["rendered_params"]
        self.assertIn("rows", params)
        self.assertTrue(len(params["rows"]) >= 2)

    async def test_timeline_converts_milestones(self):
        state = self._state_with_outline()
        result = await content_node(state)
        tl = [s for s in result["ppt_filled_slides"] if s["mck_method"] == "timeline"][0]
        milestones = tl["rendered_params"]["milestones"]
        self.assertEqual(len(milestones), 2)

    async def test_donut_converts_segments(self):
        state = self._state_with_outline()
        result = await content_node(state)
        donut = [s for s in result["ppt_filled_slides"] if s["mck_method"] == "donut"][0]
        segments = donut["rendered_params"]["segments"]
        self.assertEqual(len(segments), 3)


class TestRenderNode(unittest.TestCase):
    """S4: 渲染节点。"""

    @patch("backend.agent.ppt_agent.MckEngineRenderer")
    async def test_render_calls_engine_and_saves(self, MockRenderer):
        mock_renderer_instance = AsyncMock()
        mock_renderer_instance.render.return_value = {
            "success": True,
            "filepath": "/tmp/test.pptx",
            "slides_count": 3,
        }
        MockRenderer.return_value = mock_renderer_instance

        state: PPTAgentState = {
            "ppt_filled_slides": [
                {"index": 0, "title": "Cover", "mck_method": "cover", "rendered_params": {"title": "T"}},
                {"index": 1, "title": "Content", "mck_method": "table_insight", "rendered_params": {"title": "C"}},
                {"index": 2, "title": "End", "mck_method": "closing", "rendered_params": {"title": "E"}},
            ],
            "ppt_brief": {"title": "T"},
            "messages": [],
        }
        result = await render_node(state)
        self.assertTrue(result["ppt_render_result"]["success"])
        self.assertEqual(result["ppt_render_result"]["slides_count"], 3)

    @patch("backend.agent.ppt_agent.MckEngineRenderer")
    async def test_render_sets_error_on_failure(self, MockRenderer):
        mock_renderer_instance = AsyncMock()
        mock_renderer_instance.render.return_value = {"success": False, "error": "engine crash"}
        MockRenderer.return_value = mock_renderer_instance

        state: PPTAgentState = {
            "ppt_filled_slides": [{"index": 0, "title": "X", "mck_method": "cover", "rendered_params": {}}],
            "ppt_brief": {},
            "messages": [],
        }
        result = await render_node(state)
        self.assertIn("error", result)


class TestRunPptAgentIntegration(unittest.IsolatedAsyncioTestCase):
    """端到端：run_ppt_agent() 错误传播。"""

    @patch("backend.agent.ppt_agent.render_node")
    @patch("backend.agent.ppt_agent.content_node")
    @patch("backend.agent.ppt_agent.structure_node")
    @patch("backend.agent.ppt_agent.outline_node")
    async def test_error_propagates(self, mock_s1, mock_s2, mock_s3, mock_s4):
        async def failing_s1(state):
            state["error"] = "LLM timeout"
            return state
        mock_s1.side_effect = failing_s1

        result = await run_ppt_agent(
            deck_spec={"title": "Test", "slides": []},
        )
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
