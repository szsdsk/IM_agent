import logging
from datetime import datetime

from backend.agent.state import AgentState
from backend.tools.tool_factory import ToolFactory

logger = logging.getLogger(__name__)


def _touch(state: AgentState, step: str, progress: float | None = None) -> None:
    state["current_step"] = step
    state["updated_at"] = datetime.utcnow().isoformat()
    if progress is not None:
        state["progress"] = progress


async def receive_input(state: AgentState) -> AgentState:
    state["status"] = "running"
    _touch(state, "receive_input", 0.05)
    logger.info("Task %s: received input", state["task_id"])
    state["messages"].append({
        "role": "system",
        "content": f"已接收用户需求：{state['intent']}",
        "step": "receive_input",
        "timestamp": state["updated_at"],
    })
    return state


async def parse_intent(state: AgentState) -> AgentState:
    _touch(state, "parse_intent", 0.12)
    intent_lower = state["intent"].lower()
    detected_types: list[str] = []

    if any(keyword in intent_lower for keyword in ["文档", "方案", "纪要", "周报", "总结", "报告", "doc"]):
        detected_types.append("generate_doc")
    if any(keyword in intent_lower for keyword in ["ppt", "幻灯片", "汇报", "演示", "slides"]):
        detected_types.append("generate_slides")
    if not detected_types:
        detected_types = ["generate_doc", "generate_slides"]

    state["workflow_plan"] = detected_types
    state["messages"].append({
        "role": "assistant",
        "content": f"需求分析完成，识别到任务类型：{', '.join(detected_types)}",
        "step": "parse_intent",
        "timestamp": state["updated_at"],
    })
    return state


async def plan_workflow(state: AgentState) -> AgentState:
    _touch(state, "plan_workflow", 0.2)
    output_steps = ["receive_input", "parse_intent", "plan_workflow", "extract_tasks"]
    output_steps.extend(state.get("workflow_plan") or ["generate_doc", "generate_slides"])
    output_steps.extend(["confirm_or_modify", "deliver_result"])
    state["workflow_plan"] = output_steps
    state["messages"].append({
        "role": "assistant",
        "content": f"已规划执行流程：{', '.join(output_steps)}",
        "step": "plan_workflow",
        "timestamp": state["updated_at"],
    })
    return state


async def extract_tasks(state: AgentState) -> AgentState:
    _touch(state, "extract_tasks", 0.3)
    state["extracted_tasks"] = [
        "理解并归纳用户目标",
        "整理核心内容结构",
        "生成文档初稿",
        "生成 PPT 大纲",
        "汇总交付结果",
    ]
    state["messages"].append({
        "role": "assistant",
        "content": "已完成任务拆解。",
        "step": "extract_tasks",
        "timestamp": state["updated_at"],
    })
    return state


async def generate_doc(state: AgentState) -> AgentState:
    _touch(state, "generate_doc", 0.5)
    logger.info("Task %s: generating document", state["task_id"])

    content = (
        f"# {state['intent']}\n\n"
        "## 核心结论\n"
        "- 已根据输入需求整理出可执行的工作内容。\n"
        "- 当前为本地 mock 生成结果，可用于验证前后端链路。\n\n"
        "## 待办事项\n"
        "1. 补充真实业务上下文。\n"
        "2. 接入真实模型或飞书数据源。\n"
        "3. 根据反馈继续修改文档和 PPT。\n"
    )

    try:
        doc_tool = ToolFactory.get_tool("DocTool")
        result = await doc_tool.execute(
            action="create_doc",
            task_id=state["task_id"],
            title=state["intent"],
            content=content,
        )
        if result.get("success"):
            state["doc_content"] = result
            state["messages"].append({
                "role": "assistant",
                "content": "文档初稿已生成。",
                "step": "generate_doc",
                "timestamp": state["updated_at"],
            })
        else:
            state["error"] = f"文档生成失败：{result.get('error')}"
    except Exception as exc:
        logger.exception("Error generating doc")
        state["error"] = str(exc)

    return state


async def generate_slides(state: AgentState) -> AgentState:
    _touch(state, "generate_slides", 0.7)
    logger.info("Task %s: generating slides", state["task_id"])

    slides_data = [
        {"index": 0, "title": "封面", "content": state["intent"], "layout": "title"},
        {"index": 1, "title": "背景与目标", "content": "说明任务背景、目标和预期产出。", "layout": "content"},
        {"index": 2, "title": "执行计划", "content": "需求分析、内容生成、结果校验、交付确认。", "layout": "content"},
        {"index": 3, "title": "风险与待办", "content": "补充真实数据源、完善模型配置、确认交付格式。", "layout": "content"},
        {"index": 4, "title": "下一步", "content": "根据反馈继续完善文档和演示材料。", "layout": "content"},
    ]

    try:
        ppt_tool = ToolFactory.get_tool("PPTTool")
        result = await ppt_tool.execute(
            action="create_slides",
            task_id=state["task_id"],
            title=state["intent"],
            slides=slides_data,
        )
        if result.get("success"):
            result["slides"] = slides_data
            state["slides_content"] = result
            state["messages"].append({
                "role": "assistant",
                "content": "PPT 大纲已生成。",
                "step": "generate_slides",
                "timestamp": state["updated_at"],
            })
        else:
            state["error"] = f"PPT 生成失败：{result.get('error')}"
    except Exception as exc:
        logger.exception("Error generating slides")
        state["error"] = str(exc)

    return state


async def confirm_or_modify(state: AgentState) -> AgentState:
    _touch(state, "confirm_or_modify", 0.85)
    state["messages"].append({
        "role": "assistant",
        "content": "初稿已完成，可以继续提出修改意见。",
        "step": "confirm_or_modify",
        "timestamp": state["updated_at"],
        "requires_confirmation": True,
    })
    return state


async def deliver_result(state: AgentState) -> AgentState:
    _touch(state, "deliver_result", 1.0)
    state["status"] = "failed" if state.get("error") else "completed"
    state["result"] = {
        "doc": state.get("doc_content"),
        "slides": state.get("slides_content"),
        "status": state["status"],
        "message": state.get("error") or "任务完成",
        "progress": state["progress"],
    }

    state["messages"].append({
        "role": "system",
        "content": "结果已交付。",
        "step": "deliver_result",
        "timestamp": state["updated_at"],
    })
    return state
