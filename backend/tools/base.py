import json
import logging
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    def __init__(self, name: str, mock_mode: bool = True):
        self.name = name
        self.mock_mode = mock_mode
        self._logger = logging.getLogger(f"{__name__}.{name}")

    def _log(self, level: str, message: str, extra: Optional[Dict] = None):
        log_data = {"tool": self.name, "message": message}
        if extra:
            log_data.update(extra)
        getattr(self._logger, level)(json.dumps(log_data))

    def _validate_input(self, data: Dict[str, Any], required_fields: list) -> bool:
        for field in required_fields:
            if field not in data:
                self._log("error", f"Missing required field: {field}")
                return False
        return True

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        pass
