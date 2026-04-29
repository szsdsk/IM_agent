import os
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.config import settings
from backend.tools.base import BaseTool


class PPTToolInput(BaseModel):
    action: str = Field(description="PPT action, such as create_slides, update_slide, get_slides, export_markdown, or export_pdf.")
    task_id: Optional[str] = None
    slides: Optional[List[Dict[str, Any]]] = None
    title: Optional[str] = None
    slide_id: Optional[str] = None
    deck_spec: Optional[Dict[str, Any]] = None


class PPTTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("PPTTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)
        self._output_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "slides"
        )
        os.makedirs(self._output_dir, exist_ok=True)


    @staticmethod
    def _apply_template_profile(deck) -> None:
        profile = (deck.metadata or {}).get("template_profile") or (deck.metadata or {}).get("presentation_scene")
        template_map = {
            "management_briefing": {"theme": "business_blue", "title_prefix": "管理汇报"},
            "project_review": {"theme": "tech_dark", "title_prefix": "项目评审"},
            "proposal_pitch": {"theme": "minimal", "title_prefix": "方案提案"},
            "postmortem": {"theme": "tech_dark", "title_prefix": "复盘总结"},
            "training": {"theme": "minimal", "title_prefix": "培训讲解"},
        }
        template = template_map.get(profile or "", {"theme": deck.theme, "title_prefix": ""})
        if not deck.theme:
            deck.theme = template["theme"]
        elif profile in template_map:
            deck.theme = template["theme"]
        if template["title_prefix"] and deck.slides:
            first_slide = deck.slides[0]
            if not any(prefix in (first_slide.title or "") for prefix in ["管理汇报", "项目评审", "方案提案", "复盘总结", "培训讲解"]):
                first_slide.title = f"{template['title_prefix']} · {first_slide.title}"


    def _build_langchain_tool(self):
        from langchain_core.tools import StructuredTool

        return StructuredTool.from_function(
            name="ppt_tool",
            description="Create, update, export, or read an Agent-Pilot PPT artifact.",
            coroutine=self._run,
            args_schema=PPTToolInput,
        )

    def _download_url(self, filepath: str) -> str:
        """把本地 PPT 文件路径转换成浏览器可访问的下载地址。"""
        filename = os.path.basename(filepath)
        return f"/api/files/slides/{filename}"

    async def _run(
        self,
        action: str,
        task_id: str = None,
        slides: List[Dict] = None,
        title: str = None,
        slide_id: str = None,
        deck_spec: Dict = None,
    ) -> Dict[str, Any]:
        self._log("info", f"PPT action: {action}", {"task_id": task_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_run(action, task_id, slides, title, slide_id)
        return await self._real_run(action, task_id, slides, title, slide_id, deck_spec)

    async def _mock_run(
        self,
        action: str,
        task_id: str,
        slides: List[Dict],
        title: str,
        slide_id: str,
    ) -> Dict[str, Any]:
        await self._simulate_delay(0.5)
        self._log("info", f"Mock PPT action executed: {action}")

        mock_responses = {
            "create_slides": {
                "success": True,
                "slide_id": f"slide_{int(time.time() * 1000)}",
                "task_id": task_id,
                "title": title or "Presentation",
                "slides_count": len(slides) if slides else 5,
                "file_path": None,
                "download_url": None,
            },
            "update_slide": {
                "success": True,
                "slide_id": slide_id,
                "updated": True,
            },
            "get_slides": {
                "success": True,
                "slides": slides or self._generate_mock_slides(),
            },
            "export_markdown": {
                "success": True,
                "file_path": f"{self._output_dir}/mock_{int(time.time() * 1000)}.md",
            },
            "export_pdf": {
                "success": True,
                "file_path": f"{self._output_dir}/mock_{int(time.time() * 1000)}.pdf",
            },
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_run(
        self,
        action: str,
        task_id: str,
        slides: List[Dict],
        title: str,
        slide_id: str,
        deck_spec: Dict = None,
    ) -> Dict[str, Any]:
        try:
            if action == "create_slides":
                return await self._create_pptx(task_id, title, slides, deck_spec)
            if action == "update_slide":
                return await self._update_slide(slide_id, slides)
            if action == "get_slides":
                return await self._get_slides(task_id)
            if action == "export_markdown":
                return await self._export_markdown(title, slides, deck_spec)
            if action == "export_pdf":
                return await self._export_pdf(title, slides, deck_spec)
            return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as exc:
            self._log("error", f"PPT action failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _create_pptx(
        self,
        task_id: str,
        title: str,
        slides: List[Dict],
        deck_spec: Dict = None,
    ) -> Dict[str, Any]:
        self._log("info", f"Creating PPT for task {task_id}")

        # Always use DeckSpec + PptxGenRenderer for themed output
        try:
            from backend.services.deck_renderer import PptxGenRenderer
            from backend.services.deck_spec import DeckSpec, SlideSpec

            if deck_spec:
                deck = DeckSpec.from_dict(deck_spec)
            else:
                if not slides:
                    slides = self._generate_mock_slides()
                deck = DeckSpec(title=title or "Presentation")
                for s in slides:
                    deck.add_slide(
                        title=s.get("title", ""),
                        layout=s.get("layout", "content"),
                        bullets=s.get("bullets", []),
                    )

            self._apply_template_profile(deck)

            renderer = PptxGenRenderer(self._output_dir)
            result = await renderer.render(deck, filename=f"{task_id}.pptx")

            if result.get("success"):
                return {
                    "success": True,
                    "slide_id": f"slide_{int(time.time() * 1000)}",
                    "task_id": task_id,
                    "title": deck.title,
                    "slides_count": len(deck.slides),
                    "file_path": result["filepath"],
                    "download_url": self._download_url(result["filepath"]),
                }
            return result

        except ImportError:
            self._log("warning", "python-pptx not available")
            return {
                "success": False,
                "error": "python-pptx not installed. Run: python -m pip install python-pptx",
            }
        except Exception as exc:
            self._log("error", f"PPTX creation failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _render_with_deck_spec(self, deck_spec: Dict, task_id: str) -> Dict[str, Any]:
        try:
            from backend.services.deck_renderer import PptxGenRenderer
            from backend.services.deck_spec import DeckSpec

            deck = DeckSpec.from_dict(deck_spec)
            renderer = PptxGenRenderer(self._output_dir)
            result = await renderer.render(deck, filename=f"{task_id}.pptx")

            if result.get("success"):
                return {
                    "success": True,
                    "slide_id": f"slide_{int(time.time() * 1000)}",
                    "task_id": task_id,
                    "title": deck.title,
                    "slides_count": len(deck.slides),
                    "file_path": result["filepath"],
                    "download_url": self._download_url(result["filepath"]),
                }
            return result

        except Exception as exc:
            self._log("error", f"DeckSpec render failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _export_markdown(self, title: str, slides: List[Dict], deck_spec: Dict = None) -> Dict[str, Any]:
        try:
            from backend.services.deck_renderer import SlidevRenderer
            from backend.services.deck_spec import DeckSpec

            if deck_spec:
                deck = DeckSpec.from_dict(deck_spec)
            else:
                deck = DeckSpec(title=title or "Presentation")
                for slide in (slides or self._generate_mock_slides()):
                    deck.add_slide(
                        title=slide.get("title", ""),
                        layout=slide.get("layout", "content"),
                        bullets=slide.get("bullets", []),
                    )

            renderer = SlidevRenderer(self._output_dir)
            filepath = renderer.render_to_file(deck)

            return {"success": True, "file_path": filepath}

        except Exception as exc:
            self._log("error", f"Markdown export failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _export_pdf(self, title: str, slides: List[Dict], deck_spec: Dict = None) -> Dict[str, Any]:
        try:
            from backend.services.deck_renderer import MarkdownToPdfRenderer, SlidevRenderer
            from backend.services.deck_spec import DeckSpec

            if deck_spec:
                deck = DeckSpec.from_dict(deck_spec)
            else:
                deck = DeckSpec(title=title or "Presentation")
                for slide in (slides or self._generate_mock_slides()):
                    deck.add_slide(title=slide.get("title", ""), layout=slide.get("layout", "content"))

            md_renderer = SlidevRenderer(self._output_dir)
            md_path = md_renderer.render_to_file(deck)

            pdf_renderer = MarkdownToPdfRenderer()
            return await pdf_renderer.render(md_path)

        except Exception as exc:
            self._log("error", f"PDF export failed: {str(exc)}")
            return {"success": False, "error": str(exc)}

    async def _update_slide(self, slide_id: str, slides: List[Dict]) -> Dict[str, Any]:
        self._log("info", f"Updating slide {slide_id}")
        return {"success": True, "slide_id": slide_id, "updated": True}

    async def _get_slides(self, task_id: str) -> Dict[str, Any]:
        self._log("info", f"Getting slides for task {task_id}")
        return {"success": True, "slides": []}

    def _generate_mock_slides(self) -> List[Dict]:
        return [
            {"index": 0, "title": "封面", "layout": "title", "bullets": []},
            {"index": 1, "title": "背景与目标", "layout": "content", "bullets": ["目标 1", "目标 2"]},
            {"index": 2, "title": "核心方案", "layout": "two_column", "bullets": ["方案 A: 快速迭代", "方案 B: 稳步推进", "优势: 低风险", "优势: 全面覆盖"]},
            {"index": 3, "title": "技术架构", "layout": "diagram", "bullets": []},
            {"index": 4, "title": "风险与待办", "layout": "content", "bullets": ["风险 1", "待办 1"]},
            {"index": 5, "title": "下一步", "layout": "content", "bullets": ["行动项"]},
        ]

    async def _simulate_delay(self, seconds: float):
        import asyncio

        await asyncio.sleep(seconds)
