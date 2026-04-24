"""
LLM Service - MiniMax API Integration
支持 OpenAI 兼容接口的 LLM 调用
"""
import os
import json
import logging
from typing import Dict, Any, Optional, List, AsyncIterator
from datetime import datetime

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务封装，支持 OpenAI 兼容 API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.model = model or settings.LLM_MODEL
        self._client: Optional[httpx.AsyncClient] = None

        if not self.api_key:
            logger.warning("No API key configured, LLM calls will use mock mode")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_response: bool = False,
    ) -> Dict[str, Any]:
        """
        发送聊天请求到 LLM

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大 token 数
            json_response: 是否要求 JSON 响应

        Returns:
            {"content": str, "usage": {...}, "model": str}
        """
        if not self.api_key:
            return self._mock_response(messages)

        # 构建完整消息列表
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        request_data = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
        }
        if max_tokens:
            request_data["max_tokens"] = max_tokens

        try:
            logger.info(f"LLM Request: model={self.model}, messages_count={len(full_messages)}")
            response = await self.client.post("/chat/completions", json=request_data)
            response.raise_for_status()
            result = response.json()

            return {
                "content": result["choices"][0]["message"]["content"],
                "usage": result.get("usage", {}),
                "model": result.get("model", self.model),
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM HTTP Error: {e.response.status_code} - {e.response.text}")
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except Exception as e:
            logger.error(f"LLM Error: {str(e)}")
            return {"error": str(e)}

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """流式响应"""
        if not self.api_key:
            for item in self._mock_stream_gen():
                yield item
            return

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        request_data = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with self.client.stream("POST", "/chat/completions", json=request_data) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if chunk["choices"][0]["delta"].get("content"):
                            yield chunk["choices"][0]["delta"]["content"]
        except Exception as e:
            logger.error(f"LLM Stream Error: {str(e)}")
            yield f"Error: {str(e)}"

    async def parse_json(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> Optional[Dict]:
        """解析 JSON 响应"""
        response = await self.chat(messages, system_prompt, json_response=False)
        if "error" in response:
            return None

        content = response["content"].strip()
        # 尝试提取 JSON
        # 去掉 markdown 代码块标记
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        # 尝试从中间找到 JSON 对象开始
        json_start = content.find("{")
        if json_start >= 0:
            content = content[json_start:]

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON: {content[:200]}")
            return None

    def _mock_response(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Mock 响应"""
        last_message = messages[-1]["content"] if messages else ""
        return {
            "content": f"[Mock] 已处理: {last_message[:50]}...",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "model": "mock",
        }

    def _mock_stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        """Mock 流式响应"""
        async def mock_gen():
            yield "[Mock] 正在处理..."
            yield "这是 Mock 响应内容"
        return mock_gen()

    def _mock_stream_gen(self):
        """Mock 流式响应生成器"""
        yield "[Mock] 正在处理..."
        yield "这是 Mock 响应内容"


# 全局实例
llm_service = LLMService()


# ============ Agent Prompt Templates ============

SYSTEM_PROMPTS = {
    "intent_parser": """你是一个任务规划助手。用户会通过 IM 输入需求，你需要：
1. 理解用户的核心意图
2. 识别需要生成的内容类型（文档/PPT/画布/总结）
3. 识别目标受众和汇报场景
4. 识别特殊约束或要求

请用 JSON 格式输出分析结果：
{
    "intent_summary": "用一句话总结用户需求",
    "content_types": ["doc", "slides", "canvas", "summary"],
    "audience": "目标受众",
    "constraints": ["约束1", "约束2"],
    "questions": ["需要确认的问题"]
}""",

    "planner": """你是一个工作流规划助手。根据用户需求和上下文，制定执行计划。

要求：
1. 将任务分解为可执行的子任务
2. 每个子任务有明确的 action 和 module
3. 需要用户确认的节点标记 needs_approval: true
4. 考虑任务的依赖关系和执行顺序

JSON 格式：
{
    "goal": "总体目标",
    "audience": "目标受众",
    "artifacts": ["需要生成的产物"],
    "steps": [
        {"module": "IM_CONTEXT", "action": "summarize_thread", "needs_approval": false},
        {"module": "DOC", "action": "create_prd_outline", "needs_approval": true},
        ...
    ]
}""",

    "doc_writer": """你是一个专业的文档撰写助手。根据以下要求生成高质量文档内容。

文档类型：PRD（产品需求文档）
要求：
- 结构清晰：背景、目标、需求详情、里程碑、风险
- 语言专业但易懂
- 突出关键信息和决策点
- 使用 Markdown 格式

请生成完整文档内容。""",

    "slides_generator": """你是一个演示稿设计助手。根据文档内容生成 PPT 结构。

要求：
- 每页有明确的标题和内容
- 考虑信息密度和演讲节奏
- 适当使用图表和可视化
- 生成 DeckSpec JSON 格式

JSON 格式：
{
    "title": "演示标题",
    "audience": "目标受众",
    "duration_minutes": 5,
    "slides": [
        {
            "index": 0,
            "title": "封面",
            "layout": "title",
            "content": {...}
        },
        ...
    ]
}""",

    "summarizer": """你是一个会议和讨论总结助手。分析 IM 对话上下文，提取：
1. 讨论的核心话题
2. 各方观点和立场
3. 已达成的共识
4. 待解决的问题
5. 关键决策和行动项

请用结构化格式输出总结。""",

    "rehearsal": """你是一个演讲排练助手。根据 PPT 内容生成排练材料：
1. 每页讲稿（50-100字）
2. 预计时间
3. 可能的提问（Q&A）
4. 提示要点

JSON 格式：
{
    "slides": [
        {
            "slide_index": 0,
            "speaker_notes": "讲稿内容",
            "duration_seconds": 30,
            "qa_questions": ["问题1", "问题2"]
        }
    ],
    "total_duration_minutes": 5,
    "tips": ["提示1", "提示2"]
}""",
}


async def parse_intent(user_input: str, context: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """解析用户意图"""
    messages = [{"role": "user", "content": user_input}]
    if context:
        context_text = "\n".join([f"{c.get('role', 'user')}: {c.get('content', '')}" for c in context[-10:]])
        messages = [{"role": "user", "content": f"上下文：\n{context_text}\n\n当前输入：{user_input}"}]

    return await llm_service.parse_json(
        messages,
        system_prompt=SYSTEM_PROMPTS["intent_parser"]
    ) or {"intent_summary": user_input, "content_types": ["doc", "slides"]}


async def plan_workflow(intent: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    """生成任务计划"""
    messages = [{"role": "user", "content": f"用户需求：{intent}"}]
    if context:
        messages[0]["content"] += f"\n\n上下文信息：{json.dumps(context, ensure_ascii=False)}"

    return await llm_service.parse_json(
        messages,
        system_prompt=SYSTEM_PROMPTS["planner"]
    ) or {
        "goal": intent,
        "steps": [
            {"module": "DOC", "action": "create_doc", "needs_approval": True},
            {"module": "DECK", "action": "generate_slides", "needs_approval": False},
        ]
    }


async def generate_doc_content(title: str, intent: str, outline: Optional[Dict] = None) -> str:
    """生成文档内容"""
    prompt = f"# 任务\n生成文档标题：{title}\n用户需求：{intent}\n"
    if outline:
        prompt += f"\n大纲：{json.dumps(outline, ensure_ascii=False, indent=2)}"

    response = await llm_service.chat(
        [{"role": "user", "content": prompt}],
        system_prompt=SYSTEM_PROMPTS["doc_writer"]
    )
    return response.get("content", "")


async def generate_deck_spec(title: str, doc_content: str, audience: str = "管理层") -> Dict[str, Any]:
    """生成 PPT 结构"""
    prompt = f"文档标题：{title}\n\n文档内容：\n{doc_content[:2000]}...\n\n目标受众：{audience}"

    result = await llm_service.parse_json(
        [{"role": "user", "content": prompt}],
        system_prompt=SYSTEM_PROMPTS["slides_generator"]
    )

    if not result:
        # 默认结构
        return {
            "title": title,
            "audience": audience,
            "slides": [
                {"index": 0, "title": "封面", "layout": "title"},
                {"index": 1, "title": "背景与目标", "layout": "content"},
                {"index": 2, "title": "执行计划", "layout": "content"},
                {"index": 3, "title": "风险与待办", "layout": "content"},
                {"index": 4, "title": "下一步", "layout": "content"},
            ]
        }
    return result


async def generate_rehearsal(deck_spec: Dict[str, Any]) -> Dict[str, Any]:
    """生成排练材料"""
    prompt = f"PPT 结构：\n{json.dumps(deck_spec, ensure_ascii=False, indent=2)}"

    result = await llm_service.parse_json(
        [{"role": "user", "content": prompt}],
        system_prompt=SYSTEM_PROMPTS["rehearsal"]
    )

    if not result:
        slides = deck_spec.get("slides", [])
        return {
            "slides": [
                {"slide_index": i, "speaker_notes": f"讲解第 {i+1} 页", "duration_seconds": 60}
                for i in range(len(slides))
            ],
            "total_duration_minutes": len(slides),
            "tips": ["控制语速", "注意互动"]
        }
    return result
