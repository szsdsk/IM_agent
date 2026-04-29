import unittest

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
        self.assertEqual(result["provider"], "local_mock")
        self.assertEqual(result["diagram_type"], "flow")


if __name__ == "__main__":
    unittest.main()
