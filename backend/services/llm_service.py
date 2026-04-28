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
}

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
    prompt = (
        f"文档标题：{title}\n\n"
        f"文档内容：\n{doc_content[:4000]}\n\n"
        f"目标受众：{audience}\n"
        f"演示场景：{scene_key}\n"
        f"场景说明：{scene_profile['label']}\n"
        f"建议结构：{' / '.join(outline)}"
    )

    return await llm_service.structured_chat(
        [{"role": "user", "content": prompt}],
        DeckSpecModel,
        system_prompt=SYSTEM_PROMPTS["slides_generator"],
        default=default,
    ) or default


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
