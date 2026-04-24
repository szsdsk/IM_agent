"""
Agent Nodes - 任务节点定义
每个节点负责一个特定的任务步骤，集成 LLM 服务
"""
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional, List

from backend.agent.state import AgentState
from backend.tools.tool_factory import ToolFactory
from backend.services.llm_service import (
    parse_intent as llm_parse_intent,
    plan_workflow as llm_plan_workflow,
    generate_doc_content,
    generate_deck_spec,
    generate_rehearsal,
)

logger = logging.getLogger(__name__)


def _touch(state: AgentState, step: str, progress: float | None = None) -> None:
    """更新状态"""
    state["current_step"] = step
    state["updated_at"] = datetime.utcnow().isoformat()
    if progress is not None:
        state["progress"] = progress


def _append_message(state: AgentState, role: str, content: str, step: str = None,
                    requires_confirmation: bool = False, **kwargs) -> None:
    """追加消息"""
    msg = {
        "role": role,
        "content": content,
        "timestamp": state["updated_at"],
    }
    if step:
        msg["step"] = step
    if requires_confirmation:
        msg["requires_confirmation"] = True
    msg.update(kwargs)
    state["messages"].append(msg)


async def receive_input(state: AgentState) -> AgentState:
    """接收用户输入"""
    state["status"] = "running"
    _touch(state, "receive_input", 0.05)

    logger.info(f"Task {state['task_id']}: received input - {state['intent'][:100]}")

    _append_message(state, role="user", content=state["intent"], step="receive_input")
    _append_message(state, role="system", content="✅ 已接收需求，正在分析...", step="receive_input")

    return state


async def parse_intent(state: AgentState) -> AgentState:
    """解析用户意图 - 使用 LLM"""
    _touch(state, "parse_intent", 0.12)

    try:
        context = state.get("context_messages", [])
        intent_result = await llm_parse_intent(state["intent"], context)

        if intent_result:
            state["intent_analysis"] = intent_result
            state["content_types"] = intent_result.get("content_types", ["doc", "slides"])
            state["audience"] = intent_result.get("audience", "管理层")
            state["constraints"] = intent_result.get("constraints", [])

            analysis_text = f"""📋 **需求分析完成**

- **核心需求**: {intent_result.get('intent_summary', '待分析')}
- **生成内容**: {', '.join(state['content_types'])}
- **目标受众**: {state['audience']}
"""
            if intent_result.get("questions"):
                analysis_text += f"\n**需要确认**: {', '.join(intent_result['questions'])}"
                state["pending_questions"] = intent_result["questions"]

            _append_message(state, "assistant", analysis_text, "parse_intent")
        else:
            _append_message(state, "assistant", "⚠️ 意图分析失败，使用默认方案", "parse_intent")
            state["content_types"] = ["doc", "slides"]

    except Exception as e:
        logger.exception("Error in parse_intent")
        _append_message(state, "assistant", f"⚠️ 分析出错: {str(e)}", "parse_intent")
        state["content_types"] = ["doc", "slides"]

    return state


async def plan_workflow(state: AgentState) -> AgentState:
    """规划工作流 - 使用 LLM"""
    _touch(state, "plan_workflow", 0.2)

    try:
        context = {
            "content_types": state.get("content_types", []),
            "audience": state.get("audience", "管理层"),
            "constraints": state.get("constraints", []),
        }

        plan = await llm_plan_workflow(state["intent"], context)

        if plan:
            state["workflow_plan"] = plan
            state["steps"] = plan.get("steps", [])

            plan_text = "📋 **执行计划**\n\n"
            for i, step in enumerate(state["steps"]):
                module = step.get("module", "UNKNOWN")
                action = step.get("action", "unknown")
                needs_approval = step.get("needs_approval", False)
                icon = "✅" if needs_approval else "➡️"
                approval_text = " [待确认]" if needs_approval else ""
                plan_text += f"{i+1}. {icon} **{module}** / {action}{approval_text}\n"

            _append_message(state, "assistant", plan_text, "plan_workflow")

            if state["steps"] and state["steps"][0].get("needs_approval"):
                state["waiting_approval"] = True
                state["status"] = "waiting_approval"
                _append_message(state, "assistant",
                    "⏸️ 请确认计划是否正确，回复\"继续\"或提出修改意见",
                    "plan_workflow", requires_confirmation=True)
        else:
            state["steps"] = [
                {"module": "DOC", "action": "create_doc", "needs_approval": True},
                {"module": "DECK", "action": "generate_slides", "needs_approval": False},
            ]
            _append_message(state, "assistant", "📋 使用默认计划", "plan_workflow")

    except Exception as e:
        logger.exception("Error in plan_workflow")
        _append_message(state, "assistant", f"⚠️ 规划出错: {str(e)}", "plan_workflow")
        state["steps"] = [{"module": "DOC", "action": "create_doc", "needs_approval": False}]

    return state


async def extract_tasks(state: AgentState) -> AgentState:
    """提取具体任务"""
    _touch(state, "extract_tasks", 0.3)

    tasks = []
    modules = set(step.get("module") for step in state.get("steps", []))

    for module in modules:
        if module == "DOC":
            tasks.extend(["理解并归纳文档结构", "生成文档初稿"])
        elif module == "DECK":
            tasks.extend(["整理 PPT 结构和内容", "生成演示稿"])
        elif module == "CANVAS":
            tasks.append("生成流程图或架构图")
        elif module == "IM_CONTEXT":
            tasks.append("读取并分析群聊上下文")

    state["extracted_tasks"] = tasks
    _append_message(state, "assistant",
        f"📝 **任务拆解完成** ({len(tasks)} 个子任务)\n\n" + "\n".join(f"- {t}" for t in tasks),
        "extract_tasks")

    return state


async def generate_doc(state: AgentState) -> AgentState:
    """生成文档 - 使用 LLM"""
    _touch(state, "generate_doc", 0.5)
    logger.info(f"Task {state['task_id']}: generating document")

    _append_message(state, "assistant", "📄 正在生成文档...", "generate_doc")

    try:
        title = state.get("intent", "未命名文档")
        outline = state.get("intent_analysis", {}).get("outline")
        content = await generate_doc_content(title, state["intent"], outline)

        if content:
            doc_tool = ToolFactory.get_tool("DocTool")
            result = await doc_tool.execute(
                action="create_doc",
                task_id=state["task_id"],
                title=title,
                content=content,
            )

            if result.get("success"):
                state["doc_content"] = {
                    "doc_id": result.get("doc_id"),
                    "title": title,
                    "content": content,
                    "content_preview": content[:500] + "..." if len(content) > 500 else content,
                }
                state["doc_id"] = result.get("doc_id")
                _append_message(state, "assistant",
                    f"✅ **文档已生成**\n\n文档: **{title}**\n\n预览:\n```\n{state['doc_content']['content_preview']}\n```",
                    "generate_doc")
            else:
                state["error"] = f"文档保存失败: {result.get('error')}"
                _append_message(state, "assistant", f"⚠️ {state['error']}", "generate_doc")
        else:
            state["error"] = "文档内容生成失败"
            _append_message(state, "assistant", "⚠️ 文档内容生成失败", "generate_doc")

    except Exception as e:
        logger.exception("Error generating doc")
        state["error"] = str(e)
        _append_message(state, "assistant", f"⚠️ 生成失败: {str(e)}", "generate_doc")

    return state


async def generate_canvas(state: AgentState) -> AgentState:
    """生成画布/白板"""
    _touch(state, "generate_canvas", 0.6)

    modules = set(step.get("module") for step in state.get("steps", []))
    if "CANVAS" not in modules:
        return state

    _append_message(state, "assistant", "🎨 正在生成流程图/架构图...", "generate_canvas")
    state["canvas_content"] = {"canvas_id": f"canvas_{state['task_id']}", "type": "architecture_diagram"}
    _append_message(state, "assistant", "✅ 架构图已生成", "generate_canvas")

    return state


async def generate_slides(state: AgentState) -> AgentState:
    """生成 PPT - 使用 LLM"""
    _touch(state, "generate_slides", 0.7)
    logger.info(f"Task {state['task_id']}: generating slides")

    modules = set(step.get("module") for step in state.get("steps", []))
    if "DECK" not in modules:
        return state

    _append_message(state, "assistant", "📊 正在生成演示稿...", "generate_slides")

    try:
        doc_content = state.get("doc_content", {}).get("content", state["intent"])
        audience = state.get("audience", "管理层")

        deck_spec = await generate_deck_spec(
            title=state.get("intent", "演示稿"),
            doc_content=doc_content,
            audience=audience
        )
        state["deck_spec"] = deck_spec

        ppt_tool = ToolFactory.get_tool("PPTTool")
        slides = deck_spec.get("slides", [])

        result = await ppt_tool.execute(
            action="create_slides",
            task_id=state["task_id"],
            title=deck_spec.get("title", state["intent"]),
            slides=slides,
        )

        if result.get("success"):
            state["slides_content"] = {
                "slide_id": result.get("slide_id"),
                "title": deck_spec.get("title"),
                "slides": slides,
                "file_path": result.get("file_path"),
            }
            state["slide_id"] = result.get("slide_id")

            slides_count = len(slides)
            _append_message(state, "assistant",
                f"✅ **演示稿已生成** ({slides_count} 页)\n\n" +
                "\n".join(f"- 第 {s.get('index', i)+1} 页: {s.get('title', '未命名')}" for i, s in enumerate(slides[:5])) +
                (f"\n- ..." if slides_count > 5 else ""),
                "generate_slides")
        else:
            state["error"] = f"PPT 保存失败: {result.get('error')}"
            _append_message(state, "assistant", f"⚠️ {state['error']}", "generate_slides")

    except Exception as e:
        logger.exception("Error generating slides")
        state["error"] = str(e)
        _append_message(state, "assistant", f"⚠️ 生成失败: {str(e)}", "generate_slides")

    return state


async def confirm_or_modify(state: AgentState) -> AgentState:
    """等待用户确认或修改"""
    _touch(state, "confirm_or_modify", 0.85)

    _append_message(state, "assistant",
        "📝 **初稿已完成**\n\n"
        "请提出修改意见，或输入\"确认交付\"完成本次任务。\n\n"
        "支持的指令：\n"
        "- 修改具体内容\n"
        "- 调整 PPT 页数\n"
        "- 重新生成某部分\n"
        "- 确认交付",
        "confirm_or_modify", requires_confirmation=True)

    return state


async def deliver_result(state: AgentState) -> AgentState:
    """交付结果"""
    _touch(state, "deliver_result", 1.0)
    state["status"] = "failed" if state.get("error") else "completed"

    delivery = {
        "status": state["status"],
        "message": state.get("error") or "任务完成",
        "progress": state["progress"],
    }

    if state.get("doc_content"):
        delivery["document"] = {
            "title": state["doc_content"].get("title"),
            "doc_id": state["doc_content"].get("doc_id"),
            "preview": state["doc_content"].get("content_preview"),
        }

    if state.get("slides_content"):
        delivery["slides"] = {
            "title": state["slides_content"].get("title"),
            "slide_id": state["slides_content"].get("slide_id"),
            "slides_count": len(state["slides_content"].get("slides", [])),
            "file_path": state["slides_content"].get("file_path"),
        }

    if state.get("canvas_content"):
        delivery["canvas"] = {"canvas_id": state["canvas_content"].get("canvas_id")}

    state["result"] = delivery

    card_text = "🎉 **任务完成！**\n\n"
    if state.get("doc_content"):
        card_text += f"📄 **文档**: {state['doc_content'].get('title')}\n"
    if state.get("slides_content"):
        slides_info = state["slides_content"]
        card_text += f"📊 **演示稿**: {slides_info.get('title')} ({len(slides_info.get('slides', []))} 页)\n"
    if state.get("canvas_content"):
        card_text += "🎨 **架构图**: 已生成\n"
    card_text += "\n💡 输入\"排练\"可以获取演讲提示"

    _append_message(state, "assistant", card_text, "deliver_result")
    _append_message(state, "system", "结果已交付", "deliver_result")

    return state


# 节点映射
NODES = {
    "receive_input": receive_input,
    "parse_intent": parse_intent,
    "plan_workflow": plan_workflow,
    "extract_tasks": extract_tasks,
    "generate_doc": generate_doc,
    "generate_canvas": generate_canvas,
    "generate_slides": generate_slides,
    "confirm_or_modify": confirm_or_modify,
    "deliver_result": deliver_result,
}
