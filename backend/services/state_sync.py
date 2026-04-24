import json
import logging
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


class WebSocketMessage:
    def __init__(self, msg_type: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        self.type = msg_type
        self.timestamp = datetime.utcnow().isoformat()
        self.data = data or {}
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self) -> Dict[str, Any]:
        result = {"type": self.type, "timestamp": self.timestamp}
        if self.data:
            result.update(self.data)
        for key in ["type", "timestamp"]:
            if hasattr(self, key):
                result[key] = getattr(self, key)
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class SyncMessage:
    @staticmethod
    def task_progress(task_id: str, step: str, progress: float,
                      message: str = "", status: str = "running") -> Dict[str, Any]:
        return {
            "type": "task.progress",
            "task_id": task_id,
            "step": step,
            "message": message,
            "progress": progress,
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }

    @staticmethod
    def task_completed(task_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "task.completed",
            "task_id": task_id,
            "result": result,
            "status": "completed",
            "updated_at": datetime.utcnow().isoformat()
        }

    @staticmethod
    def task_failed(task_id: str, error: str) -> Dict[str, Any]:
        return {
            "type": "task.failed",
            "task_id": task_id,
            "error": error,
            "status": "failed",
            "updated_at": datetime.utcnow().isoformat()
        }

    @staticmethod
    def session_sync(session_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "session.sync",
            "session_id": session_id,
            "state": state,
            "updated_at": datetime.utcnow().isoformat()
        }

    @staticmethod
    def agent_message(session_id: str, task_id: str, content: str,
                      sender: str = "agent") -> Dict[str, Any]:
        return {
            "type": "agent.message",
            "session_id": session_id,
            "task_id": task_id,
            "content": content,
            "sender": sender,
            "timestamp": datetime.utcnow().isoformat()
        }


class StateCenter:
    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {}

    def get_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._states.get(session_id)

    def update_state(self, session_id: str, task_id: str, state: Dict[str, Any]):
        if session_id not in self._states:
            self._states[session_id] = {
                "session_id": session_id,
                "tasks": {},
                "last_updated": datetime.utcnow().isoformat()
            }

        self._states[session_id]["tasks"][task_id] = state
        self._states[session_id]["last_updated"] = datetime.utcnow().isoformat()

    def sync_state(self, session_id: str, task_id: str, updates: Dict[str, Any]):
        if session_id not in self._states:
            self.update_state(session_id, task_id, {})
        else:
            if task_id not in self._states[session_id]["tasks"]:
                self._states[session_id]["tasks"][task_id] = {}
            self._states[session_id]["tasks"][task_id].update(updates)
            self._states[session_id]["last_updated"] = datetime.utcnow().isoformat()

    def get_full_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        if session_id not in self._states:
            return None
        return {
            "session_id": session_id,
            "tasks": self._states[session_id]["tasks"],
            "last_updated": self._states[session_id]["last_updated"]
        }


state_center = StateCenter()
