from backend.tools.canvas_tool import CanvasTool
from backend.tools.doc_tool import DocTool
from backend.tools.im_tool import IMTool
from backend.tools.ppt_tool import PPTTool


class ToolFactory:
    _tools = {}

    @classmethod
    def get_tool(cls, tool_name: str):
        if tool_name not in cls._tools:
            if tool_name == "IMTool":
                cls._tools[tool_name] = IMTool()
            elif tool_name == "DocTool":
                cls._tools[tool_name] = DocTool()
            elif tool_name == "PPTTool":
                cls._tools[tool_name] = PPTTool()
            elif tool_name == "CanvasTool":
                cls._tools[tool_name] = CanvasTool()
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        return cls._tools[tool_name]

    @classmethod
    def get_langchain_tool(cls, tool_name: str):
        return cls.get_tool(tool_name).langchain_tool

    @classmethod
    async def invoke_tool(cls, tool_name: str, payload: dict):
        return await cls.get_tool(tool_name).ainvoke(payload)

    @classmethod
    def get_all_tools(cls):
        return {
            "IMTool": cls.get_tool("IMTool"),
            "DocTool": cls.get_tool("DocTool"),
            "PPTTool": cls.get_tool("PPTTool"),
            "CanvasTool": cls.get_tool("CanvasTool"),
        }

    @classmethod
    def get_all_langchain_tools(cls):
        return {
            "IMTool": cls.get_langchain_tool("IMTool"),
            "DocTool": cls.get_langchain_tool("DocTool"),
            "PPTTool": cls.get_langchain_tool("PPTTool"),
            "CanvasTool": cls.get_langchain_tool("CanvasTool"),
        }
