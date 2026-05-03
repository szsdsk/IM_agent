import unittest

from backend.services.lark_bot_service import build_progress_card, markdown_to_lark_blocks
from backend.tools.doc_tool import DocTool
from backend.tools.canvas_tool import CanvasTool
from backend.tools.ppt_tool import PPTTool
from backend.tools.tool_factory import ToolFactory


class LangChainToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_doc_tool_structured_tool_create_doc(self):
        tool = DocTool(mock_mode=True)

        result = await tool.ainvoke({
            "action": "create_doc",
            "task_id": "task_1",
            "title": "测试文档",
            "content": "正文",
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["title"], "测试文档")

    async def test_ppt_tool_structured_tool_create_slides(self):
        tool = PPTTool(mock_mode=True)

        result = await tool.ainvoke({
            "action": "create_slides",
            "task_id": "task_1",
            "title": "测试 PPT",
            "slides": [{"title": "第一页", "content": "内容"}],
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["slides_count"], 1)

    async def test_tool_factory_invokes_langchain_tool(self):
        ToolFactory._tools = {"DocTool": DocTool(mock_mode=True)}
        ToolFactory._langchain_tools = {}

        result = await ToolFactory.invoke_tool(
            "DocTool",
            {
                "action": "create_doc",
                "task_id": "task_2",
                "title": "工厂调用",
                "content": "正文",
            },
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["title"], "工厂调用")

    async def test_canvas_tool_mock_flow_diagram(self):
        tool = CanvasTool(mock_mode=True)

        result = await tool.ainvoke({
            "action": "create_flow_diagram",
            "task_id": "task_canvas",
            "title": "流程图",
            "nodes": [
                {"id": "n1", "text": "开始", "type": "start"},
                {"id": "n2", "text": "交付", "type": "process"},
            ],
            "edges": [{"source": "n1", "target": "n2"}],
        })

        self.assertTrue(result["success"])
        self.assertEqual(result["provider"], "local_canvas")
        self.assertEqual(result["diagram_type"], "flow")
        self.assertTrue(result["exportable"])
        self.assertGreater(len(result["elements"]), 0)

    async def test_markdown_to_lark_blocks_uses_supported_block_types(self):
        # 飞书 Docx OpenAPI 不支持 block_type=16；列表和引用块要使用当前可写入的类型。
        blocks = markdown_to_lark_blocks("- 要点\n> 引用\n---")

        self.assertEqual(blocks[0]["block_type"], 12)
        self.assertEqual(blocks[1]["block_type"], 15)
        self.assertEqual(blocks[2], {"block_type": 22, "divider": {}})

    async def test_lark_progress_card_uses_safe_components(self):
        # 进度卡片只使用飞书交互卡片的基础组件，避免 progress_bar 在部分租户中校验失败。
        card = build_progress_card("task_1", "generate_slides", 0.75)

        tags = [element.get("tag") for element in card["elements"]]
        self.assertIn("div", tags)
        self.assertNotIn("progress_bar", tags)
        self.assertIn("75%", card["elements"][0]["text"]["content"])


if __name__ == "__main__":
    unittest.main()
