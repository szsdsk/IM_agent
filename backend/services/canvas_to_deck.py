from datetime import datetime
from typing import Any, Dict, List, Optional


CANVAS_DIAGRAM_REF_PREFIX = "canvas:"

NODE_LAYOUT_MAP = {
    "start": "title",
    "input": "bullets",
    "process": "content",
    "decision": "comparison",
    "document": "bullets",
    "slides": "bullets",
    "canvas": "content",
    "notification": "bullets",
    "feedback": "comparison",
    "default": "content",
}


def build_canvas_linked_deck(slides_payload: Dict[str, Any], canvas: Dict[str, Any]) -> Dict[str, Any]:
    """将画布节点转换为实际的PPT幻灯片，而非仅一页文字摘要。

    每个画布节点生成一页对应布局的幻灯片，包含标题、描述内容和视觉样式。
    最后插入或替换原有的画布联动摘要页。
    """
    existing_slides = [
        dict(slide)
        for slide in slides_payload.get("slides", [])
        if isinstance(slide, dict)
    ]
    nodes = _canvas_nodes(canvas)
    edges = _canvas_edges(canvas)

    canvas_slides = []
    for node in nodes:
        node_slide = _node_to_slide(node, nodes, edges)
        canvas_slides.append(node_slide)

    summary_slide = build_canvas_summary_slide(canvas, nodes, edges)
    all_canvas_slides = canvas_slides + [summary_slide]

    slides = _replace_or_insert_canvas_slides(existing_slides, all_canvas_slides)

    for index, slide in enumerate(slides):
        slide["index"] = index

    metadata = dict(slides_payload.get("metadata") or {})
    history = list(metadata.get("canvas_sync_history") or [])
    history.append({
        "canvas_id": canvas.get("canvas_id"),
        "canvas_version": (canvas.get("metadata") or {}).get("version"),
        "synced_at": datetime.utcnow().isoformat(),
        "node_count": len(nodes),
        "slide_count": len(all_canvas_slides),
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


def _node_to_slide(node: Dict[str, Any], all_nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert a single canvas node into a PPT slide with appropriate layout."""
    text = node.get("text", "")
    description = _node_description(node)
    node_type = node.get("kind") or node.get("type") or "process"
    layout = NODE_LAYOUT_MAP.get(node_type, NODE_LAYOUT_MAP["default"])

    connected_edges = [e for e in edges if e.get("source") == node["id"] or e.get("target") == node["id"]]
    connected_nodes = []
    for edge in connected_edges:
        other_id = edge["target"] if edge["source"] == node["id"] else edge["source"]
        other = _node_by_id(all_nodes, other_id)
        if other:
            label = edge.get("label", "")
            rel = f" -> {other['text']}" if label else f" -> {other['text']}"
            connected_nodes.append(rel.strip())

    bullets = []
    if description:
        bullets.append(description)
    if connected_nodes:
        bullets.append("关联: " + "; ".join(connected_nodes[:4]))

    return {
        "title": text,
        "layout": layout,
        "layout_variant": "canvas_node",
        "canvas_node_ref": node["id"],
        "content": description or text,
        "bullets": bullets,
        "speaker_notes": f"画布节点: {text}。{description}" if description else f"画布节点: {text}。",
        "duration_seconds": 45,
        "visual_profile": "canvas_linked",
        "canvas_sync": {
            "node_id": node["id"],
            "node_type": node_type,
        },
    }


def build_canvas_summary_slide(canvas: Dict[str, Any], nodes: Optional[List[Dict[str, Any]]] = None, edges: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """把画布节点和关系整理为一页适合 PPT 展示的结构说明页。"""
    if nodes is None:
        nodes = _canvas_nodes(canvas)
    if edges is None:
        edges = _canvas_edges(canvas)
    canvas_id = canvas.get("canvas_id") or "local"
    title = canvas.get("title") or "画布结构"
    diagram_type = canvas.get("diagram_type") or "flow"
    canvas_version = (canvas.get("metadata") or {}).get("version")

    bullets = []
    for node in nodes[:10]:
        desc = _node_description(node)
        node_type = node.get("kind") or node.get("type") or "node"
        type_tag = f"[{node_type}]"
        bullets.append(f"{type_tag} {node['text']}：{desc}" if desc else f"{type_tag} {node['text']}")

    if edges:
        relation_text = "；".join(
            f"{_node_text_by_id(nodes, edge.get('source'))} -> {_node_text_by_id(nodes, edge.get('target'))}"
            for edge in edges[:8]
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

    layout = "diagram" if diagram_type == "architecture" else "process"
    return {
        "index": 1,
        "title": f"{title}：结构总览",
        "layout": layout,
        "layout_variant": "canvas_linked_summary",
        "diagram_ref": f"{CANVAS_DIAGRAM_REF_PREFIX}{canvas_id}",
        "content": "\n".join(bullets),
        "bullets": bullets,
        "process_steps": process_steps,
        "sections": [
            {
                "title": node["text"],
                "body": _node_description(node) or str(node.get("kind") or node.get("type") or "节点"),
            }
            for node in nodes[:4]
        ],
        "speaker_notes": "这一页根据最新画布自动同步，展示整体结构及各节点间的关联关系。",
        "duration_seconds": 75,
        "visual_profile": "canvas_linked",
        "canvas_sync": {
            "canvas_id": canvas_id,
            "canvas_version": canvas_version,
            "diagram_type": diagram_type,
            "synced_at": datetime.utcnow().isoformat(),
        },
    }


def _replace_or_insert_canvas_slides(slides: List[Dict[str, Any]], canvas_slides: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace existing canvas-linked slides with new ones, or insert at index 1."""
    if not slides:
        return canvas_slides

    first_canvas_index = None
    last_canvas_index = None
    for i, slide in enumerate(slides):
        if slide.get("layout_variant", "").startswith("canvas_linked") or slide.get("diagram_ref", "").startswith(CANVAS_DIAGRAM_REF_PREFIX):
            if first_canvas_index is None:
                first_canvas_index = i
            last_canvas_index = i

    if first_canvas_index is not None and last_canvas_index is not None:
        return slides[:first_canvas_index] + canvas_slides + slides[last_canvas_index + 1:]

    insert_index = 1 if len(slides) > 1 else len(slides)
    return slides[:insert_index] + canvas_slides + slides[insert_index:]


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


def _node_by_id(nodes: List[Dict[str, Any]], node_id: Optional[str]) -> Optional[Dict[str, Any]]:
    for node in nodes:
        if node.get("id") == node_id:
            return node
    return None
