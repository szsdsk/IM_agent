from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.services.affine_service import affine_service
from backend.services.canvas_layout import normalize_canvas_artifact
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
            description="Create or update a local interactive canvas artifact.",
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

        try:
            if action == "create_canvas":
                return self._local_canvas_payload(
                    action=action,
                    task_id=task_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    title=title,
                    elements=elements,
                    nodes=nodes,
                    edges=edges,
                    layers=layers,
                    diagram_type="flow",
                )

            if action == "add_elements":
                if not canvas_id:
                    return {"success": False, "error": "Missing required parameter: canvas_id"}
                return self._local_canvas_payload(
                    action=action,
                    task_id=task_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    title=title,
                    elements=elements,
                    nodes=nodes,
                    edges=edges,
                    layers=layers,
                    diagram_type="flow",
                )

            if action == "create_flow_diagram":
                return self._local_canvas_payload(
                    action=action,
                    task_id=task_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    title=title,
                    elements=elements,
                    nodes=nodes,
                    edges=edges,
                    layers=layers,
                    diagram_type="flow",
                )

            if action == "create_architecture_diagram":
                return self._local_canvas_payload(
                    action=action,
                    task_id=task_id,
                    workspace_id=workspace_id,
                    canvas_id=canvas_id,
                    title=title,
                    elements=elements,
                    nodes=nodes,
                    edges=edges,
                    layers=layers,
                    diagram_type="architecture",
                )

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
        if action in {"create_canvas", "add_elements", "create_architecture_diagram", "create_flow_diagram"}:
            return self._local_canvas_payload(
                action=action,
                task_id=task_id,
                workspace_id=None,
                canvas_id=canvas_id,
                title=title,
                elements=elements,
                nodes=nodes,
                edges=edges,
                layers=layers,
                diagram_type="architecture" if action == "create_architecture_diagram" else "flow",
            )
        return {"success": False, "provider": "local_canvas", "error": f"Unknown action: {action}"}

    def _local_canvas_payload(
        self,
        action: str,
        task_id: Optional[str],
        workspace_id: Optional[str],
        canvas_id: Optional[str],
        title: Optional[str],
        elements: Optional[List[Dict[str, Any]]],
        nodes: Optional[List[Dict[str, Any]]],
        edges: Optional[List[Dict[str, Any]]],
        layers: Optional[List[List[str]]],
        diagram_type: str,
    ) -> Dict[str, Any]:
        """本地画布始终可用；AFFiNE 只作为后续同步状态，不阻塞 Demo。"""
        resolved_workspace_id = workspace_id or f"ws_{task_id or 'local'}"
        resolved_canvas_id = canvas_id or f"canvas_{task_id or 'local'}"
        payload = normalize_canvas_artifact(
            title=title or "Agent-Pilot 画布",
            diagram_type=diagram_type,
            task_id=task_id,
            workspace_id=resolved_workspace_id,
            canvas_id=resolved_canvas_id,
            nodes=nodes or [],
            edges=edges or [],
            layers=layers or [],
            elements=elements or [],
            provider=self._provider(),
            url=self._canvas_url(workspace_id, canvas_id),
            affine_configured=affine_service.is_configured,
        )
        if action == "add_elements":
            payload["elements_added"] = len(elements or [])
        return payload

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
        return "local_canvas"

    def _canvas_url(self, workspace_id: Optional[str], canvas_id: Optional[str]) -> Optional[str]:
        if not affine_service.is_configured or not workspace_id or not canvas_id:
            return None
        return f"{settings.AFFINE_URL.rstrip('/')}/workspace/{workspace_id}/canvas/{canvas_id}"
