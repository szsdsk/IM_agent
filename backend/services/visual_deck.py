from __future__ import annotations

"""Visual normalization for DeckSpec.

This layer upgrades plain model output into deterministic visual intent.  The
renderer can then draw metrics, timelines, process rails and cards without
asking the model to invent coordinates.
"""

import re
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Tuple

from backend.services.deck_spec import DeckSpec, SlideSpec


NUMERIC_PATTERN = re.compile(r"([+-]?\d+(?:\.\d+)?\s*(?:%|x|X|倍|万|千|百|亿|人|天|周|月|年|项|次|k|K)?)")
TIMELINE_PATTERN = re.compile(r"(第\s*\d+|phase|阶段|里程碑|day|week|周|月|上线|灰度|发布)", re.IGNORECASE)
PROCESS_PATTERN = re.compile(r"(步骤|流程|路径|闭环|输入|输出|采集|分析|生成|交付|同步|回流|触发|执行)")
COMPARISON_PATTERN = re.compile(r"(对比|优势|劣势|优点|缺点|before|after|现状|目标|风险|机会)", re.IGNORECASE)
CHART_PATTERN = re.compile(r"(收入|营收|占比|增长|趋势|比例|份额|同比|环比|季度|月度|分布|对比数据|图表|柱状|折线|饼图)", re.IGNORECASE)


SCENE_THEME_MAP = {
    "management_briefing": ("business_blue", "executive"),
    "project_review": ("tech_dark", "technical"),
    "proposal_pitch": ("emerald", "proposal"),
    "postmortem": ("slate", "review"),
    "training": ("minimal", "training"),
}


def normalize_visual_deck(deck: DeckSpec) -> DeckSpec:
    """Fill theme, visual profile and high-level layouts for old and new specs."""
    scene_key = str((deck.metadata or {}).get("presentation_scene") or (deck.metadata or {}).get("template_profile") or "")
    theme, profile = _choose_visual_profile(deck, scene_key)
    metadata = dict(deck.metadata or {})
    metadata.update({
        "visual_enhanced": True,
        "visual_profile": profile,
        "normalized_layouts": True,
    })

    normalized = replace(deck, theme=theme, visual_profile=profile, metadata=metadata, slides=[])
    total = len(deck.slides)
    for index, slide in enumerate(deck.slides):
        normalized.slides.append(_normalize_slide(slide, index, total, profile))
    return normalized


def _choose_visual_profile(deck: DeckSpec, scene_key: str) -> Tuple[str, str]:
    title = f"{deck.title} {' '.join(slide.title for slide in deck.slides[:3])}".lower()
    if any(keyword in title for keyword in ["原神", "星穹", "游戏", "动漫", "娱乐", "二次元", "bilibili", "哔哩"]):
        return "entertainment", "entertainment"
    if scene_key in SCENE_THEME_MAP:
        return SCENE_THEME_MAP[scene_key]
    if any(keyword in title for keyword in ["复盘", "风险", "事故", "postmortem"]):
        return "slate", "review"
    if any(keyword in title for keyword in ["方案", "提案", "商业", "增长"]):
        return "emerald", "proposal"
    return deck.theme or "business_blue", deck.visual_profile or "executive"


def _normalize_slide(slide: SlideSpec, index: int, total: int, profile: str) -> SlideSpec:
    bullets = _clean_bullets(slide.bullets, slide.content)
    title = slide.title or f"第 {index + 1} 页"
    layout = _pick_layout(slide.layout, title, bullets, index, total)
    metrics = _extract_metrics(bullets)
    timeline = _extract_timeline(bullets)
    steps = _extract_process_steps(bullets)
    sections = _extract_sections(bullets)

    if layout == "metrics" and not metrics:
        layout = "cards"
    if layout == "timeline" and not timeline:
        layout = "process" if steps else "cards"
    if layout == "process" and not steps:
        steps = [{"label": f"Step {i + 1}", "text": item} for i, item in enumerate(bullets[:5])]

    # Upgrade to chart layout if chart data present or title suggests chart
    chart_data = slide.chart
    if layout not in {"hero", "closing"} and (chart_data or CHART_PATTERN.search(slide.title or "")):
        layout = "chart"

    max_bullets = 6 if layout in {"content", "two_column"} else 4
    return replace(
        slide,
        index=index,
        title=title,
        layout=layout,
        visual_profile=profile,
        layout_variant=_layout_variant(layout, index),
        bullets=bullets[:max_bullets],
        highlight_metrics=metrics[:4],
        timeline=timeline[:5],
        process_steps=steps[:6],
        sections=sections[:6],
    )


def _pick_layout(current: str, title: str, bullets: List[str], index: int, total: int) -> str:
    title_text = title.lower()
    if current in {"hero", "section_divider", "metrics", "timeline", "comparison", "process", "cards", "chart", "closing"}:
        return current
    if index == 0 or current == "title":
        return "hero"
    if index == total - 1 or any(keyword in title for keyword in ["Q&A", "qa", "下一步", "总结", "谢谢"]):
        return "closing"
    if any(keyword in title for keyword in ["目录", "议程", "章节"]):
        return "section_divider"
    joined = "\n".join(bullets)
    if TIMELINE_PATTERN.search(joined) or any(keyword in title for keyword in ["计划", "路线", "里程碑", "时间"]):
        return "timeline"
    if len(_extract_metrics(bullets)) >= 2:
        return "metrics"
    if current == "diagram" or PROCESS_PATTERN.search(title + joined):
        return "process"
    if current == "two_column" or COMPARISON_PATTERN.search(title_text + joined):
        return "comparison"
    if 2 <= len(bullets) <= 6:
        return "cards"
    return "content"


def _layout_variant(layout: str, index: int) -> str:
    variants = {
        "hero": "diagonal",
        "metrics": "scorecards",
        "timeline": "horizontal",
        "comparison": "split",
        "process": "rail",
        "cards": "mosaic" if index % 2 else "grid",
        "closing": "summary",
    }
    return variants.get(layout, "standard")


def _clean_bullets(bullets: Iterable[Any], content: Any) -> List[str]:
    values = [str(item).strip() for item in bullets or [] if str(item).strip()]
    if not values and content:
        if isinstance(content, str):
            values = [line.strip("-•\t ") for line in content.splitlines() if line.strip()]
        elif isinstance(content, dict):
            for value in content.values():
                if isinstance(value, list):
                    values.extend(str(item).strip() for item in value if str(item).strip())
                elif value:
                    values.append(str(value).strip())
        elif isinstance(content, list):
            values = [str(item).strip() for item in content if str(item).strip()]

    cleaned = []
    for item in values:
        text = re.sub(r"\s+", " ", item).strip(" -•\t")
        if text and text not in cleaned:
            cleaned.append(text[:90])
    return cleaned


def _extract_metrics(bullets: List[str]) -> List[Dict[str, str]]:
    metrics = []
    for item in bullets:
        match = NUMERIC_PATTERN.search(item)
        if not match:
            continue
        value = match.group(1).strip()
        label = item.replace(value, "").strip(" ：:-")
        metrics.append({"value": value, "label": label or item})
    return metrics


def _extract_timeline(bullets: List[str]) -> List[Dict[str, str]]:
    items = []
    for index, item in enumerate(bullets):
        if TIMELINE_PATTERN.search(item) or index < 5:
            parts = re.split(r"[：:、-]", item, maxsplit=1)
            label = parts[0].strip() if parts else f"阶段 {index + 1}"
            text = parts[1].strip() if len(parts) > 1 else item
            items.append({"label": label[:16], "text": text[:70]})
    return items


def _extract_process_steps(bullets: List[str]) -> List[Dict[str, str]]:
    return [
        {"label": f"{index + 1:02d}", "text": item}
        for index, item in enumerate(bullets[:6])
    ]


def _extract_sections(bullets: List[str]) -> List[Dict[str, str]]:
    sections = []
    for item in bullets:
        if "：" in item:
            title, body = item.split("：", 1)
        elif ":" in item:
            title, body = item.split(":", 1)
        else:
            title, body = item[:12], item
        sections.append({"title": title.strip()[:18], "body": body.strip()[:72]})
    return sections
