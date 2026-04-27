import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """项目工具基类，直接以 LangChain StructuredTool 作为对外调用形态。"""

    def __init__(self, name: str, mock_mode: bool = True):
        self.name = name
        self.mock_mode = mock_mode
        self._logger = logging.getLogger(f"{__name__}.{name}")
        self._structured_tool = None

    def _log(self, level: str, message: str, extra: Optional[Dict] = None):
        log_data = {"tool": self.name, "message": message}
        if extra:
            log_data.update(extra)
        getattr(self._logger, level)(json.dumps(log_data, ensure_ascii=False))

    def _validate_input(self, data: Dict[str, Any], required_fields: list) -> bool:
        for field in required_fields:
            if field not in data:
                self._log("error", f"Missing required field: {field}")
                return False
        return True

    @property
    def langchain_tool(self):
        """缓存 StructuredTool，避免每次节点调用都重复构造 schema。"""
        if self._structured_tool is None:
            self._structured_tool = self._build_langchain_tool()
        return self._structured_tool

    async def ainvoke(self, tool_input: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """统一的工具调用入口，直接转发到 LangChain StructuredTool。"""
        return await self.langchain_tool.ainvoke(tool_input)

    @abstractmethod
    def _build_langchain_tool(self):
        pass
