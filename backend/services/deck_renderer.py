from __future__ import annotations
"""
Deck Renderer - PPT 渲染器
DeckSpec -> Slidev Markdown / PptxGenJS
"""
import os
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from backend.services.deck_spec import DeckSpec, SlideSpec, ThemeConfig

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
    """PptxGenJS / python-pptx 渲染器，支持主题模板"""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or "./data/slides"
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def _hex_to_rgb(hex_color: str):
        from pptx.dml.color import RGBColor
        h = hex_color.lstrip("#")
        return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    async def render(self, deck: DeckSpec, filename: str = None) -> Dict[str, Any]:
        if filename is None:
            filename = f"{deck.title.replace(' ', '_')}.pptx"

        filepath = os.path.join(self.output_dir, filename)

        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt, Emu
            from pptx.dml.color import RGBColor
            from pptx.enum.text import PP_ALIGN
        except ImportError:
            logger.warning("python-pptx not installed")
            return {"success": False, "error": "python-pptx not installed"}

        theme = ThemeConfig.get_theme(deck.theme)
        colors = theme.colors

        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        for slide_spec in deck.slides:
            self._add_slide(prs, slide_spec, theme)

        prs.save(filepath)

        return {
            "success": True,
            "filepath": filepath,
            "slides_count": len(deck.slides),
            "title": deck.title,
        }

    def _add_slide(self, prs, slide: SlideSpec, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        colors = theme.colors
        layout = prs.slide_layouts[6]  # blank
        slide_obj = prs.slides.add_slide(layout)

        # Background
        bg = slide_obj.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = self._hex_to_rgb(colors.bg_white)

        # Bottom accent bar
        bar = slide_obj.shapes.add_shape(
            1,  # MSO_SHAPE.RECTANGLE
            Inches(0), Inches(7.1), Inches(13.333), Inches(0.4)
        )
        bar_fill = bar.fill
        bar_fill.solid()
        bar_fill.fore_color.rgb = self._hex_to_rgb(colors.primary)
        bar.line.fill.background()

        # Page number
        page_box = slide_obj.shapes.add_textbox(
            Inches(12.5), Inches(7.12), Inches(0.7), Inches(0.3)
        )
        page_tf = page_box.text_frame
        page_p = page_tf.paragraphs[0]
        page_p.text = str(slide.index + 1)
        page_p.font.size = Pt(10)
        page_p.font.color.rgb = self._hex_to_rgb(colors.text_light)
        page_p.alignment = PP_ALIGN.RIGHT

        # Dispatch layout
        if slide.layout == "title":
            self._render_title_layout(slide_obj, slide, theme)
        elif slide.layout == "content":
            self._render_content_layout(slide_obj, slide, theme)
        elif slide.layout == "two_column":
            self._render_two_column_layout(slide_obj, slide, theme)
        elif slide.layout == "diagram":
            self._render_diagram_layout(slide_obj, slide, theme)
        else:
            self._render_content_layout(slide_obj, slide, theme)

        # Speaker notes
        if slide.speaker_notes:
            notes_slide = slide_obj.notes_slide
            notes_slide.notes_text_frame.text = slide.speaker_notes

    def _render_title_layout(self, slide_obj, slide: SlideSpec, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        colors = theme.colors

        # Top accent strip
        strip = slide_obj.shapes.add_shape(
            1, Inches(0), Inches(0), Inches(13.333), Inches(0.15)
        )
        strip_fill = strip.fill
        strip_fill.solid()
        strip_fill.fore_color.rgb = self._hex_to_rgb(colors.accent)
        strip.line.fill.background()

        # Title - centered, large
        title_box = slide_obj.shapes.add_textbox(
            Inches(1.5), Inches(2.2), Inches(10.333), Inches(2)
        )
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = slide.title
        p.font.size = Pt(theme.title_size + 8)
        p.font.bold = True
        p.font.color.rgb = self._hex_to_rgb(colors.primary)
        p.font.name = theme.font_title
        p.alignment = PP_ALIGN.CENTER

        # Subtitle area (from bullets or content)
        subtitle_text = ""
        if slide.bullets:
            subtitle_text = slide.bullets[0] if len(slide.bullets) == 1 else " | ".join(slide.bullets[:3])

        if subtitle_text:
            sub_box = slide_obj.shapes.add_textbox(
                Inches(2), Inches(4.4), Inches(9.333), Inches(1)
            )
            sub_tf = sub_box.text_frame
            sub_tf.word_wrap = True
            sub_p = sub_tf.paragraphs[0]
            sub_p.text = subtitle_text
            sub_p.font.size = Pt(theme.body_size)
            sub_p.font.color.rgb = self._hex_to_rgb(colors.text_muted)
            sub_p.font.name = theme.font_body
            sub_p.alignment = PP_ALIGN.CENTER

    def _render_content_layout(self, slide_obj, slide: SlideSpec, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        colors = theme.colors

        # Title bar with primary background
        title_bg = slide_obj.shapes.add_shape(
            1, Inches(0), Inches(0), Inches(13.333), Inches(1.3)
        )
        title_bg_fill = title_bg.fill
        title_bg_fill.solid()
        title_bg_fill.fore_color.rgb = self._hex_to_rgb(colors.primary)
        title_bg.line.fill.background()

        # Title text on colored bar
        title_box = slide_obj.shapes.add_textbox(
            Inches(0.8), Inches(0.2), Inches(11.733), Inches(0.9)
        )
        tf = title_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = slide.title
        p.font.size = Pt(theme.title_size)
        p.font.bold = True
        p.font.color.rgb = self._hex_to_rgb(colors.text_light)
        p.font.name = theme.font_title
        p.alignment = PP_ALIGN.LEFT

        # Content area
        if slide.bullets:
            content_box = slide_obj.shapes.add_textbox(
                Inches(1.0), Inches(1.8), Inches(11.333), Inches(4.8)
            )
            content_tf = content_box.text_frame
            content_tf.word_wrap = True

            for i, bullet in enumerate(slide.bullets):
                if i == 0:
                    para = content_tf.paragraphs[0]
                else:
                    para = content_tf.add_paragraph()

                para.text = f"▸  {bullet}"
                para.font.size = Pt(theme.bullet_size)
                para.font.color.rgb = self._hex_to_rgb(colors.text_dark)
                para.font.name = theme.font_body
                para.space_after = Pt(10)

    def _render_two_column_layout(self, slide_obj, slide: SlideSpec, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        colors = theme.colors

        # Title bar
        title_bg = slide_obj.shapes.add_shape(
            1, Inches(0), Inches(0), Inches(13.333), Inches(1.3)
        )
        title_bg_fill = title_bg.fill
        title_bg_fill.solid()
        title_bg_fill.fore_color.rgb = self._hex_to_rgb(colors.primary)
        title_bg.line.fill.background()

        title_box = slide_obj.shapes.add_textbox(
            Inches(0.8), Inches(0.2), Inches(11.733), Inches(0.9)
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = slide.title
        p.font.size = Pt(theme.title_size)
        p.font.bold = True
        p.font.color.rgb = self._hex_to_rgb(colors.text_light)
        p.font.name = theme.font_title

        # Two columns
        mid = max(1, len(slide.bullets) // 2)
        left_bullets = slide.bullets[:mid]
        right_bullets = slide.bullets[mid:]

        # Divider line
        divider = slide_obj.shapes.add_shape(
            1, Inches(6.666), Inches(1.6), Inches(0.02), Inches(5)
        )
        divider_fill = divider.fill
        divider_fill.solid()
        divider_fill.fore_color.rgb = self._hex_to_rgb(colors.divider)
        divider.line.fill.background()

        for bullets, x_pos in [(left_bullets, Inches(0.8)), (right_bullets, Inches(7.0))]:
            col_box = slide_obj.shapes.add_textbox(
                x_pos, Inches(1.8), Inches(5.5), Inches(4.8)
            )
            col_tf = col_box.text_frame
            col_tf.word_wrap = True

            for i, bullet in enumerate(bullets):
                para = col_tf.paragraphs[0] if i == 0 else col_tf.add_paragraph()
                para.text = f"▸  {bullet}"
                para.font.size = Pt(theme.bullet_size)
                para.font.color.rgb = self._hex_to_rgb(colors.text_dark)
                para.font.name = theme.font_body
                para.space_after = Pt(10)

    def _render_diagram_layout(self, slide_obj, slide: SlideSpec, theme: ThemeConfig):
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN

        colors = theme.colors

        # Title bar
        title_bg = slide_obj.shapes.add_shape(
            1, Inches(0), Inches(0), Inches(13.333), Inches(1.3)
        )
        title_bg_fill = title_bg.fill
        title_bg_fill.solid()
        title_bg_fill.fore_color.rgb = self._hex_to_rgb(colors.primary)
        title_bg.line.fill.background()

        title_box = slide_obj.shapes.add_textbox(
            Inches(0.8), Inches(0.2), Inches(11.733), Inches(0.9)
        )
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = slide.title
        p.font.size = Pt(theme.title_size)
        p.font.bold = True
        p.font.color.rgb = self._hex_to_rgb(colors.text_light)
        p.font.name = theme.font_title

        # Placeholder diagram area
        placeholder = slide_obj.shapes.add_shape(
            1, Inches(1.5), Inches(2.0), Inches(10.333), Inches(4.5)
        )
        ph_fill = placeholder.fill
        ph_fill.solid()
        ph_fill.fore_color.rgb = self._hex_to_rgb(colors.bg_light)
        placeholder.line.color.rgb = self._hex_to_rgb(colors.divider)
        placeholder.line.width = Pt(1)

        # Label
        label_box = slide_obj.shapes.add_textbox(
            Inches(4), Inches(3.8), Inches(5.333), Inches(0.8)
        )
        label_tf = label_box.text_frame
        label_p = label_tf.paragraphs[0]
        label_p.text = "[ 图表 / 架构图区域 ]"
        label_p.font.size = Pt(16)
        label_p.font.color.rgb = self._hex_to_rgb(colors.text_muted)
        label_p.alignment = PP_ALIGN.CENTER


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
