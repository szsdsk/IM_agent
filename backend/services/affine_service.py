"""
AFFiNE Service - 文档与画布集成
支持 BlockSuite Yjs 协同、AFFiNE API 操作
"""
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class AFFiNEService:
    """AFFiNE API 客户端"""

    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.url = (url or settings.AFFINE_URL or "https://affine.example.com").rstrip("/")
        self.token = token or settings.AFFINE_TOKEN
        self._client: Optional[httpx.AsyncClient] = None

        if not self.token:
            logger.warning("AFFiNE not configured, using mock mode")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = httpx.AsyncClient(
                base_url=self.url,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.url)

    async def create_workspace(self, name: str) -> Dict[str, Any]:
        """创建工作空间"""
        if not self.is_configured:
            return self._mock_response("workspace", {"id": f"ws_{datetime.utcnow().timestamp()}"})

        try:
            response = await self.client.post(
                "/api/workspaces",
                json={"name": name},
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            logger.error(f"Create workspace error: {e}")
            return {"success": False, "error": str(e)}

    async def create_page(self, workspace_id: str, title: str) -> Dict[str, Any]:
        """创建页面（文档）"""
        if not self.is_configured:
            page_id = f"page_{datetime.utcnow().timestamp()}"
            return self._mock_response("page", {
                "id": page_id,
                "title": title,
                "workspace_id": workspace_id,
            })

        try:
            response = await self.client.post(
                f"/api/workspaces/{workspace_id}/pages",
                json={"title": title},
            )
            response.raise_for_status()
            data = response.json()
            return {"success": True, "page_id": data.get("id"), "title": title}
        except Exception as e:
            logger.error(f"Create page error: {e}")
            return {"success": False, "error": str(e)}

    async def update_page_content(
        self,
        page_id: str,
        blocks: List[Dict],
        after_block_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        更新页面内容（Block Operation）
        blocks: [{"type": "heading", "text": "...", "children": []}, ...]
        """
        if not self.is_configured:
            return self._mock_response("update", {"page_id": page_id, "blocks_updated": len(blocks)})

        try:
            payload = {
                "operations": [
                    {
                        "type": "insert",
                        "blocks": blocks,
                        "afterBlockId": after_block_id,
                    }
                ]
            }

            response = await self.client.patch(
                f"/api/pages/{page_id}/blocks",
                json=payload,
            )
            response.raise_for_status()
            return {"success": True, "page_id": page_id, "blocks_updated": len(blocks)}
        except Exception as e:
            logger.error(f"Update page error: {e}")
            return {"success": False, "error": str(e)}

    async def get_page(self, page_id: str) -> Dict[str, Any]:
        """获取页面内容"""
        if not self.is_configured:
            return self._mock_response("page", {
                "id": page_id,
                "title": "Mock Document",
                "blocks": [],
            })

        try:
            response = await self.client.get(f"/api/pages/{page_id}")
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            logger.error(f"Get page error: {e}")
            return {"success": False, "error": str(e)}

    async def create_canvas(self, workspace_id: str, name: str) -> Dict[str, Any]:
        """创建画布"""
        if not self.is_configured:
            canvas_id = f"canvas_{datetime.utcnow().timestamp()}"
            return self._mock_response("canvas", {
                "id": canvas_id,
                "name": name,
                "workspace_id": workspace_id,
            })

        try:
            response = await self.client.post(
                f"/api/workspaces/{workspace_id}/canvases",
                json={"name": name},
            )
            response.raise_for_status()
            data = response.json()
            return {"success": True, "canvas_id": data.get("id"), "name": name}
        except Exception as e:
            logger.error(f"Create canvas error: {e}")
            return {"success": False, "error": str(e)}

    async def add_canvas_elements(
        self,
        canvas_id: str,
        elements: List[Dict],
    ) -> Dict[str, Any]:
        """
        添加画布元素
        elements: [{"type": "rect", "x": 100, "y": 100, "width": 200, "height": 100, "text": "..."}, ...]
        """
        if not self.is_configured:
            return self._mock_response("canvas", {
                "canvas_id": canvas_id,
                "elements_added": len(elements),
            })

        try:
            response = await self.client.post(
                f"/api/canvases/{canvas_id}/elements",
                json={"elements": elements},
            )
            response.raise_for_status()
            return {"success": True, "canvas_id": canvas_id, "elements_added": len(elements)}
        except Exception as e:
            logger.error(f"Add canvas elements error: {e}")
            return {"success": False, "error": str(e)}

    async def create_flow_diagram(
        self,
        canvas_id: str,
        title: str,
        nodes: List[Dict],
        edges: List[Dict],
    ) -> Dict[str, Any]:
        """
        创建流程图
        nodes: [{"id": "n1", "text": "开始", "type": "start"}, ...]
        edges: [{"from": "n1", "to": "n2", "label": ""}, ...]
        """
        elements = []

        # 添加节点
        for i, node in enumerate(nodes):
            elements.append({
                "type": "rect",
                "x": 100 + (i % 3) * 250,
                "y": 100 + (i // 3) * 150,
                "width": 200,
                "height": 80,
                "text": node.get("text", node.get("id", "")),
                "fill": "#e3f2fd" if node.get("type") == "start" else "#fff3e0",
                "stroke": "#1976d2" if node.get("type") == "start" else "#ff9800",
            })

        # 添加连线
        for edge in edges:
            elements.append({
                "type": "arrow",
                "from": edge.get("from"),
                "to": edge.get("to"),
                "label": edge.get("label", ""),
            })

        return await self.add_canvas_elements(canvas_id, elements)

    async def create_architecture_diagram(
        self,
        canvas_id: str,
        layers: List[List[str]],
    ) -> Dict[str, Any]:
        """
        创建架构图
        layers: [["前端", "React"], ["后端", "FastAPI"], ["数据库", "PostgreSQL"]]
        """
        elements = []

        for row, layer in enumerate(layers):
            y = 100 + row * 120
            for col, item in enumerate(layer):
                x = 200 + col * 250
                elements.append({
                    "type": "rect",
                    "x": x,
                    "y": y,
                    "width": 200,
                    "height": 80,
                    "text": item,
                    "fill": "#e8f5e9",
                    "stroke": "#4caf50",
                })

        return await self.add_canvas_elements(canvas_id, elements)

    def _mock_response(self, action: str, data: Dict) -> Dict[str, Any]:
        return {"success": True, **data}

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None


# 全局实例
affine_service = AFFiNEService()


# ============ Block Operation Utilities ============

def markdown_to_blocks(markdown: str) -> List[Dict]:
    """
    将 Markdown 转换为 BlockSuite blocks
    """
    blocks = []
    lines = markdown.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line:
            i += 1
            continue

        # 标题
        if line.startswith("### "):
            blocks.append({"type": "heading3", "text": line[4:]})
        elif line.startswith("## "):
            blocks.append({"type": "heading2", "text": line[3:]})
        elif line.startswith("# "):
            blocks.append({"type": "heading1", "text": line[2:]})
        # 列表
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append({"type": "bulleted", "text": line[2:]})
        elif line.startswith("1. ") or line.startswith("1) "):
            blocks.append({"type": "numbered", "text": line[3:]})
        # 代码块
        elif line.startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.append({"type": "code", "text": "\n".join(code_lines)})
        # 引用
        elif line.startswith("> "):
            blocks.append({"type": "quote", "text": line[2:]})
        # 分隔线
        elif line == "---" or line == "***":
            blocks.append({"type": "divider"})
        # 普通段落
        else:
            blocks.append({"type": "paragraph", "text": line})

        i += 1

    return blocks


def generate_prd_blocks(
    title: str,
    intent: str,
    content: str,
) -> List[Dict]:
    """
    生成 PRD 文档的 Block 列表
    """
    blocks = [
        {"type": "heading1", "text": title},
        {"type": "paragraph", "text": f"**需求背景**: {intent}"},
        {"type": "divider"},
        {"type": "heading2", "text": "核心需求"},
    ]

    # 解析内容中的列表
    in_list = False
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            in_list = False
            continue

        if line.startswith("- "):
            if not in_list:
                blocks.append({"type": "bulleted", "text": line[2:]})
            else:
                blocks.append({"type": "bulleted", "text": line[2:]})
            in_list = True
        else:
            in_list = False
            if line.startswith("## "):
                blocks.append({"type": "heading2", "text": line[3:]})
            elif line.startswith("# "):
                blocks.append({"type": "heading1", "text": line[2:]})
            elif line:
                blocks.append({"type": "paragraph", "text": line})

    blocks.extend([
        {"type": "divider"},
        {"type": "heading2", "text": "风险与约束"},
        {"type": "paragraph", "text": "（待补充）"},
    ])

    return blocks


# ============ Doc Tool Extension ============

async def create_affine_doc(
    title: str,
    content: str,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建 AFFiNE 文档"""
    if settings.MOCK_MODE or not affine_service.is_configured:
        import time
        return {
            "success": True,
            "doc_id": f"doc_{int(time.time() * 1000)}",
            "title": title,
        }

    # 转换 Markdown 为 Blocks
    blocks = markdown_to_blocks(content)

    # 创建页面
    result = await affine_service.create_page(
        workspace_id=workspace_id or "default",
        title=title,
    )

    if result.get("success"):
        page_id = result.get("page_id")
        # 插入内容
        await affine_service.update_page_content(page_id, blocks)
        return result

    return result


async def update_affine_doc(
    doc_id: str,
    content: str,
) -> Dict[str, Any]:
    """更新 AFFiNE 文档"""
    if settings.MOCK_MODE or not affine_service.is_configured:
        return {"success": True, "doc_id": doc_id, "updated": True}

    blocks = markdown_to_blocks(content)
    return await affine_service.update_page_content(doc_id, blocks)


async def get_affine_doc(doc_id: str) -> Dict[str, Any]:
    """获取 AFFiNE 文档"""
    if settings.MOCK_MODE or not affine_service.is_configured:
        return {"success": True, "doc_id": doc_id, "title": "Mock", "content": ""}

    return await affine_service.get_page(doc_id)
