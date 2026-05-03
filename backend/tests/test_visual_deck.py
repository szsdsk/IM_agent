import os
import tempfile
import unittest

from backend.services.deck_renderer import PptxGenRenderer
from backend.services.deck_spec import DeckSpec
from backend.services.visual_deck import normalize_visual_deck
from backend.tools.ppt_tool import PPTTool


class VisualDeckTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_deck_is_upgraded_with_visual_layouts(self):
        deck = DeckSpec(title="项目复盘 PPT", metadata={"presentation_scene": "postmortem"})
        deck.add_slide(title="封面", layout="title", bullets=["季度项目复盘"])
        deck.add_slide(title="核心指标", bullets=["转化率提升 18%", "响应时间降低 35%", "覆盖 12 个团队"])
        deck.add_slide(title="实施计划", bullets=["第 1 周：完成调研", "第 2 周：灰度上线", "第 3 周：全量发布"])
        deck.add_slide(title="下一步", bullets=["确认行动项", "同步负责人"])

        normalized = normalize_visual_deck(deck)

        self.assertEqual(normalized.theme, "slate")
        self.assertEqual(normalized.visual_profile, "review")
        self.assertEqual(normalized.slides[0].layout, "hero")
        self.assertEqual(normalized.slides[1].layout, "metrics")
        self.assertEqual(normalized.slides[2].layout, "timeline")
        self.assertEqual(normalized.slides[3].layout, "closing")
        self.assertGreaterEqual(len(normalized.slides[1].highlight_metrics), 2)

    def test_entertainment_theme_is_selected_for_game_titles(self):
        deck = DeckSpec(title="生成一个原神的 PPT")
        deck.add_slide(title="封面", layout="title", bullets=["开放世界与角色叙事"])
        deck.add_slide(title="内容亮点", bullets=["角色塑造", "地图探索", "音乐美术"])

        normalized = normalize_visual_deck(deck)

        self.assertEqual(normalized.theme, "entertainment")
        self.assertEqual(normalized.visual_profile, "entertainment")

    async def test_renderer_supports_enhanced_layouts(self):
        deck = DeckSpec(title="视觉增强样例", theme="business_blue")
        deck.add_slide(title="封面", layout="hero", bullets=["Demo", "Agent-Pilot"])
        deck.add_slide(title="指标总览", layout="metrics", highlight_metrics=[
            {"value": "30%", "label": "效率提升"},
            {"value": "12", "label": "关键任务"},
        ])
        deck.add_slide(title="路线图", layout="timeline", timeline=[
            {"label": "Phase 1", "text": "需求分析"},
            {"label": "Phase 2", "text": "方案实现"},
        ])
        deck.add_slide(title="方案对比", layout="comparison", bullets=["旧流程耗时长", "新流程自动化"])
        deck.add_slide(title="执行流程", layout="process", process_steps=[
            {"label": "01", "text": "输入需求"},
            {"label": "02", "text": "生成内容"},
        ])
        deck.add_slide(title="谢谢", layout="closing", bullets=["欢迎提问"])

        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = PptxGenRenderer(tmpdir)
            result = await renderer.render(deck, "visual_sample.pptx")

            self.assertTrue(result["success"])
            self.assertEqual(result["slides_count"], 6)
            self.assertTrue(os.path.exists(result["filepath"]))

    async def test_ppt_tool_returns_downloadable_enhanced_deck(self):
        deck = DeckSpec(title="工具层视觉增强")
        deck.add_slide(title="封面", layout="title", bullets=["Agent-Pilot"])
        deck.add_slide(title="关键指标", bullets=["完成率 95%", "耗时降低 30%"])
        deck.add_slide(title="下一步", bullets=["确认交付"])

        result = await PPTTool(mock_mode=False).ainvoke({
            "action": "create_slides",
            "task_id": "visual_tool_test",
            "title": deck.title,
            "slides": [],
            "deck_spec": deck.to_dict(),
        })

        self.assertTrue(result["success"])
        self.assertTrue(os.path.exists(result["file_path"]))
        self.assertIn("/api/files/slides/", result["download_url"])
        self.assertEqual(result["slides_count"], 3)
        self.assertEqual(result["deck_spec"]["slides"][0]["layout"], "hero")
        self.assertEqual(result["deck_spec"]["slides"][1]["layout"], "metrics")

    def test_chart_layout_is_valid(self):
        from backend.services.deck_spec import DeckSpec, validate_deck_spec
        deck = DeckSpec(title="Chart Test")
        deck.add_slide(title="Quarterly Revenue", layout="chart", chart={
            "type": "bar", "title": "Revenue",
            "categories": ["Q1", "Q2", "Q3", "Q4"],
            "series": [{"name": "Revenue", "values": [100, 150, 180, 210]}],
        })
        errors = validate_deck_spec(deck)
        self.assertEqual(errors, [])

    async def test_renderer_supports_chart_layout(self):
        import os, tempfile
        from backend.services.deck_spec import DeckSpec
        from backend.services.deck_renderer import PptxGenRenderer

        deck = DeckSpec(title="Chart Rendering Test", theme="business_blue")
        deck.add_slide(title="Revenue", layout="chart", chart={
            "type": "bar", "title": "Quarterly Revenue",
            "categories": ["Q1", "Q2", "Q3", "Q4"],
            "series": [{"name": "2025", "values": [120, 150, 180, 210]}],
        })
        deck.add_slide(title="Market Share", layout="chart", chart={
            "type": "pie", "title": "Market Share",
            "categories": ["Product A", "Product B", "Product C"],
            "series": [{"name": "Share", "values": [45, 35, 20]}],
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = PptxGenRenderer(tmpdir)
            result = await renderer.render(deck, "chart_test.pptx")
            self.assertTrue(result["success"])
            self.assertEqual(result["slides_count"], 2)
            self.assertTrue(os.path.exists(result["filepath"]))


if __name__ == "__main__":
    unittest.main()
