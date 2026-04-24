"""
Delivery Service - 交付与归档服务
生成交付卡片、聚合链接、处理归档
"""
import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, asdict

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DeliveryCard:
    """交付卡片"""
    task_id: str
    title: str
    status: str
    document: Optional[Dict] = None
    slides: Optional[Dict] = None
    canvas: Optional[Dict] = None
    rehearsal: Optional[Dict] = None
    links: Dict[str, str] = None
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        if self.links is None:
            self.links = {}

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = ["# 🎉 Agent-Pilot 任务完成！\n"]

        lines.append(f"**任务**: {self.title}")
        lines.append(f"**状态**: {'✅ 成功' if self.status == 'completed' else '❌ 失败'}")
        lines.append(f"**时间**: {self.created_at}\n")

        if self.document:
            lines.append("## 📄 文档")
            lines.append(f"- **标题**: {self.document.get('title', '未命名')}")
            if self.document.get("preview"):
                lines.append(f"- **预览**: {self.document['preview'][:200]}...")
            if self.document.get("link"):
                lines.append(f"- **链接**: {self.document['link']}")

        if self.slides:
            lines.append("\n## 📊 演示稿")
            lines.append(f"- **标题**: {self.slides.get('title', '未命名')}")
            lines.append(f"- **页数**: {self.slides.get('slides_count', 0)} 页")
            if self.slides.get("link"):
                lines.append(f"- **预览**: {self.slides['link']}")
            if self.slides.get("pdf_link"):
                lines.append(f"- **PDF**: {self.slides['pdf_link']}")
            if self.slides.get("pptx_link"):
                lines.append(f"- **PPTX**: {self.slides['pptx_link']}")

        if self.canvas:
            lines.append("\n## 🎨 架构图/画布")
            if self.canvas.get("link"):
                lines.append(f"- **链接**: {self.canvas['link']}")

        if self.rehearsal:
            lines.append("\n## 🎤 排练材料")
            total = self.rehearsal.get("total_duration_minutes", 0)
            lines.append(f"- **预计时长**: {total} 分钟")
            if self.rehearsal.get("tips"):
                lines.append("- **提示**:")
                for tip in self.rehearsal["tips"][:3]:
                    lines.append(f"  - {tip}")

        if self.links:
            lines.append("\n## 🔗 快速链接")
            for name, url in self.links.items():
                lines.append(f"- [{name}]({url})")

        lines.append("\n---\n")
        lines.append("*由 Agent-Pilot 自动生成*")

        return "\n".join(lines)

    def to_rocketchat_card(self) -> str:
        """转换为 Rocket.Chat 卡片格式"""
        parts = [f"*Agent-Pilot 任务完成*"]

        if self.document:
            parts.append(f"📄 文档: {self.document.get('title', '未命名')}")

        if self.slides:
            count = self.slides.get('slides_count', 0)
            parts.append(f"📊 演示稿: {self.slides.get('title', '未命名')} ({count} 页)")

        if self.canvas:
            parts.append("🎨 架构图: 已生成")

        parts.append("\n💡 输入「排练」获取演讲提示")
        parts.append("📥 输入「导出」下载文件")

        return "\n".join(parts)


@dataclass
class ArchiveRecord:
    """归档记录"""
    archive_id: str
    task_id: str
    title: str
    document_id: Optional[str] = None
    slide_id: Optional[str] = None
    canvas_id: Optional[str] = None
    files: List[Dict] = None
    im_thread_id: Optional[str] = None
    created_at: str = None
    tags: List[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        if self.files is None:
            self.files = []
        if self.tags is None:
            self.tags = []

    def to_dict(self) -> Dict:
        return asdict(self)


class DeliveryService:
    """交付服务"""

    def __init__(self):
        self._storage_dir = "./data/delivery"
        self._archive_file = "./data/delivery/archive.json"

    async def create_delivery_card(
        self,
        task_id: str,
        title: str,
        status: str,
        document: Optional[Dict] = None,
        slides: Optional[Dict] = None,
        canvas: Optional[Dict] = None,
        rehearsal: Optional[Dict] = None,
        links: Optional[Dict[str, str]] = None,
    ) -> DeliveryCard:
        """创建交付卡片"""
        card = DeliveryCard(
            task_id=task_id,
            title=title,
            status=status,
            document=document,
            slides=slides,
            canvas=canvas,
            rehearsal=rehearsal,
            links=links or {},
        )

        logger.info(f"Created delivery card for task {task_id}")
        return card

    async def save_delivery(self, card: DeliveryCard) -> Dict[str, Any]:
        """保存交付记录"""
        import os
        os.makedirs(self._storage_dir, exist_ok=True)

        filename = f"{card.task_id}_delivery.json"
        filepath = os.path.join(self._storage_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(card.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"Saved delivery to {filepath}")
        return {"success": True, "filepath": filepath}

    async def create_archive(
        self,
        task_id: str,
        title: str,
        document_id: Optional[str] = None,
        slide_id: Optional[str] = None,
        canvas_id: Optional[str] = None,
        files: List[Dict] = None,
        im_thread_id: Optional[str] = None,
        tags: List[str] = None,
    ) -> ArchiveRecord:
        """创建归档记录"""
        import time
        archive_id = f"archive_{int(time.time() * 1000)}"

        record = ArchiveRecord(
            archive_id=archive_id,
            task_id=task_id,
            title=title,
            document_id=document_id,
            slide_id=slide_id,
            canvas_id=canvas_id,
            files=files or [],
            im_thread_id=im_thread_id,
            tags=tags or [],
        )

        # 保存归档记录
        self._save_archive_record(record)

        logger.info(f"Created archive {archive_id} for task {task_id}")
        return record

    def _save_archive_record(self, record: ArchiveRecord):
        """保存归档记录到文件"""
        import os
        os.makedirs(self._storage_dir, exist_ok=True)

        # 读取现有归档
        archives = []
        if os.path.exists(self._archive_file):
            try:
                with open(self._archive_file, "r", encoding="utf-8") as f:
                    archives = json.load(f)
            except:
                archives = []

        # 添加新记录
        archives.append(record.to_dict())

        # 保存
        with open(self._archive_file, "w", encoding="utf-8") as f:
            json.dump(archives, f, ensure_ascii=False, indent=2)

    async def get_archive(self, archive_id: str) -> Optional[ArchiveRecord]:
        """获取归档记录"""
        import os
        if not os.path.exists(self._archive_file):
            return None

        try:
            with open(self._archive_file, "r", encoding="utf-8") as f:
                archives = json.load(f)

            for record in archives:
                if record.get("archive_id") == archive_id:
                    return ArchiveRecord(**record)
        except:
            pass

        return None

    async def list_archives(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> List[ArchiveRecord]:
        """列出归档记录"""
        import os
        if not os.path.exists(self._archive_file):
            return []

        try:
            with open(self._archive_file, "r", encoding="utf-8") as f:
                archives = json.load(f)

            records = [
                ArchiveRecord(**a)
                for a in archives[offset:offset + limit]
            ]
            return records
        except:
            return []


# 全局实例
delivery_service = DeliveryService()


# ============ Convenience Functions ============

async def build_delivery(
    task_id: str,
    intent: str,
    doc_content: Optional[Dict] = None,
    slides_content: Optional[Dict] = None,
    canvas_content: Optional[Dict] = None,
    rehearsal: Optional[Dict] = None,
) -> DeliveryCard:
    """构建交付卡片"""
    status = "failed" if (doc_content or slides_content) is None else "completed"

    card = await delivery_service.create_delivery_card(
        task_id=task_id,
        title=intent,
        status=status,
        document=doc_content,
        slides=slides_content,
        canvas=canvas_content,
        rehearsal=rehearsal,
    )

    await delivery_service.save_delivery(card)

    return card


async def archive_task(
    task_id: str,
    title: str,
    doc_id: Optional[str] = None,
    slide_id: Optional[str] = None,
    canvas_id: Optional[str] = None,
    files: List[Dict] = None,
) -> ArchiveRecord:
    """归档任务"""
    return await delivery_service.create_archive(
        task_id=task_id,
        title=title,
        document_id=doc_id,
        slide_id=slide_id,
        canvas_id=canvas_id,
        files=files,
    )
