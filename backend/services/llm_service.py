"""
LLM service implemented with LangChain 1.x chat models.

The public functions at the bottom intentionally keep the old call surface so
the Agent nodes can be migrated without changing API responses.
"""
import json
import logging
import re
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
    visual_profile: Optional[str] = None
    layout_variant: Optional[str] = None
    highlight_metrics: List[Dict[str, str]] = Field(default_factory=list)
    sections: List[Dict[str, str]] = Field(default_factory=list)
    chart: Optional[Dict[str, Any]] = None
    timeline: List[Dict[str, str]] = Field(default_factory=list)
    process_steps: List[Dict[str, str]] = Field(default_factory=list)


class DeckSpecModel(BaseModel):
    title: str = ""
    audience: str = "管理层"
    duration_minutes: int = 5
    theme: str = "business_blue"
    visual_profile: Optional[str] = None
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
    text = re.sub(r"^\[Mock\]\s*已处理[:：]\s*", "", text).strip()
    for prefix in ("-", "*", "✅", "❌", "🔹", "1.", "2.", "3.", "4.", "5.", "6.", "7."):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text.strip("| ").replace("  ", " ")


def _strip_speaker_prefix(text: str) -> str:
    return re.sub(
        r"^(产品经理|业务负责人|研发负责人|算法同学|设计同学|客服负责人|法务同学|项目经理|销售负责人|数据同学|运营同学|运营|客户成功经理|客户成功)[:：]\s*",
        "",
        str(text or "").strip(),
    )


def _looks_like_instruction_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return True
    instruction_prefixes = (
        "# 任务",
        "请根据",
        "请先",
        "不用生成",
        "生成文档标题",
        "用户需求",
        "飞书群聊上下文",
        "群聊上下文",
        "实际内容",
        "产出要求",
        "输出要求",
    )
    if text.startswith(instruction_prefixes):
        return True
    return bool(re.match(r"^\d+\.\s*(文档|画布|PPT|讲稿|演示稿)", text))


def _derive_topic(title: str = "", source: str = "") -> str:
    text = f"{title}\n{source}"
    patterns = [
        r"上线[“\"]([^”\"]{2,40})[”\"]",
        r"主题是[“\"]([^”\"]{2,40})[”\"]",
        r"主题为[“\"]([^”\"]{2,40})[”\"]",
        r"围绕[“\"]([^”\"]{2,40})[”\"]",
        r"“([^”]{2,40})”",
        r"\"([^\"]{2,40})\"",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()

    clean_title = str(title or "").strip()
    if clean_title and len(clean_title) <= 40 and not _looks_like_instruction_line(clean_title):
        return clean_title

    for raw_line in text.splitlines():
        line = _clean_content_line(raw_line)
        if not line or _looks_like_instruction_line(line):
            continue
        if "：" in line:
            line = line.split("：", 1)[1].strip()
        elif ":" in line:
            line = line.split(":", 1)[1].strip()
        if line:
            return line[:32]
    return "项目方案"


def _extract_requested_flow_nodes(source: str) -> List[str]:
    match = re.search(r"画布用流程图表达[：:]\s*([^\n。]+)", source or "")
    if not match:
        return []
    raw = match.group(1)
    parts = [
        item.strip(" 。；;")
        for item in re.split(r"、|，|,|→|->", raw)
        if item.strip(" 。；;")
    ]
    return parts[:8]


def _extract_business_points(content: str, limit: int = 18) -> List[str]:
    keywords = [
        "提前", "风险", "续费", "召回", "投诉", "ARR", "MVP", "规则", "飞书", "客户成功",
        "登录", "工单", "合同", "使用率", "里程碑", "灰度", "准确率", "收益", "目标",
        "会议", "纪要", "行动项", "发言人", "录音", "权限", "合规", "脱敏", "审计",
        "多端", "移动端", "桌面端", "效率", "遗漏", "任务", "低置信度", "确认",
        "回滚", "试点", "上线", "两周", "负责人", "截止时间", "依赖",
    ]
    points: List[str] = []
    seen: set[str] = set()
    for raw_line in (content or "").splitlines():
        line = _clean_content_line(raw_line)
        if not line or len(line) < 6:
            continue
        if _looks_like_instruction_line(line):
            continue
        line = _strip_speaker_prefix(line)
        if line.startswith(("#", "flowchart", "A[", "B[", "C{")):
            continue
        if set(line) <= {"|", "-", " "}:
            continue
        if line in seen:
            continue
        if any(keyword in line for keyword in keywords) or len(points) < 4:
            seen.add(line)
            points.append(line[:120])
        if len(points) >= limit:
            break
    return points


def _pick_points(points: List[str], keywords: List[str], fallback: List[str], limit: int = 4) -> List[str]:
    picked = []
    for point in points:
        if any(keyword in point for keyword in keywords) and point not in picked:
            picked.append(point)
    values = picked or fallback
    deduped = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped[:limit]


def _merge_points(*groups: List[str], limit: int = 6) -> List[str]:
    merged: List[str] = []
    for group in groups:
        for item in group:
            if item and item not in merged:
                merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def _fallback_doc_content(title: str, intent: str, outline: Optional[Dict] = None) -> str:
    topic = _derive_topic(title, intent)
    points = _extract_business_points(intent, limit=8)
    if not points:
        points = [topic]

    outline_sections = []
    if isinstance(outline, dict):
        for value in outline.values():
            if isinstance(value, list):
                outline_sections.extend(str(item) for item in value[:4])
            elif value:
                outline_sections.append(str(value))

    goals = _pick_points(points, ["目标", "提升", "降低", "效率", "遗漏", "及时"], [f"围绕「{topic}」提升协作效率和交付质量"], limit=4)
    scope = _pick_points(points, ["第一版", "覆盖", "MVP", "桌面端", "移动端", "同步", "抽取"], points[:4], limit=5)
    compliance = _pick_points(points, ["权限", "合规", "敏感", "脱敏", "审计"], ["继承原有权限边界，对敏感内容给出脱敏提示，并记录关键操作审计"], limit=3)
    risks = _pick_points(points, ["风险", "低置信度", "误判", "不做", "回滚"], ["低置信度结果需要人工确认，试点期保留人工编辑和回滚方案"], limit=4)
    milestones = _pick_points(points, ["两周", "试点", "上线", "里程碑", "第"], ["两周内完成 MVP，并在小范围团队试点后复盘"], limit=4)

    lines = [f"# {topic} 发布评审文档", "", "## 背景与目标"]
    lines.extend(f"- {point}" for point in goals)
    lines.append("")
    lines.append("## 用户角色与关键诉求")
    lines.extend(f"- {point}" for point in points[:5])
    lines.append("")
    lines.append("## MVP 范围")
    lines.extend(f"- {point}" for point in scope)
    lines.append("")
    lines.append("## 权限与合规")
    lines.extend(f"- {point}" for point in compliance)
    lines.append("")
    lines.append("## 风险与缓解")
    lines.extend(f"- {point}" for point in risks)
    lines.append("")
    lines.append("## 里程碑")
    lines.extend(f"- {point}" for point in milestones)
    return "\n".join(lines).strip()


def _fallback_deck_spec(
    title: str,
    doc_content: str,
    audience: str,
    scene_key: str,
    scene_profile: Dict[str, Any],
) -> Dict[str, Any]:
    topic = _derive_topic(title, doc_content)
    source = f"{title}\n{doc_content}"
    points = _extract_business_points(doc_content)
    is_renewal_risk = "续费" in source and ("客户" in source or "风险" in source)

    if is_renewal_risk:
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
        deck_title = "客户续费风险预警MVP项目汇报"
        cover_content = "2周上线，提前14天识别高风险客户"
        cover_bullets = ["2周上线", "提前14天识别高风险客户", "管理层决策汇报"]
        qa_bullets = ["为什么第一版采用规则引擎？", "如何避免重复触达客户？", "投入产出比如何？"]
    else:
        pain_points = _pick_points(
            points,
            ["效率", "遗漏", "人工", "耗时", "及时", "管理层"],
            [f"{topic}需要降低人工整理成本", "跨部门行动项需要可追踪、可确认、可回流", "管理层需要看到价值、范围和风险边界"],
        )
        goals = _pick_points(
            points,
            ["目标", "降低", "提升", "5分钟", "30分钟", "及时率", "遗漏率"],
            [f"{topic}围绕效率提升和事项闭环建立 MVP", "先在小范围团队试点验证价值", "用自动化减少会后重复整理"],
        )
        scope = _pick_points(
            points,
            ["第一版", "覆盖", "MVP", "录音", "发言人", "行动项", "桌面端", "移动端", "同步"],
            [f"围绕 {topic} 实现核心生成、确认和回传能力", "桌面端负责预览编辑，移动端负责轻量确认", "结果回到飞书原会话形成协同闭环"],
        )
        flow_nodes = _extract_requested_flow_nodes(source)
        if not flow_nodes and any(keyword in source for keyword in ["会议纪要", "会议", "纪要", "行动项"]):
            flow_nodes = ["IM触发", "会议内容解析", "文档生成", "行动项确认", "PPT生成", "飞书交付", "归档复盘"]
        flow_points = [f"{index + 1}. {node}" for index, node in enumerate(flow_nodes)]
        rollout = _pick_points(
            points,
            ["两周", "试点", "上线", "里程碑", "回滚", "MVP", "第"],
            ["两周内完成 MVP", "先在 3 个内部团队试点", "上线前准备风险清单和回滚方案"],
        )
        risks = _pick_points(
            points,
            ["风险", "低置信度", "误判", "敏感", "权限", "合规", "脱敏", "审计", "回滚"],
            ["低置信度内容进入人工确认", "敏感内容保留权限继承和脱敏提示", "保留人工编辑和回滚方案"],
        )
        deck_title = f"{topic}MVP上线汇报"
        cover_content = "从 IM 触发到文档、画布、PPT 和交付归档的 Agent 闭环"
        cover_bullets = ["Agent 自动化闭环", "多端协作确认", "管理层决策汇报"]
        qa_bullets = ["MVP 范围为什么这样收敛？", "如何控制低置信度结果？", "试点成功的判断标准是什么？"]

    background_bullets = _merge_points(pain_points, goals[:2], limit=5)
    scope_bullets = _merge_points(scope, limit=5)
    process_bullets = _merge_points((flow_points if not is_renewal_risk else []), scope, limit=6)
    risk_bullets = _merge_points(rollout[:3], risks[:3], limit=6)

    return {
        "title": deck_title,
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
                "title": deck_title,
                "layout": "title",
                "content": cover_content,
                "bullets": cover_bullets,
            },
            {"index": 1, "title": "项目背景与业务价值", "layout": "content", "content": "\n".join(background_bullets), "bullets": background_bullets},
            {"index": 2, "title": "MVP核心能力", "layout": "content", "content": "\n".join(scope_bullets), "bullets": scope_bullets},
            {"index": 3, "title": "Agent自动化闭环", "layout": "process", "content": "\n".join(process_bullets), "bullets": process_bullets},
            {"index": 4, "title": "落地节奏与风险控制", "layout": "two_column", "content": "\n".join(risk_bullets), "bullets": risk_bullets},
            {"index": 5, "title": "管理层关注与Q&A", "layout": "content", "content": "请各位领导指示", "bullets": qa_bullets},
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
    combined = f"{title}\n{intent}\n{doc_content}"
    if "续费" in combined and ("风险" in combined or "客户" in combined):
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
    elif any(keyword in combined for keyword in ["会议纪要", "会议", "纪要", "行动项", "发言人", "录音"]):
        labels = _extract_requested_flow_nodes(combined) or [
            "IM触发",
            "会议内容解析",
            "文档生成",
            "行动项确认",
            "PPT生成",
            "飞书交付",
            "归档复盘",
        ]
        nodes = [
            {"id": f"n{index + 1}", "text": label, "type": "process"}
            for index, label in enumerate(labels)
        ]
        edges = [
            {"source": nodes[index]["id"], "target": nodes[index + 1]["id"], "label": ""}
            for index in range(max(len(nodes) - 1, 0))
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
        "title": "客户续费风险预警全流程闭环流程图" if "续费" in combined else f"{_derive_topic(title, combined)}流程闭环图",
        "diagram_type": "flow",
        "nodes": nodes,
        "edges": edges,
        "layers": [],
    }


def _content_canvas_spec(title: str, intent: str, doc_content: str, steps: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """本地模式下生成内容白板，而不是把 Agent 执行步骤误当成用户要看的画布。"""
    source = f"{intent}\n{doc_content}".strip()
    if any(keyword in source for keyword in ["续费", "风险", "规则引擎"]):
        return _fallback_canvas_spec(title, intent, doc_content, steps)

    topic = _clean_canvas_label(title or intent or "演示主题", 28)
    points = _extract_canvas_points(source, limit=6)
    if not points:
        points = ["背景与目标", "核心观点", "关键论据", "解决方案", "实施路径", "总结与下一步"]

    nodes = [{"id": "topic", "text": topic, "type": "theme", "description": "整份文档和演示稿围绕这一主题展开"}]
    for index, point in enumerate(points, 1):
        node_type = "action" if any(word in point for word in ["下一步", "行动", "计划", "落地", "实施"]) else "insight"
        nodes.append({
            "id": f"p{index}",
            "text": _clean_canvas_label(point, 32),
            "type": node_type,
            "description": "可同步为 PPT 的结构说明页内容",
        })

    edges = [
        {"source": "topic", "target": node["id"], "label": "支撑"}
        for node in nodes[1:]
    ]
    return {
        "title": f"{topic}：内容结构白板",
        "diagram_type": "content_map",
        "nodes": nodes,
        "edges": edges,
        "layers": [],
    }


def _extract_canvas_points(source: str, limit: int = 6) -> List[str]:
    """从文档标题、Markdown 小节和项目符号里提取适合放到白板上的观点。"""
    points: List[str] = []
    for raw_line in (source or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,4}\s*", "", line)
        line = re.sub(r"^[-*+]\s*", "", line)
        line = re.sub(r"^\d+[.)、]\s*", "", line)
        line = line.strip(" ：:")
        if not line or len(line) < 4:
            continue
        if any(skip in line.lower() for skip in ["http://", "https://", "|---", "```"]):
            continue
        if any(generic in line for generic in ["生成流程图", "生成画布", "结构图画布"]):
            continue
        clauses = [item.strip(" ，。；;,.") for item in re.split(r"[。；;]", line) if item.strip()]
        for clause in clauses or [line]:
            if len(clause) < 4:
                continue
            if clause not in points:
                points.append(clause)
            if len(points) >= limit:
                break
        if len(points) >= limit:
            break
    if len(points) < 3:
        for point in _extract_business_points(source, limit=limit):
            cleaned = _clean_canvas_label(point, 36)
            if cleaned and cleaned not in points:
                points.append(cleaned)
            if len(points) >= limit:
                break
    return points[:limit]


def _clean_canvas_label(value: str, limit: int = 36) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip("，。；,.;") or "核心观点"


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
    topic = _derive_topic(current_intent, source)
    points = _extract_business_points(source, limit=24)

    stakeholders = []
    for marker in ["产品经理", "业务负责人", "销售负责人", "数据同学", "算法同学", "客服负责人", "客户成功", "研发负责人", "设计同学", "法务同学", "项目经理", "运营"]:
        if marker in source and marker not in stakeholders:
            stakeholders.append(marker)

    is_renewal_risk = "续费" in source and ("客户" in source or "风险" in source)

    return {
        "summary": "团队正在讨论客户续费风险预警能力，目标是提前识别高风险客户，并通过文档、画布和汇报材料沉淀方案。" if is_renewal_risk else (f"团队正在讨论{topic}，需要沉淀文档、画布和汇报材料。" if topic else (points[0] if points else source[:160])),
        "topics": _pick_points(points, ["续费", "风险", "预警", "飞书", "MVP", "会议", "纪要", "行动项"], [topic, "跨部门协同", "MVP落地"]),
        "decisions": _pick_points(points, ["第一版", "规则引擎", "两周", "MVP", "不做", "覆盖", "试点"], ["第一版收敛MVP范围", "两周内完成MVP"]),
        "requirements": _pick_points(points, ["希望", "需要", "目标", "页面", "信号", "推送", "桌面端", "移动端", "确认"], [f"围绕{topic}生成可交付材料", "推送到飞书群", "支持多端协作确认"]),
        "risks": _pick_points(points, ["重复", "打扰", "投诉", "复杂", "滞后", "敏感", "低置信度", "权限", "回滚"], ["控制MVP范围", "低置信度内容需要人工确认"]),
        "todos": _pick_points(points, ["完成", "上线", "评审", "联调", "灰度", "试点", "两周"], ["确认MVP范围", "完成试点和复盘验证"]),
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

关键要求：只有当用户输入明显缺少核心信息时，才生成澄清问题。核心信息指：没有说
明主题、用途或内容方向。不要因为缺少受众、风格等次要信息而提问——这些有合理的
默认值。

判断模糊的标准（必须满足至少一条才生成 questions）：
- 只说了"做个PPT"/"生成文档"/"画个流程图"但没有说明任何主题或用途
- 说"做个方案"但没有具体方向
- 说"总结一下"但没有说明总结的范围

如果用户已经说明了主题（例如"做一个关于XX的PPT"），就不要生成澄清问题。此时
应将 audience 设为合理的默认值（如"管理层"或"团队"）。

在以上情况下，请在 questions 中返回 2-3 个具体问题，同时把 content_types 设为根
据需求推测的最可能的类型。

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
- 给每页选择明确页面意图：结论页、指标页、流程页、对比页、时间线页、Q&A 页
- layout 优先从 hero、metrics、timeline、comparison、process、cards、chart、closing 中选择；必要时可用 content、two_column、diagram
- 指标页把关键数字放入 highlight_metrics，时间线页放入 timeline，流程页放入 process_steps，对比/卡片页放入 sections
- 当内容涉及数量对比、趋势变化、占比分布时（如季度收入、市场占比、增长趋势、同比环比），优先使用 chart layout，并在 chart 字段输出图表数据
- chart 字段格式：{"type": "bar"|"pie"|"line"|"horizontal_bar", "title": "图表标题", "categories": ["Q1", "Q2", ...], "series": [{"name": "系列名", "values": [100, 150, ...]}]}
- chart layout 示例：
  - 季度收入对比 → type: "bar", categories: ["Q1", "Q2", "Q3", "Q4"], series: [{"name": "收入(万元)", "values": [120, 150, 180, 210]}]
  - 市场占比 → type: "pie", categories: ["产品A", "产品B", "产品C"], series: [{"name": "份额", "values": [45, 35, 20]}]
  - 增长趋势 → type: "line", categories: ["1月", "2月", "3月", "4月", "5月"], series: [{"name": "用户数", "values": [1000, 1200, 1500, 1800, 2200]}]
  - 多系列对比 → type: "bar", categories: ["Q1", "Q2", "Q3"], series: [{"name": "2024", "values": [100, 130, 160]}, {"name": "2025", "values": [120, 150, 180]}]
- 适当使用图表和可视化建议，但不要输出 CSS、坐标或外部图片 URL
- 输出结构化演示稿信息
- theme 字段从 business_blue / tech_dark / minimal / emerald / slate / sunset / entertainment 中选择最合适的主题
  - business_blue: 商务蓝色，适合正式汇报
  - tech_dark: 科技深色，适合技术分享
  - minimal: 极简风格，适合简洁报告
  - emerald: 适合方案提案和增长主题
  - slate: 适合复盘、风险和治理主题
  - sunset: 适合营销、活动和阶段推进
  - entertainment: 适合游戏、文娱、二次元主题""",

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
- 优先表达“内容结构、论证关系、演示逻辑”，不要把 Agent 执行步骤当成画布内容
- diagram_type 优先使用 content_map；只有用户明确要系统架构时用 architecture，明确要业务流程时用 flow
- content_map 使用中心主题 + 核心观点节点，边表示“支撑/展开/推导”
- flow 使用 nodes + edges
- architecture 使用 layers。""",

    "ppt_brief_generator": (
        "你是一位资深演示文稿策划师。根据给定的草稿规格和源材料，"
        "输出结构化的演示文稿简报（brief），用于指导专业级幻灯片设计。\n\n"
        "输出格式（严格 JSON）：\n"
        "{\n"
        '  "title": "演示文稿标题（不超过40字）",\n'
        '  "subtitle": "副标题或标语",\n'
        '  "audience": "目标受众描述",\n'
        '  "slide_count": 8-15之间的整数,\n'
        '  "key_messages": ["核心信息1", "核心信息2", "核心信息3"],\n'
        '  "tone": "formal|executive|technical|casual 其中之一",\n'
        '  "date": "封面日期字符串",\n'
        '  "sections": [{"name": "章节名", "slides": 页数, "message": "该章节传达的核心信息"}]\n'
        "}\n\n"
        "设计原则：\n"
        "- 管理层受众：页数少（8-10），数据驱动\n"
        "- 技术人员：可深入（12-15），包含流程细节\n"
        "- 每页只传达一个核心信息\n"
        "- 先给结论，后给支撑细节\n"
    ),
}

SYSTEM_PROMPTS["im_context_summarizer"] = (
    "You are an IM context analysis agent that extracts structured, reusable context from "
    "Chinese-language chat history. The input contains session messages and task summaries.\n\n"
    "Extract the following fields from the conversation:\n"
    "- summary: 1-2 sentence Chinese summary of the overall discussion\n"
    "- topics: key topics discussed (in Chinese, 3-8 items)\n"
    "- decisions: concrete decisions already made (e.g. '采用方案A', '下周上线')\n"
    "- requirements: explicit requirements or feature requests mentioned\n"
    "- risks: risks or concerns raised by any participant\n"
    "- todos: action items with owner if mentioned (e.g. '张三负责整理数据')\n"
    "- stakeholders: people or roles mentioned as relevant parties\n"
    "- open_questions: unresolved questions that still need discussion\n\n"
    "Guidelines:\n"
    "- Prefer extracting explicitly stated information over inference\n"
    "- If the chat only contains previous task summaries (not actual discussion), "
    "set summary to the task intent and extract key points from the summary\n"
    "- For single-message inputs without context, focus on the request itself\n"
    "- Output must be concise — each item should be under 100 characters\n"
    "- Use Chinese for all extracted content"
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
    content_types = {str(item).strip().lower() for item in (context or {}).get("content_types", [])}
    wants_doc = bool(content_types & {"doc", "document", "documents", "prd", "summary"})
    wants_slides = bool(content_types & {"ppt", "slide", "slides", "deck", "presentation", "powerpoint"})
    wants_canvas = bool(content_types & {"canvas", "whiteboard", "diagram", "flowchart", "board"})
    default_steps = []
    default_artifacts = []
    if wants_doc:
        default_steps.append({"module": "DOC", "action": "create_doc", "needs_approval": False})
        default_artifacts.append("document")
    if wants_canvas:
        default_steps.append({"module": "CANVAS", "action": "generate_canvas", "needs_approval": False})
        default_artifacts.append("canvas")
    if wants_slides or not default_steps:
        default_steps.append({"module": "DECK", "action": "generate_slides", "needs_approval": False})
        default_artifacts.append("slides")
    default = {
        "goal": intent,
        "presentation_scene": scene,
        "audience": (context or {}).get("audience", "管理层"),
        "artifacts": default_artifacts,
        "steps": default_steps,
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
    content = str(response.get("content") or "").strip()
    if content.startswith("[Mock]"):
        return _fallback_doc_content(title, intent, outline)
    return content or _fallback_doc_content(title, intent, outline)


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
    safe_title = _derive_topic(title, doc_content)

    default = {
        "title": safe_title,
        "audience": audience,
        "duration_minutes": scene_profile["duration_minutes"],
        "theme": scene_profile["theme"],
        "metadata": {
            "presentation_scene": scene_key,
            "template_profile": scene_key,
            "scene_label": scene_profile["label"],
        },
        "slides": [
            {"index": 0, "title": safe_title, "layout": "title", "content": scene_profile["label"], "bullets": [scene_profile["label"]]},
            {"index": 1, "title": outline[0], "layout": "content", "content": "开场与结论", "bullets": [f"场景：{scene_profile['label']}", f"受众：{audience}"]},
            {"index": 2, "title": outline[1], "layout": "content", "content": "背景与上下文", "bullets": []},
            {"index": 3, "title": outline[2], "layout": "two_column", "content": "核心结构", "bullets": []},
            {"index": 4, "title": outline[3], "layout": "content", "content": "关键风险或价值", "bullets": []},
            {"index": 5, "title": outline[-1], "layout": "content", "content": "行动与收尾", "bullets": []},
        ],
    }
    default = _fallback_deck_spec(safe_title, doc_content, audience, scene_key, scene_profile)
    prompt = (
        f"文档标题：{safe_title}\n\n"
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
    default = _content_canvas_spec(title, intent, doc_content, steps)
    if not use_llm:
        return default

    prompt = (
        f"# Title\n{title}\n\n"
        f"# User Intent\n{intent}\n\n"
        f"# Workflow Steps\n{json.dumps(steps or [], ensure_ascii=False, indent=2)}\n\n"
        f"# Document\n{doc_content[:4000]}\n\n"
        "# Task\nCreate a content-first whiteboard spec. Focus on what the PPT should explain, not on backend execution steps."
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
