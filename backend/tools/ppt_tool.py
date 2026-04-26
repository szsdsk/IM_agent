"""
PPTTool - 演示稿生成工具
集成 DeckSpec 和 PptxGenJS 渲染器
"""
from typing import Dict, Any, List, Optional
import time
import os

from backend.tools.base import BaseTool
from backend.config import settings


class PPTTool(BaseTool):
    def __init__(self, mock_mode: bool = None):
        super().__init__("PPTTool", mock_mode if mock_mode is not None else settings.MOCK_MODE)
        self._output_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "slides"
        )
        os.makedirs(self._output_dir, exist_ok=True)

    def _download_url(self, filepath: str) -> str:
        """把本地 PPT 文件路径转换成浏览器可访问的下载地址。"""
        filename = os.path.basename(filepath)
        return f"/api/files/slides/{filename}"

    async def execute(
        self,
        action: str,
        task_id: str = None,
        slides: List[Dict] = None,
        title: str = None,
        slide_id: str = None,
        deck_spec: Dict = None,
        **kwargs
    ) -> Dict[str, Any]:
        self._log("info", f"PPT action: {action}", {"task_id": task_id})

        if not self._validate_input({"action": action}, ["action"]):
            return {"success": False, "error": "Missing required parameter: action"}

        if self.mock_mode:
            return await self._mock_execute(action, task_id, slides, title, slide_id)
        else:
            return await self._real_execute(action, task_id, slides, title, slide_id, deck_spec)

    async def _mock_execute(
        self,
        action: str,
        task_id: str,
        slides: List[Dict],
        title: str,
        slide_id: str
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
                "updated": True
            },
            "get_slides": {
                "success": True,
                "slides": slides or self._generate_mock_slides()
            },
            "export_markdown": {
                "success": True,
                "file_path": f"{self._output_dir}/mock_{int(time.time() * 1000)}.md"
            },
            "export_pdf": {
                "success": True,
                "file_path": f"{self._output_dir}/mock_{int(time.time() * 1000)}.pdf"
            }
        }

        return mock_responses.get(action, {"success": True, "action": action})

    async def _real_execute(
        self,
        action: str,
        task_id: str,
        slides: List[Dict],
        title: str,
        slide_id: str,
        deck_spec: Dict = None
    ) -> Dict[str, Any]:
        try:
            if action == "create_slides":
                return await self._create_pptx(task_id, title, slides, deck_spec)
            elif action == "update_slide":
                return await self._update_slide(slide_id, slides)
            elif action == "get_slides":
                return await self._get_slides(task_id)
            elif action == "export_markdown":
                return await self._export_markdown(title, slides, deck_spec)
            elif action == "export_pdf":
                return await self._export_pdf(title, slides, deck_spec)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            self._log("error", f"PPT action failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _create_pptx(
        self,
        task_id: str,
        title: str,
        slides: List[Dict],
        deck_spec: Dict = None
    ) -> Dict[str, Any]:
        self._log("info", f"Creating PPT for task {task_id}")

        if not slides and not deck_spec:
            slides = self._generate_mock_slides()

        # 优先使用 DeckSpec
        if deck_spec:
            return await self._render_with_deck_spec(deck_spec, task_id)

        # 使用 slides 列表
        if not slides:
            slides = self._generate_mock_slides()

        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt
            from pptx.enum.text import PP_ALIGN

            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)

            for slide_data in slides:
                layout = prs.slide_layouts[6]  # 空白布局
                slide = prs.slides.add_slide(layout)

                # 标题
                if slide_data.get("title"):
                    title_box = slide.shapes.add_textbox(
                        Inches(0.5), Inches(0.5), Inches(12.333), Inches(1)
                    )
                    tf = title_box.text_frame
                    p = tf.paragraphs[0]
                    p.text = slide_data["title"]
                    p.font.size = Pt(44)
                    p.font.bold = True
                    p.alignment = PP_ALIGN.CENTER

                # 内容（bullet points）
                bullets = slide_data.get("bullets", [])
                content = slide_data.get("content", "")
                items = bullets if bullets else (content.split("\n") if content else [])

                if items:
                    content_box = slide.shapes.add_textbox(
                        Inches(1), Inches(2), Inches(11.333), Inches(5)
                    )
                    tf = content_box.text_frame
                    for i, item in enumerate(items):
                        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                        p.text = f"• {str(item)}"
                        p.font.size = Pt(24)
                        p.space_after = Pt(12)

            filename = f"{task_id}_{int(time.time() * 1000)}.pptx"
            filepath = os.path.join(self._output_dir, filename)
            prs.save(filepath)

            return {
                "success": True,
                "slide_id": f"slide_{int(time.time() * 1000)}",
                "task_id": task_id,
                "title": title or "Presentation",
                "slides_count": len(slides),
                "file_path": filepath,
                "download_url": self._download_url(filepath),
            }

        except ImportError:
            self._log("warning", "python-pptx not available")
            return {
                "success": False,
                "error": "python-pptx not installed. Run: pip install python-pptx"
            }
        except Exception as e:
            self._log("error", f"PPTX creation failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _render_with_deck_spec(
        self,
        deck_spec: Dict,
        task_id: str
    ) -> Dict[str, Any]:
        """使用 DeckSpec 渲染"""
        try:
            from backend.services.deck_spec import DeckSpec
            from backend.services.deck_renderer import PptxGenRenderer

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

        except Exception as e:
            self._log("error", f"DeckSpec render failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _export_markdown(
        self,
        title: str,
        slides: List[Dict],
        deck_spec: Dict = None
    ) -> Dict[str, Any]:
        """导出为 Slidev Markdown"""
        try:
            from backend.services.deck_spec import DeckSpec, SlideSpec
            from backend.services.deck_renderer import SlidevRenderer

            if deck_spec:
                deck = DeckSpec.from_dict(deck_spec)
            else:
                deck = DeckSpec(title=title or "Presentation")
                for s in (slides or self._generate_mock_slides()):
                    deck.add_slide(
                        title=s.get("title", ""),
                        layout=s.get("layout", "content"),
                        bullets=s.get("bullets", []),
                    )

            renderer = SlidevRenderer(self._output_dir)
            filepath = renderer.render_to_file(deck)

            return {"success": True, "file_path": filepath}

        except Exception as e:
            self._log("error", f"Markdown export failed: {str(e)}")
            return {"success": False, "error": str(e)}

    async def _export_pdf(
        self,
        title: str,
        slides: List[Dict],
        deck_spec: Dict = None
    ) -> Dict[str, Any]:
        """导出为 PDF"""
        try:
            from backend.services.deck_spec import DeckSpec
            from backend.services.deck_renderer import SlidevRenderer, MarkdownToPdfRenderer

            if deck_spec:
                deck = DeckSpec.from_dict(deck_spec)
            else:
                deck = DeckSpec(title=title or "Presentation")
                for s in (slides or self._generate_mock_slides()):
                    deck.add_slide(title=s.get("title", ""), layout=s.get("layout", "content"))

            # 先生成 Markdown
            md_renderer = SlidevRenderer(self._output_dir)
            md_path = md_renderer.render_to_file(deck)

            # 再转 PDF
            pdf_renderer = MarkdownToPdfRenderer()
            result = await pdf_renderer.render(md_path)

            return result

        except Exception as e:
            self._log("error", f"PDF export failed: {str(e)}")
            return {"success": False, "error": str(e)}

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
            {"index": 2, "title": "执行计划", "layout": "content", "bullets": ["Phase 1", "Phase 2"]},
            {"index": 3, "title": "风险与待办", "layout": "content", "bullets": ["风险 1", "待办 1"]},
            {"index": 4, "title": "下一步", "layout": "content", "bullets": ["行动项"]},
        ]

    async def _simulate_delay(self, seconds: float):
        import asyncio
        await asyncio.sleep(seconds)
