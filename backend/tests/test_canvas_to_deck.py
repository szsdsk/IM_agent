import unittest

from backend.services.canvas_to_deck import build_canvas_linked_deck, build_canvas_summary_slide


class CanvasToDeckTests(unittest.TestCase):
    def test_canvas_summary_slide_uses_nodes_and_edges(self):
        slide = build_canvas_summary_slide({
            "canvas_id": "canvas_1",
            "title": "知识库问答架构",
            "diagram_type": "flow",
            "nodes": [
                {"id": "n1", "text": "用户提问", "description": "接收问题"},
                {"id": "n2", "text": "检索知识库", "description": "召回相关文档"},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
            "metadata": {"version": 3},
        })

        self.assertEqual(slide["layout"], "process")
        self.assertEqual(slide["diagram_ref"], "canvas:canvas_1")
        self.assertIn("用户提问", slide["bullets"][0])
        self.assertEqual(slide["canvas_sync"]["canvas_version"], 3)

    def test_canvas_slide_is_inserted_after_cover(self):
        deck = build_canvas_linked_deck(
            {
                "title": "项目评审",
                "slides": [
                    {"index": 0, "title": "封面", "layout": "hero"},
                    {"index": 1, "title": "目标", "layout": "content"},
                ],
            },
            {"canvas_id": "canvas_2", "title": "系统画布", "nodes": [{"id": "n1", "text": "前端"}]},
        )

        self.assertEqual(deck["slides"][1]["diagram_ref"], "canvas:canvas_2")
        self.assertEqual(deck["slides"][2]["title"], "目标")
        self.assertEqual(deck["metadata"]["linked_canvas_id"], "canvas_2")

    def test_existing_canvas_slide_is_replaced(self):
        deck = build_canvas_linked_deck(
            {
                "title": "项目评审",
                "slides": [
                    {"index": 0, "title": "封面"},
                    {"index": 1, "title": "旧画布", "diagram_ref": "canvas:canvas_3"},
                    {"index": 2, "title": "下一页"},
                ],
            },
            {
                "canvas_id": "canvas_3",
                "title": "新版画布",
                "nodes": [{"id": "n1", "text": "服务层", "description": "处理业务逻辑"}],
            },
        )

        self.assertEqual(len(deck["slides"]), 3)
        self.assertEqual(deck["slides"][1]["title"], "新版画布：结构说明")
        self.assertEqual(deck["slides"][2]["index"], 2)


if __name__ == "__main__":
    unittest.main()
