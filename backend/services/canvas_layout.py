import re
from typing import Any, Dict, List, Optional, Tuple


NODE_WIDTH = 220
NODE_HEIGHT = 88
FLOW_GAP_X = 92
FLOW_GAP_Y = 92
ARCH_LAYER_HEIGHT = 132
CONTENT_GAP_Y = 34


TYPE_STYLES = {
    "start": {"fill": "#DCFCE7", "stroke": "#16A34A", "text": "#14532D", "accent": "#22C55E"},
    "input": {"fill": "#E0F2FE", "stroke": "#0284C7", "text": "#075985", "accent": "#0EA5E9"},
    "process": {"fill": "#EEF2FF", "stroke": "#4F46E5", "text": "#312E81", "accent": "#6366F1"},
    "decision": {"fill": "#FEF3C7", "stroke": "#D97706", "text": "#78350F", "accent": "#F59E0B"},
    "owner": {"fill": "#FCE7F3", "stroke": "#DB2777", "text": "#831843", "accent": "#EC4899"},
    "notification": {"fill": "#F0FDFA", "stroke": "#0D9488", "text": "#134E4A", "accent": "#14B8A6"},
    "feedback": {"fill": "#F3E8FF", "stroke": "#9333EA", "text": "#581C87", "accent": "#A855F7"},
    "document": {"fill": "#F8FAFC", "stroke": "#64748B", "text": "#0F172A", "accent": "#94A3B8"},
    "slides": {"fill": "#FFF7ED", "stroke": "#EA580C", "text": "#7C2D12", "accent": "#F97316"},
    "canvas": {"fill": "#ECFEFF", "stroke": "#0891B2", "text": "#164E63", "accent": "#06B6D4"},
    "theme": {"fill": "#EFF6FF", "stroke": "#2563EB", "text": "#1E3A8A", "accent": "#3B82F6"},
    "insight": {"fill": "#F0FDF4", "stroke": "#16A34A", "text": "#14532D", "accent": "#22C55E"},
    "evidence": {"fill": "#FDF4FF", "stroke": "#C026D3", "text": "#701A75", "accent": "#D946EF"},
    "action": {"fill": "#FFF7ED", "stroke": "#EA580C", "text": "#7C2D12", "accent": "#F97316"},
    "default": {"fill": "#FFFFFF", "stroke": "#CBD5E1", "text": "#1E293B", "accent": "#3B82F6"},
}


def normalize_canvas_artifact(
    *,
    title: Optional[str],
    diagram_type: Optional[str],
    task_id: Optional[str],
    workspace_id: Optional[str] = None,
    canvas_id: Optional[str] = None,
    nodes: Optional[List[Dict[str, Any]]] = None,
    edges: Optional[List[Dict[str, Any]]] = None,
    layers: Optional[List[List[str]]] = None,
    elements: Optional[List[Dict[str, Any]]] = None,
    provider: str = "local_canvas",
    url: Optional[str] = None,
    affine_configured: bool = False,
) -> Dict[str, Any]:
    """把模型/工具返回的轻量画布规格整理成前端可直接绘制的稳定结构。"""
    normalized_layers = _normalize_layers(layers or [])
    normalized_nodes = _normalize_nodes(nodes or [], normalized_layers)
    normalized_edges = _normalize_edges(edges or [], normalized_nodes)
    resolved_type = _resolve_diagram_type(diagram_type, normalized_nodes, normalized_layers, title or "")

    if elements:
        layout_nodes, layout_edges, viewport = _reuse_elements(elements, normalized_nodes, normalized_edges)
    elif resolved_type == "architecture":
        layout_nodes, layout_edges, viewport = _layout_architecture(normalized_nodes, normalized_edges, normalized_layers)
    elif resolved_type == "content_map":
        layout_nodes, layout_edges, viewport = _layout_content_map(normalized_nodes, normalized_edges)
    elif resolved_type == "delivery_pipeline":
        layout_nodes, layout_edges, viewport = _layout_delivery_pipeline(normalized_nodes, normalized_edges)
    else:
        layout_nodes, layout_edges, viewport = _layout_flow(normalized_nodes, normalized_edges)

    canvas_elements = _group_elements(normalized_layers, viewport) + layout_nodes + layout_edges
    safe_canvas_id = canvas_id or f"canvas_{task_id or 'local'}"

    return {
        "success": True,
        "provider": provider,
        "workspace_id": workspace_id or f"ws_{task_id or 'local'}",
        "canvas_id": safe_canvas_id,
        "title": title or "Agent-Pilot 画布",
        "url": url,
        "diagram_type": resolved_type,
        "nodes": [_strip_element_fields(node) for node in layout_nodes],
        "edges": [_strip_edge_fields(edge) for edge in layout_edges],
        "layers": normalized_layers,
        "elements": canvas_elements,
        "viewport": viewport,
        "exportable": True,
        "metadata": {
            "layout_engine": "local_svg_v1",
            "artifact_count": sum(1 for node in layout_nodes if node.get("artifact_type")),
            "affine_configured": affine_configured,
            "sync_status": "external_link_available" if url else "local_only",
        },
    }


def _normalize_nodes(nodes: List[Dict[str, Any]], layers: List[List[str]]) -> List[Dict[str, Any]]:
    if not nodes and layers:
        generated = []
        for row, layer in enumerate(layers):
            for col, text in enumerate(layer):
                generated.append({"id": f"l{row + 1}_{col + 1}", "text": text, "type": "process", "layer": row})
        nodes = generated

    if not nodes:
        nodes = [
            {"id": "n1", "text": "接收需求", "type": "input"},
            {"id": "n2", "text": "生成文档", "type": "document"},
            {"id": "n3", "text": "生成画布", "type": "canvas"},
            {"id": "n4", "text": "生成 PPT", "type": "slides"},
            {"id": "n5", "text": "交付结果", "type": "notification"},
        ]

    normalized = []
    seen = set()
    for index, node in enumerate(nodes, 1):
        raw_id = str(node.get("id") or f"n{index}")
        node_id = _unique_id(_safe_id(raw_id), seen)
        text = str(node.get("text") or node.get("label") or node.get("title") or node_id)
        node_type = str(node.get("type") or "process").lower()
        artifact_type = node.get("artifact_type") or _detect_artifact_type({**node, "id": node_id, "text": text})
        normalized.append({
            **node,
            "id": node_id,
            "text": text,
            "type": _visual_type(node_type, artifact_type),
            "artifact_type": artifact_type,
            "description": node.get("description") or node.get("summary") or "",
        })
    return normalized


def _normalize_edges(edges: List[Dict[str, Any]], nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    node_ids = {node["id"] for node in nodes}
    normalized = []
    for index, edge in enumerate(edges, 1):
        source = _safe_id(str(edge.get("source") or edge.get("from") or ""))
        target = _safe_id(str(edge.get("target") or edge.get("to") or ""))
        if source in node_ids and target in node_ids and source != target:
            normalized.append({
                "id": edge.get("id") or f"e{index}",
                "source": source,
                "target": target,
                "label": str(edge.get("label") or ""),
            })

    if not normalized and len(nodes) > 1:
        normalized = [
            {"id": f"e{index + 1}", "source": nodes[index]["id"], "target": nodes[index + 1]["id"], "label": ""}
            for index in range(len(nodes) - 1)
        ]
    return normalized


def _normalize_layers(layers: List[List[str]]) -> List[List[str]]:
    normalized = []
    for layer in layers:
        values = [str(item).strip() for item in layer if str(item).strip()]
        if values:
            normalized.append(values)
    return normalized


def _layout_flow(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    if edges:
        return _layout_by_edge_direction(nodes, edges)

    columns = 3 if len(nodes) > 5 else max(len(nodes), 1)
    placed = []
    for index, node in enumerate(nodes):
        col = index % columns
        row = index // columns
        x = 80 + col * (NODE_WIDTH + FLOW_GAP_X)
        y = 92 + row * (NODE_HEIGHT + FLOW_GAP_Y)
        placed.append(_node_element(node, x, y))
    return _with_edges(placed, edges)


def _layout_by_edge_direction(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """按上下游关系做左到右分层，尽量避免流程图边反向穿插。"""
    node_ids = {node["id"] for node in nodes}
    valid_edges = [edge for edge in edges if edge.get("source") in node_ids and edge.get("target") in node_ids]
    outgoing = {node["id"]: [] for node in nodes}
    indegree = {node["id"]: 0 for node in nodes}
    for edge in valid_edges:
        outgoing[edge["source"]].append(edge["target"])
        indegree[edge["target"]] += 1

    levels = {node["id"]: 0 for node in nodes}
    queue = [node["id"] for node in nodes if indegree[node["id"]] == 0]
    visited = []
    while queue:
        node_id = queue.pop(0)
        visited.append(node_id)
        for target_id in outgoing.get(node_id, []):
            levels[target_id] = max(levels.get(target_id, 0), levels.get(node_id, 0) + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                queue.append(target_id)

    fallback_level = max(levels.values() or [0]) + 1
    for index, node in enumerate(nodes):
        if node["id"] not in visited and valid_edges:
            levels[node["id"]] = fallback_level + index

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for node in nodes:
        grouped.setdefault(levels[node["id"]], []).append(node)

    placed = []
    for level in sorted(grouped):
        for row, node in enumerate(grouped[level]):
            x = 96 + level * (NODE_WIDTH + 110)
            y = 96 + row * (NODE_HEIGHT + 72)
            placed.append(_node_element(node, x, y))
    return _with_edges(placed, edges)


def _layout_delivery_pipeline(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    placed = []
    for index, node in enumerate(nodes):
        x = 96 + index * (NODE_WIDTH + 72)
        y = 150 + (36 if index % 2 else 0)
        placed.append(_node_element(node, x, y))
    return _with_edges(placed, edges)


def _layout_content_map(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """把内容型画布排成左侧主题、右侧观点列表，避免自由拖拽前就出现交叉线。"""
    if not nodes:
        return _with_edges([], edges)

    placed = []
    center = _node_element({**nodes[0], "type": "theme"}, 96, 220)
    center["width"] = 260
    center["height"] = 112
    placed.append(center)

    children = nodes[1:] or nodes[:1]
    for index, node in enumerate(children):
        # 内容白板默认按单列展开，牺牲一点横向空间来换取更稳定、少交叉的阅读路径。
        x = 460
        y = 72 + index * (NODE_HEIGHT + CONTENT_GAP_Y)
        visual_type = node.get("type") if node.get("type") in {"insight", "evidence", "action"} else "insight"
        placed.append(_node_element({**node, "type": visual_type}, x, y))

    if not edges and len(placed) > 1:
        edges = [
            {"id": f"e{index}", "source": placed[0]["id"], "target": node["id"], "label": ""}
            for index, node in enumerate(placed[1:], 1)
        ]
    return _with_edges(placed, edges)


def _layout_architecture(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], layers: List[List[str]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    placed = []
    if layers:
        by_text = {node["text"]: node for node in nodes}
        for row, layer in enumerate(layers):
            for col, text in enumerate(layer):
                node = by_text.get(text) or {"id": f"l{row + 1}_{col + 1}", "text": text, "type": "process"}
                x = 112 + col * (NODE_WIDTH + 72)
                y = 104 + row * ARCH_LAYER_HEIGHT
                placed.append(_node_element(node, x, y, layer=row))
    else:
        for index, node in enumerate(nodes):
            x = 112 + (index % 3) * (NODE_WIDTH + 72)
            y = 104 + (index // 3) * ARCH_LAYER_HEIGHT
            placed.append(_node_element(node, x, y, layer=index // 3))
    return _with_edges(placed, edges)


def _with_edges(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    node_map = {node["id"]: node for node in nodes}
    edge_elements = []
    for index, edge in enumerate(edges, 1):
        source = node_map.get(edge["source"])
        target = node_map.get(edge["target"])
        if not source or not target:
            continue
        points = _edge_points(source, target)
        edge_elements.append({
            "type": "edge",
            "id": edge.get("id") or f"e{index}",
            "source": source["id"],
            "target": target["id"],
            "label": edge.get("label", ""),
            "points": points,
        })
    return nodes, edge_elements, _viewport(nodes)


def _node_element(node: Dict[str, Any], x: float, y: float, layer: Optional[int] = None) -> Dict[str, Any]:
    visual_type = node.get("type") or "process"
    style = TYPE_STYLES.get(visual_type, TYPE_STYLES["default"])
    return {
        "type": "node",
        "id": node["id"],
        "text": node["text"],
        "kind": visual_type,
        "artifact_type": node.get("artifact_type"),
        "description": node.get("description", ""),
        "x": x,
        "y": y,
        "width": NODE_WIDTH,
        "height": NODE_HEIGHT,
        "layer": layer,
        "style": style,
    }


def _group_elements(layers: List[List[str]], viewport: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not layers:
        return []
    groups = []
    for index, layer in enumerate(layers):
        y = 76 + index * ARCH_LAYER_HEIGHT
        groups.append({
            "type": "group",
            "id": f"layer_{index + 1}",
            "label": f"Layer {index + 1}",
            "items": layer,
            "x": 56,
            "y": y,
            "width": max(viewport["width"] - 112, NODE_WIDTH + 96),
            "height": ARCH_LAYER_HEIGHT - 28,
            "style": {"fill": "#F8FAFC", "stroke": "#E2E8F0", "text": "#64748B"},
        })
    return groups


def _reuse_elements(
    elements: List[Dict[str, Any]],
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    node_elements = [element for element in elements if element.get("type") == "node"]
    edge_elements = [element for element in elements if element.get("type") == "edge"]
    if node_elements:
        return node_elements, edge_elements, _viewport(node_elements)
    return _with_edges([_node_element(node, 80 + index * (NODE_WIDTH + FLOW_GAP_X), 92) for index, node in enumerate(nodes)], edges)


def _edge_points(source: Dict[str, Any], target: Dict[str, Any]) -> List[Dict[str, float]]:
    start = {"x": source["x"] + source["width"], "y": source["y"] + source["height"] / 2}
    end = {"x": target["x"], "y": target["y"] + target["height"] / 2}
    mid_x = (start["x"] + end["x"]) / 2
    return [start, {"x": mid_x, "y": start["y"]}, {"x": mid_x, "y": end["y"]}, end]


def _viewport(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not nodes:
        return {"x": 0, "y": 0, "width": 960, "height": 520}
    min_x = min(node["x"] for node in nodes) - 80
    min_y = min(node["y"] for node in nodes) - 80
    max_x = max(node["x"] + node["width"] for node in nodes) + 80
    max_y = max(node["y"] + node["height"] for node in nodes) + 80
    return {"x": min_x, "y": min_y, "width": max(max_x - min_x, 960), "height": max(max_y - min_y, 520)}


def _resolve_diagram_type(diagram_type: Optional[str], nodes: List[Dict[str, Any]], layers: List[List[str]], title: str) -> str:
    requested = (diagram_type or "").lower()
    if requested in {"architecture", "delivery_pipeline", "flow", "content_map"}:
        return requested
    if layers or any(word in title for word in ["架构", "architecture", "系统"]):
        return "architecture"
    if any(node.get("artifact_type") for node in nodes) or any(word in title for word in ["交付", "delivery"]):
        return "delivery_pipeline"
    return "flow"


def _visual_type(node_type: str, artifact_type: Optional[str]) -> str:
    if artifact_type == "doc":
        return "document"
    if artifact_type == "slides":
        return "slides"
    if artifact_type == "canvas":
        return "canvas"
    return node_type if node_type in TYPE_STYLES else "process"


def _detect_artifact_type(node: Dict[str, Any]) -> Optional[str]:
    haystack = " ".join(str(node.get(key, "")).lower() for key in ["id", "text", "label", "title", "type"])
    if re.search(r"文稿|文档|doc|document|prd|report|generate_doc", haystack):
        return "doc"
    if re.search(r"ppt|slides|slide|deck|演示|幻灯片|generate_slides", haystack):
        return "slides"
    if re.search(r"画布|canvas|whiteboard|白板|generate_canvas", haystack):
        return "canvas"
    return None


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "_", value.strip())
    return cleaned or "node"


def _unique_id(node_id: str, seen: set) -> str:
    candidate = node_id
    index = 2
    while candidate in seen:
        candidate = f"{node_id}_{index}"
        index += 1
    seen.add(candidate)
    return candidate


def _strip_element_fields(node: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        key: value
        for key, value in node.items()
        if key not in {"style", "type"}
    }
    payload["type"] = node.get("kind") or "process"
    return payload


def _strip_edge_fields(edge: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": edge.get("id"),
        "source": edge.get("source"),
        "target": edge.get("target"),
        "label": edge.get("label", ""),
        "points": edge.get("points", []),
    }
