"""
PPT Agent subgraph -- core pipeline for structured PPT generation.

Pipeline stages (sequential):
  S1 outline_node   -- LLM generates a presentation brief from deck_spec + doc_content
  S2 structure_node -- maps each slide layout to an MckEngine render method
  S3 content_node   -- transforms outline entries into render-ready parameter dicts
  S4 render_node    -- calls MckEngine methods and saves the .pptx file

All mck_ppt imports are lazy (inside functions) so the module works even when
the visual engine is not installed.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

from backend.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State definition
# ---------------------------------------------------------------------------

class PPTAgentState(TypedDict, total=False):  # type: ignore[valid-type]
    """Shared state carried across PPT agent pipeline stages."""
    deck_spec: Optional[Dict[str, Any]]
    doc_content: Optional[str]
    intent: str
    audience: str
    presentation_scene: Optional[str]
    output_dir: Optional[str]
    ppt_brief: Optional[Dict[str, Any]]
    ppt_outline: Optional[List[Dict[str, Any]]]
    ppt_filled_slides: Optional[List[Dict[str, Any]]]
    ppt_render_result: Optional[Dict[str, Any]]
    error: Optional[str]
    messages: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Layout -> MckEngine method mapping
# ---------------------------------------------------------------------------

LAYOUT_TO_MCK_METHOD = {
    "title": "cover",
    "hero": "cover",
    "section_divider": "section_divider",
    "content": "table_insight",
    "two_column": "two_column_compare",
    "comparison": "two_column_compare",
    "metrics": "metric_comparison",
    "timeline": "timeline",
    "process": "process_chevron",
    "diagram": "process_chevron",
    "cards": "four_column",
    "chart": "column_comparison",       # refined in content_node based on chart.type
    "closing": "closing",
    "blank": "agenda",
}


# ===================================================================
# S1 -- outline_node: generate a structured brief via LLM
# ===================================================================

async def _generate_brief_via_llm(
    deck_spec: Dict[str, Any],
    doc_content: str,
    audience: str,
    presentation_scene: Optional[str],
) -> Dict[str, Any]:
    """Call LLM to produce a presentation brief dict.

    Falls back to a deterministic brief when the LLM service is unavailable
    or in mock mode.
    """
    title = deck_spec.get("title", "演示稿")
    slides = deck_spec.get("slides", [])
    slide_titles = [s.get("title", "") for s in slides if isinstance(s, dict)]

    # 构造 prompt：让 LLM 输出结构化的简报
    prompt = (
        "你是一个专业的演示稿策划助手。请根据以下信息生成一份演示简报。\n\n"
        f"演示标题: {title}\n"
        f"目标受众: {audience}\n"
        f"演示场景: {presentation_scene or '管理层汇报'}\n"
        f"已有页面标题: {', '.join(slide_titles[:12])}\n"
    )
    if doc_content:
        prompt += f"\n参考文档内容（前3000字）:\n{doc_content[:3000]}\n"

    prompt += (
        "\n请以 JSON 格式输出，包含以下字段:\n"
        '- "title": 演示标题（字符串）\n'
        '- "subtitle": 副标题/核心信息（字符串）\n'
        '- "audience": 目标受众（字符串）\n'
        '- "slide_count": 建议页数，8-15之间（整数）\n'
        '- "key_messages": 3-5条核心信息（字符串列表）\n'
        '- "tone": 语调风格，如"专业简洁""正式汇报""轻松互动"（字符串）\n'
        '- "date": 演示日期，使用 ISO 格式（字符串）\n'
        '- "sections": 各章节概要列表，每项包含 "name" 和 "summary"（对象列表）\n'
        "\n只输出 JSON，不要其他文字。"
    )

    # 优先使用项目已有的 llm_service
    try:
        from backend.services.llm_service import llm_service

        response = await llm_service.chat(
            [{"role": "user", "content": prompt}],
            system_prompt="你是一个专业的演示稿策划助手。输出结构化 JSON。",
            temperature=0.4,
            max_tokens=1024,
        )
        content = response.get("content", "")
        if content and "error" not in response:
            parsed = _parse_json_brief(content)
            if parsed:
                logger.info("LLM brief generated successfully")
                return parsed
    except Exception as exc:
        logger.warning("LLM brief generation failed, using fallback: %s", exc)

    # Fallback: 基于规则生成简报
    logger.info("Using fallback brief generation")
    return _fallback_brief(title, audience, slides, doc_content)


def _parse_json_brief(raw: str) -> Optional[Dict[str, Any]]:
    """从 LLM 返回文本中提取 JSON 简报。"""
    text = raw.strip()
    # 去掉 markdown 代码块标记
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:] if lines else [])
    if text.endswith("```"):
        text = text[:-3].strip()
    # 找到第一个 { 的位置
    start = text.find("{")
    if start < 0:
        return None
    text = text[start:]
    # 找到最后一个 } 的位置
    end = text.rfind("}")
    if end < 0:
        return None
    text = text[: end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse brief JSON: %s", text[:200])
        return None


def _fallback_brief(
    title: str,
    audience: str,
    slides: List[Dict[str, Any]],
    doc_content: str,
) -> Dict[str, Any]:
    """当 LLM 不可用时，基于 deck_spec 生成确定性简报。"""
    slide_count = max(min(len(slides), 15), 8)
    key_messages = []
    for slide in slides[:5]:
        t = slide.get("title", "")
        if t:
            key_messages.append(t)
    while len(key_messages) < 3:
        key_messages.append(f"要点 {len(key_messages) + 1}")

    sections = []
    seen = set()
    for slide in slides:
        name = slide.get("title", f"章节 {len(sections) + 1}")
        bullets = slide.get("bullets") or []
        summary = " ".join(str(b)[:60] for b in bullets[:2]) if bullets else ""
        if name not in seen:
            seen.add(name)
            sections.append({"name": name, "summary": summary})

    return {
        "title": title,
        "subtitle": (slides[0].get("bullets") or [""])[0][:80] if slides else "",
        "audience": audience,
        "slide_count": slide_count,
        "key_messages": key_messages[:5],
        "tone": "专业简洁",
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "sections": sections[:10],
    }


async def outline_node(state: PPTAgentState) -> PPTAgentState:
    """S1: 从 deck_spec 和文档内容中提取演示简报。"""
    deck_spec = state.get("deck_spec") or {}
    doc_content = state.get("doc_content") or ""
    audience = state.get("audience", "管理层")
    presentation_scene = state.get("presentation_scene")

    try:
        brief = await _generate_brief_via_llm(deck_spec, doc_content, audience, presentation_scene)
        state["ppt_brief"] = brief
        logger.info(
            "outline_node complete: title=%s, slide_count=%s",
            brief.get("title"), brief.get("slide_count"),
        )
    except Exception as exc:
        logger.exception("outline_node failed")
        state["error"] = f"简报生成失败: {exc}"

    return state


# ===================================================================
# S2 -- structure_node: map layouts to MckEngine methods
# ===================================================================

def structure_node(state: PPTAgentState) -> PPTAgentState:
    """S2: 将 deck_spec 中每一页的 layout 映射为 MckEngine 渲染方法。

    特殊处理：
      - 第一页始终映射为 cover
      - 标题含 "closing"/"Q&A" 的最后一页映射为 closing
      - chart 类型细化：pie -> donut, line -> table_insight
    """
    brief = state.get("ppt_brief")
    deck_spec = state.get("deck_spec") or {}
    slides = deck_spec.get("slides") or []

    if not slides:
        state["error"] = "deck_spec 中没有幻灯片数据"
        return state

    outline: List[Dict[str, Any]] = []
    total = len(slides)

    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue

        original_layout = str(slide.get("layout", "content"))
        title = slide.get("title", "")

        # 特殊位置强制覆盖
        if idx == 0:
            mck_method = "cover"
        elif idx == total - 1 and any(kw in title for kw in ("closing", "Q&A", "结束", "谢谢")):
            mck_method = "closing"
        else:
            mck_method = LAYOUT_TO_MCK_METHOD.get(original_layout, "table_insight")

            # chart 类型细化
            if original_layout == "chart":
                chart_data = slide.get("chart") or {}
                if isinstance(chart_data, dict):
                    chart_type = str(chart_data.get("type", ""))
                    if chart_type == "pie":
                        mck_method = "donut"
                    elif chart_type == "line":
                        mck_method = "table_insight"

        outline.append({
            "index": idx,
            "title": title,
            "mck_method": mck_method,
            "content_hint": slide,
            "original_layout": original_layout,
        })

    state["ppt_outline"] = outline
    logger.info(
        "structure_node complete: %d slides mapped",
        len(outline),
    )
    return state


# ===================================================================
# S3 -- content_node: transform outline into render-ready params
# ===================================================================

def content_node(state: PPTAgentState) -> PPTAgentState:
    """S3: 将每个大纲条目转换为对应 MckEngine 方法所需的参数字典。"""
    outline = state.get("ppt_outline")
    brief = state.get("ppt_brief")

    if not outline:
        state["error"] = "缺少 ppt_outline，无法生成渲染参数"
        return state

    filled_slides: List[Dict[str, Any]] = []

    for entry in outline:
        mck_method = entry["mck_method"]
        hint = entry.get("content_hint") or {}
        title = entry["title"]
        bullets = hint.get("bullets") or []

        params = _build_slide_params(mck_method, title, hint, brief)
        filled_slides.append({
            "index": entry["index"],
            "title": title,
            "mck_method": mck_method,
            "params": params,
        })

    state["ppt_filled_slides"] = filled_slides
    logger.info("content_node complete: %d slides prepared", len(filled_slides))
    return state


def _build_slide_params(
    mck_method: str,
    title: str,
    hint: Dict[str, Any],
    brief: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """根据目标 MckEngine 方法构建渲染参数。"""
    bullets = hint.get("bullets") or []

    if mck_method == "cover":
        return {
            "title": title,
            "subtitle": (brief or {}).get("subtitle", ""),
            "date": (brief or {}).get("date", datetime.utcnow().strftime("%Y-%m-%d")),
        }

    if mck_method == "table_insight":
        rows = [[b[:60], b[:120]] for b in bullets[:6]] if bullets else [["", ""]]
        return {
            "title": title,
            "headers": ["内容", "详情"],
            "rows": rows,
            "insights": bullets[:6],
        }

    if mck_method == "two_column_compare":
        mid = max(1, len(bullets) // 2)
        return {
            "title": title,
            "left_items": bullets[:mid],
            "right_items": bullets[mid:],
        }

    if mck_method == "metric_comparison":
        metrics = hint.get("highlight_metrics") or []
        return {
            "title": title,
            "metrics": metrics[:5] if metrics else [
                {"value": "-", "label": b[:30]} for b in bullets[:5]
            ],
        }

    if mck_method == "timeline":
        timeline_data = hint.get("timeline") or []
        if not timeline_data:
            timeline_data = [
                {"label": f"{i + 1}", "text": b}
                for i, b in enumerate(bullets[:5])
            ]
        milestones = [(t.get("label", ""), t.get("text", "")) for t in timeline_data[:5]]
        return {"title": title, "milestones": milestones}

    if mck_method == "process_chevron":
        steps_data = hint.get("process_steps") or []
        if not steps_data:
            steps_data = [
                {"label": f"{i + 1:02d}", "text": b}
                for i, b in enumerate(bullets[:6])
            ]
        steps = [(s.get("label", ""), s.get("text", "")) for s in steps_data[:6]]
        return {"title": title, "steps": steps}

    if mck_method == "four_column":
        sections_data = hint.get("sections") or []
        if not sections_data:
            sections_data = [
                {"title": b[:18], "body": b}
                for b in bullets[:6]
            ]
        cards = [(s.get("title", ""), s.get("body", "")) for s in sections_data[:6]]
        return {"title": title, "cards": cards}

    if mck_method == "column_comparison":
        chart = hint.get("chart") or {}
        return {
            "title": title,
            "categories": chart.get("categories", []),
            "series": chart.get("series", []),
            "chart_type": chart.get("type", "bar"),
        }

    if mck_method == "donut":
        chart = hint.get("chart") or {}
        categories = chart.get("categories", [])
        values_raw = []
        if chart.get("series"):
            values_raw = chart["series"][0].get("values", [])
        segments = [
            (float(v) if v else 0.0, "", cat)
            for v, cat in zip(values_raw, categories)
        ][:6]
        return {"title": title, "segments": segments}

    if mck_method == "closing":
        return {"title": title}

    if mck_method == "section_divider":
        return {"title": title}

    if mck_method == "agenda":
        items = [(i + 1, b[:40], b[:80]) for i, b in enumerate(bullets[:6])]
        return {"title": title, "items": items}

    # 默认回退到 table_insight 风格
    return {
        "title": title,
        "headers": ["内容", "详情"],
        "rows": [[b[:60], b[:120]] for b in bullets[:6]],
        "insights": bullets,
    }


# ===================================================================
# S4 -- render_node: call MckEngine and save .pptx
# ===================================================================

def render_node(state: PPTAgentState) -> PPTAgentState:
    """S4: 实例化 MckEngine 并逐页调用渲染方法，保存为 .pptx 文件。"""
    filled_slides = state.get("ppt_filled_slides")
    output_dir = state.get("output_dir")

    if not filled_slides:
        state["error"] = "缺少 ppt_filled_slides，无法渲染"
        return state

    try:
        from mck_ppt import MckEngine  # type: ignore
    except ImportError:
        state["error"] = (
            "mck_ppt 未安装，无法使用视觉增强渲染器。"
            "请运行: pip install mck-ppt"
        )
        logger.error(state["error"])
        return state

    # 确定输出目录
    if not output_dir:
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "..", "data", "slides"
        )
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"mck_deck_{timestamp}.pptx"
    output_path = os.path.join(output_dir, filename)

    try:
        eng = MckEngine(total_slides=len(filled_slides))
        rendered_count = 0
        errors: List[str] = []

        for slide_info in filled_slides:
            mck_method = slide_info["mck_method"]
            params = slide_info["params"]
            idx = slide_info["index"]

            try:
                method_fn = getattr(eng, mck_method, None)
                if method_fn is None:
                    msg = f"Slide {idx}: MckEngine 缺少方法 '{mck_method}'"
                    logger.warning(msg)
                    errors.append(msg)
                    continue
                method_fn(**params)
                rendered_count += 1
            except Exception as slide_exc:
                msg = f"Slide {idx} ({mck_method}) 渲染失败: {slide_exc}"
                logger.warning(msg)
                errors.append(msg)
                # 单页失败不中断整份演示文稿

        eng.save(output_path)

        state["ppt_render_result"] = {
            "success": True,
            "filepath": output_path,
            "filename": filename,
            "total_slides": len(filled_slides),
            "rendered_slides": rendered_count,
            "errors": errors,
        }
        logger.info(
            "render_node complete: %d/%d slides saved to %s",
            rendered_count, len(filled_slides), output_path,
        )
    except Exception as exc:
        logger.exception("render_node failed unexpectedly")
        state["error"] = f"PPT 渲染失败: {exc}"

    return state


# ===================================================================
# Public entry point
# ===================================================================

async def run_ppt_agent(
    deck_spec: Dict[str, Any],
    doc_content: str = "",
    intent: str = "",
    audience: str = "管理层",
    presentation_scene: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """PPT Agent 公开入口：依次执行 S1->S2->S3->S4 四个阶段。

    Returns a dict compatible with the existing ``slides_content`` contract
    used by ``nodes.generate_slides`` and the frontend preview layer.
    """
    initial_state: PPTAgentState = {
        "deck_spec": deck_spec,
        "doc_content": doc_content or "",
        "intent": intent or (deck_spec or {}).get("title", ""),
        "audience": audience,
        "presentation_scene": presentation_scene,
        "output_dir": output_dir,
        "messages": [],
    }

    # S1: 生成演示简报
    state = await outline_node(initial_state)
    if state.get("error"):
        return _error_result(state["error"], deck_spec)

    # S2: 映射布局到渲染方法
    state = structure_node(state)
    if state.get("error"):
        return _error_result(state["error"], deck_spec)

    # S3: 转换为渲染参数
    state = content_node(state)
    if state.get("error"):
        return _error_result(state["error"], deck_spec)

    # S4: 调用引擎渲染
    state = render_node(state)
    if state.get("error"):
        return _error_result(state["error"], deck_spec)

    render_result = state.get("ppt_render_result") or {}
    brief = state.get("ppt_brief") or {}
    outline = state.get("ppt_outline") or []

    # 组装与现有 slides_content 兼容的返回值
    slides_for_frontend = []
    for entry in outline:
        hint = entry.get("content_hint") or {}
        slides_for_frontend.append({
            "index": entry["index"],
            "title": entry["title"],
            "layout": entry.get("original_layout", "content"),
            "mck_method": entry["mck_method"],
            "bullets": hint.get("bullets", []),
        })

    return {
        "success": True,
        "title": brief.get("title", deck_spec.get("title", "")),
        "slides": slides_for_frontend,
        "slides_count": len(slides_for_frontend),
        "file_path": render_result.get("filepath"),
        "theme": deck_spec.get("theme", "business_blue"),
        "audience": audience,
        "duration_minutes": deck_spec.get("duration_minutes", 5),
        "metadata": {
            **(deck_spec.get("metadata", {})),
            "pipeline": "ppt_agent",
            "rendered_at": datetime.utcnow().isoformat(),
            "brief": brief,
            "render_result": render_result,
        },
    }


def _error_result(error_msg: str, deck_spec: Dict[str, Any]) -> Dict[str, Any]:
    """统一包装错误返回，保持与成功返回相同的顶层结构。"""
    return {
        "success": False,
        "error": error_msg,
        "title": deck_spec.get("title", ""),
        "slides": [],
        "slides_count": 0,
        "file_path": None,
        "metadata": {"pipeline": "ppt_agent", "failed_at": datetime.utcnow().isoformat()},
    }
