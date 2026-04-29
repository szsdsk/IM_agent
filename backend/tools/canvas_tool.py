from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.services.affine_service import affine_service
from backend.tools.base import BaseTool


class CanvasToolInput(BaseModel):
    action: str = Field(description="Canvas action, such as create_canvas, add_elements, create_flow_diagram, or create_architecture_diagram.")
    task_id: Optional[str] = None
    workspace_id: Optional[str] = None
    canvas_id: Optional[str] = None
    title: Optional[str] = None
    elements: Optional[List[Dict[str, Any]]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    layers: Optional[List[List[str]]] = None


class CanvasTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("CanvasTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)

    def _build_langchain_tool(self):
        from langchain_core.tools import StructuredTool

        return StructuredTool.from_function(
            name="canvas_tool",
            description="Create or update an AFFiNE canvas artifact.",
            coroutine=self._run,
            args_schema=CanvasToolInput,
        )

    async def _run(
        self,
        action: str,
        task_id: str = None,
        workspace_id: str = None,
        canvas_id: str = None,
        title: str = None,
        elements: List[Dict[str, Any]] = None,
        nodes: List[Dict[str, Any]] = None,
        edges: List[Dict[str, Any]] = None,
        layers: List[List[str]] = None,
    ) -> Dict[str, Any]:
        self._log("info", f"Canvas action: {action}", {"task_id": task_id, "canvas_id": canvas_id})
        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}
        if self.mock_mode:
            return self._mock_run(action, task_id, canvas_id, title, elements, nodes, edges, layers)

        try:
            if action == "create_canvas":
                workspace_id = await self._ensure_workspace(workspace_id, task_id)
                created = await affine_service.create_canvas(workspace_id, title or "Agent-Pilot Canvas")
                return self._with_canvas_payload(created, workspace_id, title)

            if action == "add_elements":
                if not canvas_id:
                    return {"success": False, "error": "Missing required parameter: canvas_id"}
                result = await affine_service.add_canvas_elements(canvas_id, elements or [])
                return {**result, "provider": self._provider(), "elements": elements or []}

            if action == "create_flow_diagram":
                workspace_id = await self._ensure_workspace(workspace_id, task_id)
                canvas = await self._ensure_canvas(workspace_id, canvas_id, title)
                flow_edges = [
                    {
                        "from": edge.get("from") or edge.get("source"),
                        "to": edge.get("to") or edge.get("target"),
                        "label": edge.get("label", ""),
                    }
                    for edge in (edges or [])
                ]
                result = await affine_service.create_flow_diagram(
                    canvas["canvas_id"],
                    title or "流程图",
                    nodes or [],
                    flow_edges,
                )
                return {
                    **result,
                    **canvas,
                    "provider": self._provider(),
                    "diagram_type": "flow",
                    "nodes": nodes or [],
                    "edges": edges or [],
                }

            if action == "create_architecture_diagram":
                workspace_id = await self._ensure_workspace(workspace_id, task_id)
                canvas = await self._ensure_canvas(workspace_id, canvas_id, title)
                result = await affine_service.create_architecture_diagram(canvas["canvas_id"], layers or [])
                return {
                    **result,
                    **canvas,
                    "provider": self._provider(),
                    "diagram_type": "architecture",
                    "layers": layers or [],
                }

            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            self._log("error", f"Canvas action failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    def _mock_run(
        self,
        action: str,
        task_id: Optional[str],
        canvas_id: Optional[str],
        title: Optional[str],
        elements: Optional[List[Dict[str, Any]]],
        nodes: Optional[List[Dict[str, Any]]],
        edges: Optional[List[Dict[str, Any]]],
        layers: Optional[List[List[str]]],
    ) -> Dict[str, Any]:
        mock_canvas_id = canvas_id or f"canvas_{task_id or 'local'}"
        payload = {
            "success": True,
            "provider": "local_mock",
            "workspace_id": f"ws_{task_id or 'local'}",
            "canvas_id": mock_canvas_id,
            "title": title or "Agent-Pilot Canvas",
            "url": None,
        }
        if action == "create_canvas":
            return payload
        if action == "add_elements":
            return {**payload, "elements_added": len(elements or []), "elements": elements or []}
        if action == "create_architecture_diagram":
            return {**payload, "diagram_type": "architecture", "layers": layers or []}
        if action == "create_flow_diagram":
            return {**payload, "diagram_type": "flow", "nodes": nodes or [], "edges": edges or []}
        return {"success": False, "provider": "local_mock", "error": f"Unknown action: {action}"}

    async def _ensure_workspace(self, workspace_id: Optional[str], task_id: Optional[str]) -> str:
        if workspace_id:
            return workspace_id
        result = await affine_service.create_workspace(f"Agent-Pilot {task_id or 'Workspace'}")
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return result.get("workspace_id") or result.get("id") or data.get("id") or f"ws_{task_id or 'local'}"

    async def _ensure_canvas(self, workspace_id: str, canvas_id: Optional[str], title: Optional[str]) -> Dict[str, Any]:
        if canvas_id:
            return {
                "success": True,
                "workspace_id": workspace_id,
                "canvas_id": canvas_id,
                "title": title or "Agent-Pilot Canvas",
                "url": self._canvas_url(workspace_id, canvas_id),
            }
        created = await affine_service.create_canvas(workspace_id, title or "Agent-Pilot Canvas")
        return self._with_canvas_payload(created, workspace_id, title)

    def _with_canvas_payload(self, result: Dict[str, Any], workspace_id: str, title: Optional[str]) -> Dict[str, Any]:
        canvas_id = result.get("canvas_id") or result.get("id")
        return {
            **result,
            "success": result.get("success", True),
            "provider": self._provider(),
            "workspace_id": workspace_id,
            "canvas_id": canvas_id,
            "title": title or result.get("name") or "Agent-Pilot Canvas",
            "url": self._canvas_url(workspace_id, canvas_id),
        }

    def _provider(self) -> str:
        return "affine" if affine_service.is_configured and not self.mock_mode else "local_mock"

    def _canvas_url(self, workspace_id: Optional[str], canvas_id: Optional[str]) -> Optional[str]:
        if not affine_service.is_configured or not workspace_id or not canvas_id:
            return None
        return f"{settings.AFFINE_URL.rstrip('/')}/workspace/{workspace_id}/canvas/{canvas_id}"
