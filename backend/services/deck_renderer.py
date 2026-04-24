from __future__ import annotations
"""
Deck Renderer - PPT 渲染器
DeckSpec -> Slidev Markdown / PptxGenJS
"""
import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from backend.services.deck_spec import DeckSpec, SlideSpec

logger = logging.getLogger(__name__)


class SlidevRenderer:
    """Slidev Markdown 渲染器"""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or "./data/slides"
        os.makedirs(self.output_dir, exist_ok=True)

    def render(self, deck: DeckSpec) -> str:
        """将 DeckSpec 渲染为 Slidev Markdown"""
        lines = [
            "---",
            f"title: {deck.title}",
            f"author: Agent-Pilot",
            "transition: fade",
            "theme: default",
            "---",
            "",
        ]

        for slide in deck.slides:
            lines.extend(self._render_slide(slide))
            lines.append("")

        return "\n".join(lines)

    def _render_slide(self, slide: SlideSpec) -> list:
        """渲染单页幻灯片"""
        lines = []

        if slide.layout == "title":
            lines.extend([
                f"# {slide.title}",
                "",
                f"<!-- slide {slide.index + 1} -->",
            ])
        elif slide.layout == "content":
            lines.extend([
                f"## {slide.title}",
                "",
            ])
            for bullet in slide.bullets:
                lines.append(f"- {bullet}")
            lines.append("")
        elif slide.layout == "two_column":
            lines.extend([
                f"## {slide.title}",
                "",
                "<div style='display: flex; gap: 2rem;'>",
                "<div>",
            ])
            mid = len(slide.bullets) // 2
            for bullet in slide.bullets[:mid]:
                lines.append(f"- {bullet}")
            lines.extend([
                "</div>",
                "<div>",
            ])
            for bullet in slide.bullets[mid:]:
                lines.append(f"- {bullet}")
            lines.extend([
                "</div>",
                "</div>",
            ])
        elif slide.layout == "diagram":
            lines.extend([
                f"## {slide.title}",
                "",
                ":::diagram",
                f"![Diagram]({slide.diagram_ref or ''})",
                ":::",
            ])
        elif slide.layout == "image":
            lines.extend([
                f"## {slide.title}",
                "",
                f"![{slide.title}]({slide.image_ref or ''})",
            ])

        # 演讲者备注
        if slide.speaker_notes:
            lines.append("")
            lines.append(f"// {slide.speaker_notes}")

        return lines

    def render_to_file(self, deck: DeckSpec, filename: str = None) -> str:
        """渲染并保存为 Markdown 文件"""
        if filename is None:
            filename = f"{deck.title.replace(' ', '_')}_{int(__import__('time').time())}.md"

        path = os.path.join(self.output_dir, filename)
        content = self.render(deck)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Slidev markdown saved to {path}")
        return path


class PptxGenRenderer:
    """PptxGenJS / python-pptx 渲染器"""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or "./data/slides"
        os.makedirs(self.output_dir, exist_ok=True)

    async def render(self, deck: DeckSpec, filename: str = None) -> Dict[str, Any]:
        """将 DeckSpec 渲染为 PPTX"""
        if filename is None:
            filename = f"{deck.title.replace(' ', '_')}.pptx"

        filepath = os.path.join(self.output_dir, filename)

        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN
        except ImportError:
            logger.warning("python-pptx not installed")
            return {"success": False, "error": "python-pptx not installed"}

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        for slide_spec in deck.slides:
            self._add_slide(prs, slide_spec)

        prs.save(filepath)

        return {
            "success": True,
            "filepath": filepath,
            "slides_count": len(deck.slides),
            "title": deck.title,
        }

    def _add_slide(self, prs: Presentation, slide: SlideSpec):
        """添加单页幻灯片"""
        # 选择布局
        if slide.layout == "title":
            layout = prs.slide_layouts[6]  # 空白
        else:
            layout = prs.slide_layouts[6]  # 空白

        slide_obj = prs.slides.add_slide(layout)

        # 标题
        left = Inches(0.5)
        top = Inches(0.5)
        width = Inches(12.333)
        height = Inches(1)

        title_box = slide_obj.shapes.add_textbox(left, top, width, height)
        title_frame = title_box.text_frame
        title_para = title_frame.paragraphs[0]
        title_para.text = slide.title
        title_para.font.size = Pt(44)
        title_para.font.bold = True
        title_para.alignment = PP_ALIGN.CENTER

        # 内容
        if slide.bullets:
            left = Inches(1)
            top = Inches(2)
            width = Inches(11.333)
            height = Inches(5)

            content_box = slide_obj.shapes.add_textbox(left, top, width, height)
            content_frame = content_box.text_frame

            for i, bullet in enumerate(slide.bullets):
                if i == 0:
                    para = content_frame.paragraphs[0]
                else:
                    para = content_frame.add_paragraph()

                para.text = f"• {bullet}"
                para.font.size = Pt(24)
                para.space_after = Pt(12)

        # 演讲者备注
        if slide.speaker_notes:
            notes_slide = slide_obj.notes_slide
            notes_slide.notes_text_frame.text = slide.speaker_notes


class MarkdownToPdfRenderer:
    """Markdown 转 PDF（通过 Slidev）"""

    def __init__(self, slidev_path: str = None):
        self.slidev_path = slidev_path or "slidev"

    async def render(self, markdown_path: str, output_path: str = None) -> Dict[str, Any]:
        """将 Markdown 转换为 PDF"""
        if output_path is None:
            output_path = markdown_path.replace(".md", ".pdf")

        try:
            import subprocess
            result = subprocess.run(
                [self.slidev_path, "export", markdown_path, "--format", "pdf", "--output", output_path],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                return {"success": True, "filepath": output_path}
            else:
                return {"success": False, "error": result.stderr}

        except FileNotFoundError:
            return {"success": False, "error": "Slidev not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# 全局渲染器实例
slidev_renderer = SlidevRenderer()
pptx_renderer = PptxGenRenderer()
pdf_renderer = MarkdownToPdfRenderer()


# ============ High-level API ============

async def render_deck(
    deck: DeckSpec,
    formats: list = None,
) -> Dict[str, Any]:
    """
    渲染演示稿

    Args:
        deck: DeckSpec 对象
        formats: 导出格式列表 ["markdown", "pptx", "pdf"]

    Returns:
        {"markdown": path, "pptx": path, "pdf": path}
    """
    formats = formats or ["pptx"]
    results = {}

    if "markdown" in formats:
        md_path = slidev_renderer.render_to_file(deck)
        results["markdown"] = md_path

    if "pptx" in formats:
        pptx_result = await pptx_renderer.render(deck)
        if pptx_result.get("success"):
            results["pptx"] = pptx_result["filepath"]

    if "pdf" in formats:
        # 先生成 markdown，再转 pdf
        md_path = slidev_renderer.render_to_file(deck)
        pdf_result = await pdf_renderer.render(md_path)
        if pdf_result.get("success"):
            results["pdf"] = pdf_result["filepath"]

    return results
