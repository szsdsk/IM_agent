"""
LLM service implemented with LangChain 1.x chat models.

The public functions at the bottom intentionally keep the old call surface so
the Agent nodes can be migrated without changing API responses.
"""
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from backend.config import settings

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - dependency is declared in requirements.
    ChatOpenAI = None

logger = logging.getLogger(__name__)


class IntentAnalysis(BaseModel):
    intent_summary: str = ""
    content_types: List[str] = Field(default_factory=lambda: ["doc", "slides"])
    presentation_scene: Optional[str] = None
    audience: str = "管理层"
    constraints: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    outline: Optional[Dict[str, Any]] = None


class WorkflowStep(BaseModel):
    module: str
    action: str
    needs_approval: bool = False


class WorkflowPlan(BaseModel):
    goal: str = ""
    presentation_scene: Optional[str] = None
    audience: str = "管理层"
    artifacts: List[str] = Field(default_factory=list)
    steps: List[WorkflowStep] = Field(default_factory=list)


class DeckSlide(BaseModel):
    index: int = 0
    title: str = ""
    layout: str = "content"
    content: Any = ""
    bullets: List[str] = Field(default_factory=list)


class DeckSpecModel(BaseModel):
    title: str = ""
    audience: str = "管理层"
    duration_minutes: int = 5
    theme: str = "business_blue"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    slides: List[DeckSlide] = Field(default_factory=list)


class RehearsalSlide(BaseModel):
    slide_index: int = 0
    speaker_notes: str = ""
    duration_seconds: int = 60
    qa_questions: List[str] = Field(default_factory=list)


class RehearsalPlan(BaseModel):
    slides: List[RehearsalSlide] = Field(default_factory=list)
    total_duration_minutes: int = 5
    tips: List[str] = Field(default_factory=list)


class QAItem(BaseModel):
    slide_index: Optional[int] = None
    question: str = ""
    answer: str = ""


class QAPlan(BaseModel):
    items: List[QAItem] = Field(default_factory=list)


class SlideRevisionPlan(BaseModel):
    target_slide_indexes: List[int] = Field(default_factory=list)
    global_change: bool = False
    summary: str = ""
    revised_slides: List[DeckSlide] = Field(default_factory=list)


class CanvasNode(BaseModel):
    id: str
    text: str
    type: str = "process"


class CanvasEdge(BaseModel):
    source: str
    target: str
    label: str = ""


class CanvasSpec(BaseModel):
    title: str = ""
    diagram_type: str = "flow"
    nodes: List[CanvasNode] = Field(default_factory=list)
    edges: List[CanvasEdge] = Field(default_factory=list)
    layers: List[List[str]] = Field(default_factory=list)


class IMContextSummary(BaseModel):
    summary: str = ""
    topics: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    todos: List[str] = Field(default_factory=list)
    stakeholders: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)


class LLMService:
    """LangChain wrapper for OpenAI-compatible chat completion providers."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.model = model or settings.LLM_MODEL
        self.mock_mode = settings.MOCK_MODE

        if not self.api_key:
            logger.warning("No API key configured, LLM calls will use mock mode")
        if ChatOpenAI is None:
            logger.warning("langchain-openai is not installed; LLM calls will use mock/error mode")

    def _is_mock(self) -> bool:
        return self.mock_mode or not self.api_key or ChatOpenAI is None

    def _model(self, temperature: float = 0.7, max_tokens: Optional[int] = None):
        if ChatOpenAI is None:
            raise RuntimeError("langchain-openai is not installed. Run python -m pip install -r requirements.txt")

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": temperature,
            "timeout": 120.0,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**kwargs)

    def _to_langchain_messages(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
    ) -> List[tuple[str, str]]:
        converted: List[tuple[str, str]] = []
        if system_prompt:
            converted.append(("system", system_prompt))

        role_map = {"user": "human", "assistant": "ai", "system": "system"}
        for message in messages:
            role = role_map.get(message.get("role", "user"), "human")
            converted.append((role, message.get("content", "")))
        return converted

    async def close(self):
        # ChatOpenAI manages HTTP clients internally, so there is no persistent client to close here.
        return None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_response: bool = False,
    ) -> Dict[str, Any]:
        if self._is_mock():
            return self._mock_response(messages)

        try:
            logger.info("LLM Request via LangChain: model=%s, messages_count=%s", self.model, len(messages))
            response = await self._model(temperature=temperature, max_tokens=max_tokens).ainvoke(
                self._to_langchain_messages(messages, system_prompt)
            )
            return {
                "content": str(getattr(response, "content", "") or ""),
                "usage": getattr(response, "usage_metadata", {}) or {},
                "model": self.model,
            }
        except Exception as exc:
            logger.error("LLM Error: %s", str(exc))
            return {"error": str(exc)}

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        if self._is_mock():
            for item in self._mock_stream_gen():
                yield item
            return

        try:
            async for chunk in self._model(temperature=temperature).astream(
                self._to_langchain_messages(messages, system_prompt)
            ):
                content = getattr(chunk, "content", "")
                if content:
                    yield str(content)
        except Exception as exc:
            logger.error("LLM Stream Error: %s", str(exc))
            yield f"Error: {str(exc)}"

    async def structured_chat(
        self,
        messages: List[Dict[str, str]],
        schema: Type[BaseModel],
        system_prompt: Optional[str] = None,
        default: Optional[Dict[str, Any]] = None,
        temperature: float = 0.2,
    ) -> Optional[Dict[str, Any]]:
        if self._is_mock():
            return default

        langchain_messages = self._to_langchain_messages(messages, system_prompt)
        try:
            structured_model = self._model(temperature=temperature).with_structured_output(schema)
            result = await structured_model.ainvoke(langchain_messages)
            if isinstance(result, BaseModel):
                return result.model_dump()
            if isinstance(result, dict):
                return result
        except Exception as exc:
            logger.warning("Structured output failed, falling back to JSON parsing: %s", str(exc))

        response = await self.chat(messages, system_prompt=system_prompt, temperature=temperature)
        if "error" in response:
            return default
        return self._parse_json_content(response.get("content", "")) or default

    async def parse_json(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> Optional[Dict]:
        response = await self.chat(messages, system_prompt, json_response=False)
        if "error" in response:
            return None
        return self._parse_json_content(response.get("content", ""))

    def _parse_json_content(self, content: str) -> Optional[Dict[str, Any]]:
        content = (content or "").strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()
        json_start = content.find("{")
        if json_start >= 0:
            content = content[json_start:]

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON: %s", content[:200])
            return None

    def _mock_response(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        last_message = messages[-1]["content"] if messages else ""
        return {
            "content": f"[Mock] 已处理：{last_message[:80]}...",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "model": "mock",
        }

    def _mock_stream_gen(self):
        yield "[Mock] 正在处理..."
        yield "这是 Mock 响应内容"


llm_service = LLMService()



SCENE_PROFILES: Dict[str, Dict[str, Any]] = {
    "management_briefing": {
        "label": "管理层汇报",
        "audience": "管理层",
        "theme": "business_blue",
        "duration_minutes": 5,
        "outline": ["结论摘要", "业务背景", "核心方案", "风险与决策", "下一步"],
    },
    "project_review": {
        "label": "项目评审",
        "audience": "项目团队 / 评审方",
        "theme": "tech_dark",
        "duration_minutes": 8,
        "outline": ["项目背景", "目标范围", "方案设计", "实施计划", "风险依赖", "评审问题"],
    },
    "proposal_pitch": {
        "label": "方案提案",
        "audience": "客户 / 业务方",
        "theme": "minimal",
        "duration_minutes": 6,
        "outline": ["机会洞察", "问题痛点", "提案方案", "价值收益", "落地路径"],
    },
    "postmortem": {
        "label": "复盘总结",
        "audience": "团队内部",
        "theme": "tech_dark",
        "duration_minutes": 7,
        "outline": ["事件背景", "结果概览", "问题分析", "经验教训", "改进动作"],
    },
    "training": {
        "label": "培训讲解",
        "audience": "学习者",
        "theme": "minimal",
        "duration_minutes": 10,
        "outline": ["学习目标", "核心概念", "操作步骤", "示例演示", "常见问题", "练习与总结"],
    },
}


def get_scene_profile(scene: Optional[str]) -> Dict[str, Any]:
    return SCENE_PROFILES.get(scene or "", SCENE_PROFILES["management_briefing"])


def _clean_content_line(line: str) -> str:
    text = str(line or "").strip()
    for prefix in ("-", "*", "✅", "❌", "🔹", "1.", "2.", "3.", "4.", "5.", "6.", "7."):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text.strip("| ").replace("  ", " ")


def _extract_business_points(content: str, limit: int = 18) -> List[str]:
    keywords = [
        "提前", "风险", "续费", "召回", "投诉", "ARR", "MVP", "规则", "飞书", "客户成功",
        "登录", "工单", "合同", "使用率", "里程碑", "灰度", "准确率", "收益", "目标",
    ]
    points: List[str] = []
    for raw_line in (content or "").splitlines():
        line = _clean_content_line(raw_line)
        if not line or len(line) < 6:
            continue
        if line.startswith(("#", "flowchart", "A[", "B[", "C{")):
            continue
        if set(line) <= {"|", "-", " "}:
            continue
        if any(keyword in line for keyword in keywords) or len(points) < 4:
            points.append(line[:120])
        if len(points) >= limit:
            break
    return points


def _pick_points(points: List[str], keywords: List[str], fallback: List[str], limit: int = 4) -> List[str]:
    picked = [point for point in points if any(keyword in point for keyword in keywords)]
    return (picked or fallback)[:limit]


def _fallback_deck_spec(
    title: str,
    doc_content: str,
    audience: str,
    scene_key: str,
    scene_profile: Dict[str, Any],
) -> Dict[str, Any]:
    points = _extract_business_points(doc_content)
    pain_points = _pick_points(
        points,
        ["滞后", "投诉", "人工", "痛点", "重复", "效率"],
        ["高风险客户识别滞后，挽回窗口不足", "跨部门重复触达影响客户体验", "人工排查占用客户成功大量时间"],
    )
    goals = _pick_points(
        points,
        ["目标", "提前", "召回", "投诉率", "ARR", "人效"],
        ["提前14天识别高风险续费客户", "上线首月高风险客户召回率提升30%", "重复触达投诉率降至5%以下"],
    )
    scope = _pick_points(
        points,
        ["登录", "工单", "合同", "使用率", "风险标签", "跟进话术", "飞书"],
        ["接入登录频次、工单数量、合同到期时间、核心功能使用率四类信号", "提供风险标签、原因解释和标准化跟进建议", "飞书群和工作台双渠道提醒"],
    )
    rollout = _pick_points(
        points,
        ["第1", "第4", "第11", "第13", "两周", "14天", "灰度"],
        ["第1-3天完成需求评审和规则定稿", "第4-10天完成功能开发和联调", "第11-14天完成灰度测试与全量上线"],
    )
    risks = _pick_points(
        points,
        ["误判", "准确率", "跟进不及时", "数据缺失", "风险描述"],
        ["规则准确率低：灰度期10%客户验证并周度优化", "跟进不及时：24小时未跟进触发二次提醒", "数据缺失：标记待确认并人工补全"],
    )

    return {
        "title": "客户续费风险预警MVP项目汇报" if "续费" in doc_content else title,
        "audience": audience,
        "duration_minutes": scene_profile["duration_minutes"],
        "theme": scene_profile["theme"],
        "metadata": {
            "presentation_scene": scene_key,
            "template_profile": scene_key,
            "scene_label": scene_profile["label"],
            "fallback_generated": True,
        },
        "slides": [
            {
                "index": 0,
                "title": "客户续费风险预警MVP项目汇报" if "续费" in doc_content else title,
                "layout": "title",
                "content": "2周上线，提前14天识别高风险客户",
                "bullets": ["2周上线", "提前14天识别高风险客户", "管理层决策汇报"],
            },
            {"index": 1, "title": "项目背景与业务价值", "layout": "content", "content": "\n".join(pain_points + goals[:2]), "bullets": pain_points + goals[:2]},
            {"index": 2, "title": "MVP核心能力", "layout": "content", "content": "\n".join(scope), "bullets": scope},
            {"index": 3, "title": "落地路径与资源投入", "layout": "content", "content": "\n".join(rollout), "bullets": rollout},
            {"index": 4, "title": "预期收益与风险控制", "layout": "two_column", "content": "\n".join(goals + risks), "bullets": goals[:3] + risks[:3]},
            {"index": 5, "title": "Q&A", "layout": "content", "content": "请各位领导指示", "bullets": ["为什么第一版采用规则引擎？", "如何避免重复触达客户？", "投入产出比如何？"]},
        ],
    }


def _enrich_deck_spec(candidate: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    deck = dict(candidate or fallback)
    slides = list(deck.get("slides") or [])
    fallback_slides = fallback.get("slides", [])
    if not slides:
        deck["slides"] = fallback_slides
        return deck

    enriched = []
    for index, slide in enumerate(slides):
        current = dict(slide or {})
        fallback_slide = fallback_slides[index] if index < len(fallback_slides) else {}
        if not current.get("title"):
            current["title"] = fallback_slide.get("title", f"第 {index + 1} 页")
        if not current.get("bullets"):
            current["bullets"] = fallback_slide.get("bullets", [])
        if not current.get("content"):
            current["content"] = fallback_slide.get("content", "\n".join(current.get("bullets", [])))
        current["index"] = current.get("index", index)
        enriched.append(current)
    deck["slides"] = enriched
    deck.setdefault("metadata", {}).update({"content_enriched": True})
    return deck


def _fallback_canvas_spec(title: str, intent: str, doc_content: str, steps: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    combined = f"{intent}\n{doc_content}"
    if any(keyword in combined for keyword in ["续费", "风险", "飞书", "规则引擎"]):
        nodes = [
            {"id": "n1", "text": "采集客户行为与合同数据", "type": "input"},
            {"id": "n2", "text": "规则引擎计算风险分值", "type": "process"},
            {"id": "n3", "text": "判定高/中/低风险等级", "type": "decision"},
            {"id": "n4", "text": "生成风险原因与跟进建议", "type": "process"},
            {"id": "n5", "text": "匹配客户成功经理并拦截重复触达", "type": "owner"},
            {"id": "n6", "text": "推送飞书群与工作台待办", "type": "notification"},
            {"id": "n7", "text": "跟进结果回流优化规则", "type": "feedback"},
        ]
        edges = [
            {"source": "n1", "target": "n2", "label": "四类信号"},
            {"source": "n2", "target": "n3", "label": "分值阈值"},
            {"source": "n3", "target": "n4", "label": "高中风险"},
            {"source": "n4", "target": "n5", "label": "分派负责人"},
            {"source": "n5", "target": "n6", "label": "提醒"},
            {"source": "n6", "target": "n7", "label": "跟进记录"},
            {"source": "n7", "target": "n2", "label": "规则迭代"},
        ]
    else:
        step_labels = [
            str(step.get("action") or step.get("module") or f"Step {index + 1}")
            for index, step in enumerate(steps or [])
        ]
        labels = step_labels or ["接收需求", "沉淀文档", "生成画布", "生成演示稿", "交付归档"]
        nodes = [{"id": f"n{index + 1}", "text": label, "type": "process"} for index, label in enumerate(labels)]
        edges = [
            {"source": nodes[index]["id"], "target": nodes[index + 1]["id"], "label": ""}
            for index in range(max(len(nodes) - 1, 0))
        ]

    return {
        "title": "客户续费风险预警全流程闭环流程图" if "续费" in combined else title or "Agent-Pilot 结构图",
        "diagram_type": "flow",
        "nodes": nodes,
        "edges": edges,
        "layers": [],
    }


def _format_im_context_messages(messages: Optional[List[Dict[str, Any]]], current_intent: str = "") -> str:
    lines = []
    for index, message in enumerate(messages or [], 1):
        role = message.get("role") or message.get("sender") or message.get("user") or "user"
        content = message.get("content") or message.get("text") or message.get("message") or ""
        if content:
            lines.append(f"{index}. {role}: {content}")
    if current_intent:
        lines.append(f"Current request: {current_intent}")
    return "\n".join(lines)


def _fallback_im_context_summary(messages: Optional[List[Dict[str, Any]]], current_intent: str = "") -> Dict[str, Any]:
    text = _format_im_context_messages(messages, current_intent)
    source = text or current_intent
    points = _extract_business_points(source, limit=24)

    stakeholders = []
    for marker in ["产品经理", "销售负责人", "数据同学", "客服负责人", "客户成功", "研发负责人", "设计同学", "运营"]:
        if marker in source and marker not in stakeholders:
            stakeholders.append(marker)

    return {
        "summary": "团队正在讨论客户续费风险预警能力，目标是提前识别高风险客户，并通过文档、画布和汇报材料沉淀方案。" if "续费" in source else (points[0] if points else source[:160]),
        "topics": _pick_points(points, ["续费", "风险", "预警", "飞书", "MVP"], ["客户续费风险预警", "跨部门协同", "MVP落地"]),
        "decisions": _pick_points(points, ["第一版", "规则引擎", "两周", "MVP", "不做"], ["第一版采用规则引擎", "两周内完成MVP"]),
        "requirements": _pick_points(points, ["希望", "需要", "目标", "页面", "信号", "推送"], ["展示风险等级、关键原因和建议跟进动作", "推送到飞书群", "生成客户列表、风险标签和跟进话术"]),
        "risks": _pick_points(points, ["重复", "打扰", "投诉", "复杂", "滞后"], ["避免重复触达客户", "控制MVP范围，不引入复杂机器学习模型"]),
        "todos": _pick_points(points, ["完成", "上线", "评审", "联调", "灰度"], ["确认风险判定规则", "完成MVP开发和灰度验证"]),
        "stakeholders": stakeholders,
        "open_questions": [],
        "source_message_count": len(messages or []),
    }


def format_im_context_for_prompt(summary: Optional[Dict[str, Any]]) -> str:
    if not summary:
        return ""
    sections = [
        ("Summary", [summary.get("summary", "")]),
        ("Topics", summary.get("topics", [])),
        ("Decisions", summary.get("decisions", [])),
        ("Requirements", summary.get("requirements", [])),
        ("Risks", summary.get("risks", [])),
        ("Todos", summary.get("todos", [])),
        ("Stakeholders", summary.get("stakeholders", [])),
        ("Open Questions", summary.get("open_questions", [])),
    ]
    lines = ["# IM Context Summary"]
    for title, values in sections:
        clean_values = [str(value).strip() for value in values if str(value).strip()]
        if not clean_values:
            continue
        lines.append(f"## {title}")
        lines.extend(f"- {value}" for value in clean_values)
    return "\n".join(lines)


SYSTEM_PROMPTS = {
    "intent_parser": """你是一个任务规划助手。用户会通过 IM 输入需求，你需要：
1. 理解用户的核心意图
2. 识别需要生成的内容类型（文档/PPT/画布/总结）
3. 识别目标受众和汇报场景
4. 识别特殊约束或要求

请输出结构化结果，content_types 只能使用 doc、slides、canvas、summary 等短标识。""",

    "planner": """你是一个工作流规划助手。根据用户需求和上下文制定执行计划。

要求：
1. 将任务分解为可执行的子任务
2. 每个子任务包含 action 和 module
3. module 使用 IM_CONTEXT、DOC、DECK、CANVAS、DELIVERY
4. 需要用户确认的节点标记 needs_approval=true
5. 考虑任务依赖关系和执行顺序。""",

    "doc_writer": """你是一个专业的文档撰写助手。根据要求生成高质量文档内容。

文档类型：PRD 或说明文档
要求：
- 结构清晰：背景、目标、需求详情、里程碑、风险
- 语言专业但易懂
- 突出关键信息和决策点
- 使用 Markdown 格式。""",

    "slides_generator": """你是一个演示稿设计助手。根据文档内容生成 PPT 结构。

要求：
- 每页有明确标题和内容
- 控制信息密度，适合演讲展示
- 适当使用图表和可视化建议
- 输出结构化演示稿信息
- theme 字段从 business_blue / tech_dark / minimal 中选择最合适的主题
  - business_blue: 商务蓝色，适合正式汇报
  - tech_dark: 科技深色，适合技术分享
  - minimal: 极简风格，适合简洁报告""",

    "summarizer": """你是一个会议和讨论总结助手。分析 IM 对话上下文，提取核心话题、观点、共识、待办和决策。""",

    "rehearsal": """你是一个演讲排练助手。根据 PPT 内容生成每页讲稿、预计时间、可能的 Q&A 和提示要点。""",

    "qa_generator": """你是一个答辩准备助手。根据演示稿内容生成听众最可能提出的问题和简洁回答。

要求：
- 问题必须和具体页面或整体方案相关
- 回答要适合演示现场口头表达
- 优先覆盖风险、价值、落地、数据、下一步等高频追问。""",

    "slide_revision_planner": """你是一个 PPT 局部修改助手。根据用户反馈，只改需要修改的页面。

要求：
- target_slide_indexes 使用 0-based 下标
- revised_slides 只返回被修改页面的完整内容
- 不受影响的页面不要返回
- 如果反馈明显影响整套演示稿，global_change=true。""",

    "canvas_generator": """你是一个白板/自由画布规划助手。根据用户需求和文档内容生成可视化结构。

要求：
- 适合用流程图、架构图或层级图表达
- diagram_type 使用 flow 或 architecture
- flow 使用 nodes + edges
- architecture 使用 layers。""",
}

SYSTEM_PROMPTS["im_context_summarizer"] = (
    "You are an IM context analysis agent for a multi-agent office assistant. "
    "Extract structured, reusable context from chat history and the current request. "
    "Focus on business background, stakeholder opinions, decisions, requirements, risks, todos, and open questions. "
    "Return concise structured data that downstream document, canvas, and deck agents can use."
)

SYSTEM_PROMPTS["doc_reviser"] = (
    "You revise an existing markdown document based on user feedback. "
    "Keep the original topic and most structure stable, but apply the requested changes clearly. "
    "Return the full revised markdown document."
)

SYSTEM_PROMPTS["slides_reviser"] = (
    "You revise an existing presentation deck based on user feedback. "
    "Preserve unaffected slides when possible and update only the slides impacted by the request. "
    "Return a complete DeckSpec JSON object."
)


async def parse_intent(user_input: str, context: Optional[List[Dict]] = None) -> Dict[str, Any]:
    default = {
        "intent_summary": user_input,
        "content_types": ["doc", "slides"],
        "presentation_scene": None,
        "audience": "管理层",
        "constraints": [],
        "questions": [],
    }
    messages = [{"role": "user", "content": user_input}]
    if context:
        context_text = "\n".join([f"{c.get('role', 'user')}: {c.get('content', '')}" for c in context[-10:]])
        messages = [{"role": "user", "content": f"上下文：\n{context_text}\n\n当前输入：{user_input}"}]

    return await llm_service.structured_chat(
        messages,
        IntentAnalysis,
        system_prompt=SYSTEM_PROMPTS["intent_parser"],
        default=default,
    ) or default


async def summarize_im_context(
    messages: Optional[List[Dict[str, Any]]] = None,
    current_intent: str = "",
) -> Dict[str, Any]:
    default = _fallback_im_context_summary(messages, current_intent)
    content = _format_im_context_messages(messages, current_intent)
    if not content:
        return default

    result = await llm_service.structured_chat(
        [{"role": "user", "content": content[:8000]}],
        IMContextSummary,
        system_prompt=SYSTEM_PROMPTS["im_context_summarizer"],
        default=default,
        temperature=0.1,
    ) or default
    return {
        **default,
        **result,
        "source_message_count": len(messages or []),
    }


async def plan_workflow(intent: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    scene = (context or {}).get("presentation_scene")
    default = {
        "goal": intent,
        "presentation_scene": scene,
        "audience": (context or {}).get("audience", "管理层"),
        "artifacts": ["document", "slides"],
        "steps": [
            {"module": "DOC", "action": "create_doc", "needs_approval": True},
            {"module": "DECK", "action": "generate_slides", "needs_approval": False},
        ],
    }
    content = f"用户需求：{intent}"
    if context:
        content += f"\n\n上下文信息：{json.dumps(context, ensure_ascii=False)}"

    return await llm_service.structured_chat(
        [{"role": "user", "content": content}],
        WorkflowPlan,
        system_prompt=SYSTEM_PROMPTS["planner"],
        default=default,
    ) or default


async def generate_doc_content(title: str, intent: str, outline: Optional[Dict] = None) -> str:
    prompt = f"# 任务\n生成文档标题：{title}\n用户需求：{intent}\n"
    if outline:
        prompt += f"\n大纲：{json.dumps(outline, ensure_ascii=False, indent=2)}"

    response = await llm_service.chat(
        [{"role": "user", "content": prompt}],
        system_prompt=SYSTEM_PROMPTS["doc_writer"],
    )
    return response.get("content", "")


async def generate_deck_spec(
    title: str,
    doc_content: str,
    audience: str = "管理层",
    presentation_scene: Optional[str] = None,
) -> Dict[str, Any]:
    scene_key = presentation_scene or "management_briefing"
    scene_profile = get_scene_profile(scene_key)
    audience = audience or scene_profile["audience"]
    outline = scene_profile["outline"]

    default = {
        "title": title,
        "audience": audience,
        "duration_minutes": scene_profile["duration_minutes"],
        "theme": scene_profile["theme"],
        "metadata": {
            "presentation_scene": scene_key,
            "template_profile": scene_key,
            "scene_label": scene_profile["label"],
        },
        "slides": [
            {"index": 0, "title": title, "layout": "title", "content": scene_profile["label"], "bullets": [scene_profile["label"]]},
            {"index": 1, "title": outline[0], "layout": "content", "content": "开场与结论", "bullets": [f"场景：{scene_profile['label']}", f"受众：{audience}"]},
            {"index": 2, "title": outline[1], "layout": "content", "content": "背景与上下文", "bullets": []},
            {"index": 3, "title": outline[2], "layout": "two_column", "content": "核心结构", "bullets": []},
            {"index": 4, "title": outline[3], "layout": "content", "content": "关键风险或价值", "bullets": []},
            {"index": 5, "title": outline[-1], "layout": "content", "content": "行动与收尾", "bullets": []},
        ],
    }
    default = _fallback_deck_spec(title, doc_content, audience, scene_key, scene_profile)
    prompt = (
        f"文档标题：{title}\n\n"
        f"文档内容：\n{doc_content[:4000]}\n\n"
        f"目标受众：{audience}\n"
        f"演示场景：{scene_key}\n"
        f"场景说明：{scene_profile['label']}\n"
        f"建议结构：{' / '.join(outline)}"
    )


    generated = await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        DeckSpecModel,
        system_prompt=SYSTEM_PROMPTS["slides_generator"],
        default=default,
    ) or default
    return _enrich_deck_spec(generated, default)


async def generate_rehearsal(deck_spec: Dict[str, Any]) -> Dict[str, Any]:
    slides = deck_spec.get("slides", [])
    default = {
        "slides": [
            {"slide_index": i, "speaker_notes": f"讲解第 {i + 1} 页内容。", "duration_seconds": 60, "qa_questions": []}
            for i in range(len(slides))
        ],
        "total_duration_minutes": max(len(slides), 1),
        "tips": ["控制语速", "注意和听众互动"],
    }
    prompt = f"PPT 结构：\n{json.dumps(deck_spec, ensure_ascii=False, indent=2)}"

    return await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        RehearsalPlan,
        system_prompt=SYSTEM_PROMPTS["rehearsal"],
        default=default,
    ) or default


async def generate_qa(deck_spec: Dict[str, Any], rehearsal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    slides = deck_spec.get("slides", [])
    default_items = []
    for index, slide in enumerate(slides[:5]):
        title = slide.get("title", f"第 {index + 1} 页") if isinstance(slide, dict) else f"第 {index + 1} 页"
        default_items.append({
            "slide_index": index,
            "question": f"{title} 这一页最需要提前解释的问题是什么？",
            "answer": "先说明该页的核心结论，再补充关键依据和下一步动作。",
        })

    prompt = (
        f"# DeckSpec\n{json.dumps(deck_spec, ensure_ascii=False, indent=2)[:8000]}\n\n"
        f"# Rehearsal\n{json.dumps(rehearsal or {}, ensure_ascii=False, indent=2)[:4000]}\n\n"
        "# Task\nGenerate likely audience questions and concise answers."
    )

    return await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        QAPlan,
        system_prompt=SYSTEM_PROMPTS["qa_generator"],
        default={"items": default_items},
    ) or {"items": default_items}


async def revise_targeted_slides(
    title: str,
    original_slides: List[Dict[str, Any]],
    feedback: str,
    target_slide_indexes: List[int],
    audience: str = "management",
    doc_content: str = "",
) -> Dict[str, Any]:
    valid_targets = [
        index for index in target_slide_indexes
        if 0 <= index < len(original_slides)
    ]
    if not valid_targets:
        return {
            "target_slide_indexes": [],
            "global_change": True,
            "summary": "No explicit slide target found; use full deck revision.",
            "revised_slides": [],
        }

    target_slides = [original_slides[index] for index in valid_targets]
    default_slides = []
    for slide in target_slides:
        revised = dict(slide)
        bullets = list(revised.get("bullets") or [])
        if feedback and not any(feedback in str(item) for item in bullets):
            bullets.append(f"修改要求：{feedback}")
        revised["bullets"] = bullets
        default_slides.append(revised)

    prompt = (
        f"# Deck Title\n{title}\n\n"
        f"# Audience\n{audience}\n\n"
        f"# User Feedback\n{feedback}\n\n"
        f"# Target Slide Indexes\n{valid_targets}\n\n"
        f"# Target Slides\n{json.dumps(target_slides, ensure_ascii=False, indent=2)}\n\n"
        f"# Full Deck Context\n{json.dumps(original_slides, ensure_ascii=False, indent=2)[:6000]}\n\n"
        f"# Supporting Document\n{doc_content[:3000]}\n\n"
        "# Task\nReturn only the revised target slides."
    )

    return await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        SlideRevisionPlan,
        system_prompt=SYSTEM_PROMPTS["slide_revision_planner"],
        default={
            "target_slide_indexes": valid_targets,
            "global_change": False,
            "summary": "Applied feedback to selected slides.",
            "revised_slides": default_slides,
        },
    ) or {
        "target_slide_indexes": valid_targets,
        "global_change": False,
        "summary": "Applied feedback to selected slides.",
        "revised_slides": default_slides,
    }


async def generate_canvas_spec(
    title: str,
    intent: str,
    doc_content: str = "",
    steps: Optional[List[Dict[str, Any]]] = None,
    use_llm: bool = True,
) -> Dict[str, Any]:
    step_labels = [
        str(step.get("action") or step.get("module") or f"Step {index + 1}")
        for index, step in enumerate(steps or [])
    ]
    default_nodes = [
        {"id": f"n{index + 1}", "text": label, "type": "process"}
        for index, label in enumerate(step_labels or ["接收输入", "生成文档", "生成演示稿", "交付结果"])
    ]
    default_edges = [
        {"source": default_nodes[index]["id"], "target": default_nodes[index + 1]["id"], "label": ""}
        for index in range(max(len(default_nodes) - 1, 0))
    ]
    default = {
        "title": title or "Agent-Pilot 结构图",
        "diagram_type": "flow",
        "nodes": default_nodes,
        "edges": default_edges,
        "layers": [],
    }
    default = _fallback_canvas_spec(title, intent, doc_content, steps)
    if not use_llm:
        return default

    prompt = (
        f"# Title\n{title}\n\n"
        f"# User Intent\n{intent}\n\n"
        f"# Workflow Steps\n{json.dumps(steps or [], ensure_ascii=False, indent=2)}\n\n"
        f"# Document\n{doc_content[:4000]}\n\n"
        "# Task\nCreate a diagram spec for an AFFiNE canvas."
    )

    return await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        CanvasSpec,
        system_prompt=SYSTEM_PROMPTS["canvas_generator"],
        default=default,
    ) or default


async def revise_doc_content(title: str, original_content: str, feedback: str) -> str:
    prompt = (
        f"# Document Title\n{title}\n\n"
        f"# User Feedback\n{feedback}\n\n"
        f"# Original Document\n{original_content[:8000]}\n\n"
        "# Task\nReturn the full revised markdown document."
    )

    response = await llm_service.chat(
        [{"role": "user", "content": prompt}],
        system_prompt=SYSTEM_PROMPTS["doc_reviser"],
        temperature=0.3,
    )
    return response.get("content", "")


async def revise_deck_spec(
    title: str,
    original_slides: List[Dict[str, Any]],
    feedback: str,
    audience: str = "management",
    doc_content: str = "",
) -> Dict[str, Any]:
    default = {
        "title": title,
        "audience": audience,
        "duration_minutes": 5,
        "theme": "business_blue",
        "slides": original_slides,
    }
    prompt = (
        f"# Deck Title\n{title}\n\n"
        f"# User Feedback\n{feedback}\n\n"
        f"# Original Slides\n{json.dumps(original_slides, ensure_ascii=False, indent=2)}\n\n"
        f"# Supporting Document\n{doc_content[:4000]}\n\n"
        "# Task\nReturn a complete revised DeckSpec JSON object."
    )

    return await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        DeckSpecModel,
        system_prompt=SYSTEM_PROMPTS["slides_reviser"],
        default=default,
    ) or default
