from datetime import datetime
from typing import Any, Dict, List, Optional


CANVAS_DIAGRAM_REF_PREFIX = "canvas:"


def build_canvas_linked_deck(slides_payload: Dict[str, Any], canvas: Dict[str, Any]) -> Dict[str, Any]:
    """把当前画布确定性转换成 DeckSpec，并插入或替换 PPT 中的画布联动页。"""
    existing_slides = [
        dict(slide)
        for slide in slides_payload.get("slides", [])
        if isinstance(slide, dict)
    ]
    canvas_slide = build_canvas_summary_slide(canvas)
    slides = _replace_or_insert_canvas_slide(existing_slides, canvas_slide)

    for index, slide in enumerate(slides):
        slide["index"] = index

    metadata = dict(slides_payload.get("metadata") or {})
    history = list(metadata.get("canvas_sync_history") or [])
    history.append({
        "canvas_id": canvas.get("canvas_id"),
        "canvas_version": (canvas.get("metadata") or {}).get("version"),
        "synced_at": datetime.utcnow().isoformat(),
        "node_count": len(_canvas_nodes(canvas)),
    })
    metadata["canvas_sync_history"] = history[-10:]
    metadata["last_canvas_sync_at"] = history[-1]["synced_at"]
    metadata["linked_canvas_id"] = canvas.get("canvas_id")

    return {
        "title": slides_payload.get("title") or canvas.get("title") or "Agent-Pilot 演示稿",
        "audience": slides_payload.get("audience") or "管理层",
        "duration_minutes": slides_payload.get("duration_minutes") or max(len(slides), 1),
        "theme": slides_payload.get("theme") or "business_blue",
        "visual_profile": slides_payload.get("visual_profile"),
        "slides": slides,
        "metadata": metadata,
    }


def build_canvas_summary_slide(canvas: Dict[str, Any]) -> Dict[str, Any]:
    """把画布节点和关系整理为一页适合 PPT 展示的结构说明页。"""
    nodes = _canvas_nodes(canvas)
    edges = _canvas_edges(canvas)
    canvas_id = canvas.get("canvas_id") or "local"
    title = canvas.get("title") or "画布结构"
    diagram_type = canvas.get("diagram_type") or "flow"
    canvas_version = (canvas.get("metadata") or {}).get("version")

    bullets = []
    for node in nodes[:8]:
        desc = _node_description(node)
        bullets.append(f"{node['text']}：{desc}" if desc else node["text"])

    if edges:
        relation_text = "；".join(
            f"{_node_text_by_id(nodes, edge.get('source'))} -> {_node_text_by_id(nodes, edge.get('target'))}"
            for edge in edges[:6]
        )
        bullets.append(f"关键关系：{relation_text}")

    process_steps = [
        {
            "label": str(index + 1),
            "text": node["text"],
            "description": _node_description(node) or str(node.get("kind") or node.get("type") or ""),
        }
        for index, node in enumerate(nodes[:6])
    ]

    sections = [
        {
            "title": node["text"],
            "body": _node_description(node) or str(node.get("kind") or node.get("type") or "节点"),
        }
        for node in nodes[:4]
    ]

    layout = "diagram" if diagram_type == "architecture" else "process"
    return {
        "index": 1,
        "title": f"{title}：结构说明",
        "layout": layout,
        "layout_variant": "canvas_linked",
        "diagram_ref": f"{CANVAS_DIAGRAM_REF_PREFIX}{canvas_id}",
        "content": "\n".join(bullets),
        "bullets": bullets,
        "process_steps": process_steps,
        "sections": sections,
        "speaker_notes": "这一页根据最新画布自动同步，讲解时先说明整体结构，再按节点顺序展开。",
        "duration_seconds": 75,
        "visual_profile": "canvas_linked",
        "canvas_sync": {
            "canvas_id": canvas_id,
            "canvas_version": canvas_version,
            "diagram_type": diagram_type,
            "synced_at": datetime.utcnow().isoformat(),
        },
    }


def _replace_or_insert_canvas_slide(slides: List[Dict[str, Any]], canvas_slide: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not slides:
        return [canvas_slide]

    canvas_id = canvas_slide.get("canvas_sync", {}).get("canvas_id")
    expected_ref = f"{CANVAS_DIAGRAM_REF_PREFIX}{canvas_id}"

    for index, slide in enumerate(slides):
        if slide.get("diagram_ref") == expected_ref or slide.get("layout_variant") == "canvas_linked":
            return slides[:index] + [canvas_slide] + slides[index + 1:]

    insert_index = 1 if len(slides) > 1 else len(slides)
    return slides[:insert_index] + [canvas_slide] + slides[insert_index:]


def _canvas_nodes(canvas: Dict[str, Any]) -> List[Dict[str, Any]]:
    elements = canvas.get("elements") if isinstance(canvas.get("elements"), list) else []
    nodes = [
        _normalize_node(element, index)
        for index, element in enumerate(elements)
        if isinstance(element, dict) and element.get("type") == "node"
    ]
    if nodes:
        return nodes

    raw_nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    return [
        _normalize_node(node, index)
        for index, node in enumerate(raw_nodes)
        if isinstance(node, dict)
    ]


def _canvas_edges(canvas: Dict[str, Any]) -> List[Dict[str, Any]]:
    elements = canvas.get("elements") if isinstance(canvas.get("elements"), list) else []
    edges = [
        dict(element)
        for element in elements
        if isinstance(element, dict) and element.get("type") == "edge"
    ]
    if edges:
        return edges

    raw_edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    return [dict(edge) for edge in raw_edges if isinstance(edge, dict)]


def _normalize_node(node: Dict[str, Any], index: int) -> Dict[str, Any]:
    text = str(node.get("text") or node.get("label") or node.get("title") or node.get("id") or f"节点 {index + 1}").strip()
    return {
        **node,
        "id": str(node.get("id") or f"n{index + 1}"),
        "text": text,
    }


def _node_description(node: Dict[str, Any]) -> str:
    return str(node.get("description") or node.get("summary") or "").strip()


def _node_text_by_id(nodes: List[Dict[str, Any]], node_id: Optional[str]) -> str:
    for node in nodes:
        if node.get("id") == node_id:
            return node.get("text") or str(node_id or "")
    return str(node_id or "")
