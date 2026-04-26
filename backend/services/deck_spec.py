"""
DeckSpec - PPT 中间格式定义
统一的演示稿描述格式，支持 Slidev 和 PptxGenJS 两种渲染器
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json


@dataclass
class SlideSpec:
    """单页幻灯片定义"""
    index: int
    title: str
    layout: str = "content"  # title, content, two_column, diagram, image, blank
    content: Optional[Dict] = None
    speaker_notes: str = ""
    duration_seconds: int = 60
    diagram_ref: Optional[str] = None  # e.g., "canvas:workflow-001"
    bullets: List[str] = field(default_factory=list)
    image_ref: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "SlideSpec":
        return cls(
            index=data.get("index", 0),
            title=data.get("title", ""),
            layout=data.get("layout", "content"),
            content=data.get("content"),
            speaker_notes=data.get("speaker_notes", ""),
            duration_seconds=data.get("duration_seconds", 60),
            diagram_ref=data.get("diagram_ref"),
            bullets=data.get("bullets", []),
            image_ref=data.get("image_ref"),
        )


@dataclass
class DeckSpec:
    """完整演示稿定义"""
    title: str
    audience: str = "管理层"
    duration_minutes: int = 5
    slides: List[SlideSpec] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def add_slide(
        self,
        title: str,
        layout: str = "content",
        bullets: List[str] = None,
        speaker_notes: str = "",
        **kwargs
    ) -> "DeckSpec":
        """链式添加幻灯片"""
        slide = SlideSpec(
            index=len(self.slides),
            title=title,
            layout=layout,
            bullets=bullets or [],
            speaker_notes=speaker_notes,
            **kwargs
        )
        self.slides.append(slide)
        return self

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "audience": self.audience,
            "duration_minutes": self.duration_minutes,
            "slides": [s.to_dict() for s in self.slides],
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict) -> "DeckSpec":
        return cls(
            title=data.get("title", ""),
            audience=data.get("audience", "管理层"),
            duration_minutes=data.get("duration_minutes", 5),
            slides=[SlideSpec.from_dict(s) for s in data.get("slides", [])],
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "DeckSpec":
        return cls.from_dict(json.loads(json_str))


# ============ Default Templates ============

def create_default_deck(title: str, audience: str = "管理层") -> DeckSpec:
    """创建默认演示稿结构"""
    deck = DeckSpec(title=title, audience=audience)

    deck.add_slide(
        title="封面",
        layout="title",
        speaker_notes="开场白：自我介绍 + 主题引入",
    )

    deck.add_slide(
        title="背景与痛点",
        layout="content",
        bullets=[
            "痛点 1：...",
            "痛点 2：...",
            "痛点 3：...",
        ],
        speaker_notes="重点强调问题带来的影响",
    )

    deck.add_slide(
        title="目标与价值",
        layout="content",
        bullets=[
            "目标 1：...",
            "预期收益：...",
        ],
        speaker_notes="量化目标，突出ROI",
    )

    deck.add_slide(
        title="解决方案",
        layout="diagram",
        speaker_notes="结合流程图/架构图讲解",
    )

    deck.add_slide(
        title="实施计划",
        layout="content",
        bullets=[
            "Phase 1：...",
            "Phase 2：...",
            "Phase 3：...",
        ],
        speaker_notes="时间线清晰，关键里程碑突出",
    )

    deck.add_slide(
        title="下一步与 Q&A",
        layout="content",
        bullets=[
            "待确认事项：...",
            "下一步行动：...",
        ],
        speaker_notes="开放提问，记录反馈",
    )

    return deck


def create_prd_deck(prd_content: str, title: str, audience: str = "管理层") -> DeckSpec:
    """从 PRD 内容创建演示稿"""
    deck = DeckSpec(title=title, audience=audience)

    deck.add_slide(title="封面", layout="title")

    # 解析 PRD 结构
    sections = parse_prd_sections(prd_content)

    for section_title, section_content in sections.items():
        if section_title == "背景":
            deck.add_slide(title="背景与目标", layout="content", bullets=section_content)
        elif section_title == "需求":
            deck.add_slide(title="核心需求", layout="content", bullets=section_content)
        elif section_title == "计划":
            deck.add_slide(title="实施计划", layout="content", bullets=section_content)
        elif section_title == "风险":
            deck.add_slide(title="风险与依赖", layout="content", bullets=section_content)

    deck.add_slide(title="下一步", layout="content")
    deck.add_slide(title="Q&A", layout="title")

    return deck


def parse_prd_sections(content: str) -> Dict[str, List[str]]:
    """解析 PRD 内容为结构化 sections"""
    sections = {}
    current_section = None
    current_items = []

    for line in content.split("\n"):
        line = line.strip()

        if line.startswith("## ") or line.startswith("### "):
            # 保存上一个 section
            if current_section and current_items:
                sections[current_section] = current_items

            current_section = line.replace("## ", "").replace("### ", "").strip()
            current_items = []
        elif line.startswith("- ") or line.startswith("* "):
            current_items.append(line[2:])
        elif line and current_section:
            current_items.append(line)

    # 保存最后一个 section
    if current_section and current_items:
        sections[current_section] = current_items

    return sections


# ============ Validation ============

def validate_deck_spec(deck: DeckSpec) -> List[str]:
    """验证 DeckSpec，返回错误列表"""
    errors = []

    if not deck.title:
        errors.append("Deck title is required")

    if not deck.slides:
        errors.append("At least one slide is required")

    if deck.duration_minutes <= 0:
        errors.append("Duration must be positive")

    for i, slide in enumerate(deck.slides):
        if not slide.title:
            errors.append(f"Slide {i} missing title")

        valid_layouts = ["title", "content", "two_column", "diagram", "image", "blank"]
        if slide.layout not in valid_layouts:
            errors.append(f"Slide {i} has invalid layout: {slide.layout}")

    return errors
