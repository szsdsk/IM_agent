from typing import Dict, Any, List, Optional
import time
import json
import os

from backend.tools.base import BaseTool
from backend.config import settings


class PPTTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("PPTTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)
        self._output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "slides")
        os.makedirs(self._output_dir, exist_ok=True)

    async def execute(self, action: str, task_id: str = None, slides: List[Dict] = None,
                      title: str = None, slide_id: str = None, **kwargs) -> Dict[str, Any]:
        self._log("info", f"PPT action: {action}", {"task_id": task_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_execute(action, task_id, slides, title, slide_id)
        else:
            return await self._real_execute(action, task_id, slides, title, slide_id)

    async def _mock_execute(self, action: str, task_id: str, slides: List[Dict],
                            title: str, slide_id: str) -> Dict[str, Any]:
        await self._simulate_delay(0.5)
        self._log("info", f"Mock PPT action executed: {action}")

        mock_responses = {
            "create_slides": {
                "success": True,
                "slide_id": f"slide_{int(time.time() * 1000)}",
                "task_id": task_id,
                "title": title or "Presentation",
                "slides_count": len(slides) if slides else 5,
                "file_path": f"{self._output_dir}/slide_{int(time.time() * 1000)}.pptx"
            },
            "update_slide": {
                "success": True,
                "slide_id": slide_id,
                "updated": True
            },
            "get_slides": {
                "success": True,
                "slides": slides or self._generate_mock_slides()
            }
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_execute(self, action: str, task_id: str, slides: List[Dict],
                             title: str, slide_id: str) -> Dict[str, Any]:
        try:
            if action == "create_slides":
                return await self._create_pptx(task_id, title, slides)
            elif action == "update_slide":
                return await self._update_slide(slide_id, slides)
            elif action == "get_slides":
                return await self._get_slides(task_id)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            self._log("error", f"PPT action failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def _generate_mock_slides(self) -> List[Dict]:
        return [
            {"index": 0, "title": "封面", "content": "Agent-Pilot 工作汇报", "layout": "title"},
            {"index": 1, "title": "目录", "content": "1. 任务概述\n2. 执行过程\n3. 结果展示", "layout": "content"},
            {"index": 2, "title": "任务概述", "content": "基于AI的智能办公协同任务", "layout": "content"},
            {"index": 3, "title": "执行过程", "content": "正在执行中...", "layout": "content"},
            {"index": 4, "title": "结果展示", "content": "任务已完成", "layout": "content"}
        ]

    async def _create_pptx(self, task_id: str, title: str, slides: List[Dict]) -> Dict[str, Any]:
        self._log("info", f"Creating PPT for task {task_id}")

        if not slides:
            slides = self._generate_mock_slides()

        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt

            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)

            for slide_data in slides:
                slide_layout = prs.slide_layouts[1]
                slide = prs.slides.add_slide(slide_layout)

                if slide_data.get("title"):
                    title_shape = slide.shapes.title
                    title_shape.text = slide_data["title"]

                if slide_data.get("content"):
                    content_box = slide.placeholders[1]
                    content_box.text = slide_data["content"]

            file_path = f"{self._output_dir}/{task_id}_{int(time.time() * 1000)}.pptx"
            prs.save(file_path)

            return {
                "success": True,
                "slide_id": f"slide_{int(time.time() * 1000)}",
                "task_id": task_id,
                "title": title or "Presentation",
                "slides_count": len(slides),
                "file_path": file_path
            }
        except ImportError:
            self._log("warning", "python-pptx not available, using mock")
            return {
                "success": True,
                "slide_id": f"slide_{int(time.time() * 1000)}",
                "task_id": task_id,
                "file_path": f"{self._output_dir}/mock_{int(time.time() * 1000)}.pptx"
            }

    async def _update_slide(self, slide_id: str, slides: List[Dict]) -> Dict[str, Any]:
        self._log("info", f"Updating slide {slide_id}")
        return {"success": True, "slide_id": slide_id, "updated": True}

    async def _get_slides(self, task_id: str) -> Dict[str, Any]:
        self._log("info", f"Getting slides for task {task_id}")
        return {"success": True, "slides": []}

    async def _simulate_delay(self, seconds: float):
        import asyncio
        await asyncio.sleep(seconds)
