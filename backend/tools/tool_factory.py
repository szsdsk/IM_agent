from backend.tools.im_tool import IMTool
from backend.tools.doc_tool import DocTool
from backend.tools.ppt_tool import PPTTool
from backend.tools.lark_tool import LarkTool
from backend.config import settings


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
            elif tool_name == "LarkTool":
                cls._tools[tool_name] = LarkTool()
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        return cls._tools[tool_name]

    @classmethod
    def get_all_tools(cls):
        return {
            "IMTool": cls.get_tool("IMTool"),
            "DocTool": cls.get_tool("DocTool"),
            "PPTTool": cls.get_tool("PPTTool"),
            "LarkTool": cls.get_tool("LarkTool")
        }
