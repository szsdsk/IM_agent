"""
Agent workflow nodes.

Each node receives and returns AgentState so LangGraph can orchestrate the
workflow while the API layer keeps its existing response contract.
"""
import logging
from datetime import datetime
from typing import Any, Dict

from backend.agent.state import AgentState
from backend.services.llm_service import (
    generate_canvas_spec,
    generate_deck_spec,
    generate_doc_content,
    format_im_context_for_prompt,
    generate_qa,
    generate_rehearsal,
    parse_intent as llm_parse_intent,
    plan_workflow as llm_plan_workflow,
)
from backend.services.delivery_service import archive_task
from backend.services.affine_service import affine_service
from backend.tools.tool_factory import ToolFactory

logger = logging.getLogger(__name__)


def _normalize_module(module: Any) -> str:
    """把模型返回的模块名统一成后端内部模块名。"""
    value = str(module or "").strip().upper()
    aliases = {
        "PPT": "DECK",
        "SLIDE": "DECK",
        "SLIDES": "DECK",
        "POWERPOINT": "DECK",
        "PRESENTATION": "DECK",
        "DOCUMENT": "DOC",
        "DOCUMENTS": "DOC",
        "DOCS": "DOC",
        "WHITEBOARD": "CANVAS",
        "BOARD": "CANVAS",
    }
    return aliases.get(value, value)


def _workflow_modules(state: AgentState) -> set[str]:
    """获取当前工作流里已经规划出的模块集合。"""
    return {_normalize_module(step.get("module")) for step in state.get("steps", [])}


def _content_types(state: AgentState) -> set[str]:
    return {str(item).strip().lower() for item in state.get("content_types", [])}


def _intent_with_im_context(state: AgentState) -> str:
    im_context = format_im_context_for_prompt(state.get("im_context_summary"))
    if not im_context:
        return state.get("intent", "")
    return f"{state.get('intent', '')}\n\n{im_context}"


def _agent_for_module(module: Any) -> str:
    module_name = _normalize_module(module)
    return {
        "IM_CONTEXT": "im_context_agent",
        "DOC": "doc_agent",
        "CANVAS": "canvas_agent",
        "DECK": "deck_agent",
        "REHEARSAL": "rehearsal_agent",
        "DELIVERY": "delivery_agent",
    }.get(module_name, "pilot_agent")


def _step_for_agent(agent: str, action: str) -> str:
    if agent == "im_context_agent":
        return "parse_intent"
    if agent == "doc_agent":
        return "generate_doc"
    if agent == "canvas_agent":
        return "generate_canvas"
    if agent == "deck_agent":
        return "generate_slides"
    if agent == "rehearsal_agent":
        return "generate_rehearsal"
    if agent == "delivery_agent":
        return "prepare_delivery"
    return action or "plan_workflow"


def _build_agent_plan(state: AgentState) -> Dict[str, Any]:
    """Convert planner output into an executable multi-agent task graph."""
    tasks = []
    previous_task_id = None

    intent_text = str(state.get("intent", ""))
    has_inline_im_context = any(marker in intent_text for marker in ["群聊上下文", "聊天记录", "讨论", "IM上下文", "IM 上下文"])
    if state.get("context_messages") or has_inline_im_context:
        tasks.append({
            "id": "task_1_im_context",
            "agent": "im_context_agent",
            "module": "IM_CONTEXT",
            "action": "summarize_context",
            "goal": "Extract decisions, open questions, and source material from IM context.",
            "depends_on": [],
            "step": "parse_intent",
            "status": "pending",
        })
        previous_task_id = tasks[-1]["id"]

    for step in state.get("steps", []):
        module = _normalize_module(step.get("module"))
        if module in {"DELIVERY", "UNKNOWN"}:
            continue
        if module == "IM_CONTEXT" and any(task["module"] == "IM_CONTEXT" for task in tasks):
            continue

        agent = _agent_for_module(module)
        action = step.get("action") or {
            "DOC": "create_doc",
            "CANVAS": "generate_canvas",
            "DECK": "generate_slides",
            "REHEARSAL": "generate_rehearsal",
            "IM_CONTEXT": "summarize_context",
        }.get(module, "execute")
        task_id = f"task_{len(tasks) + 1}_{agent.replace('_agent', '')}"
        depends_on = [previous_task_id] if previous_task_id else []
        tasks.append({
            "id": task_id,
            "agent": agent,
            "module": module,
            "action": action,
            "goal": step.get("goal") or f"{agent} will run {action}.",
            "depends_on": depends_on,
            "step": _step_for_agent(agent, action),
            "status": "pending",
            "needs_approval": bool(step.get("needs_approval", False)),
        })
        previous_task_id = task_id

    if needs_deck(state) and not any(task["agent"] == "rehearsal_agent" for task in tasks):
        tasks.append({
            "id": f"task_{len(tasks) + 1}_rehearsal",
            "agent": "rehearsal_agent",
            "module": "REHEARSAL",
            "action": "generate_rehearsal_and_qa",
            "goal": "Prepare speaker notes and likely Q&A for the generated deck.",
            "depends_on": [previous_task_id] if previous_task_id else [],
            "step": "generate_rehearsal",
            "status": "pending",
        })
        previous_task_id = tasks[-1]["id"]

    tasks.append({
        "id": f"task_{len(tasks) + 1}_delivery",
        "agent": "delivery_agent",
        "module": "DELIVERY",
        "action": "archive_and_share",
        "goal": "Package artifacts, archive the run, and share delivery links.",
        "depends_on": [previous_task_id] if previous_task_id else [],
        "step": "prepare_delivery",
        "status": "pending",
    })

    return {
        "architecture": "plan_and_execute",
        "pilot_agent": "pilot_agent",
        "planner_agent": "planner_agent",
        "goal": (state.get("workflow_plan") or {}).get("goal") or state.get("intent", ""),
        "agents": sorted({task["agent"] for task in tasks} | {"pilot_agent", "planner_agent", "sync_agent"}),
        "tasks": tasks,
        "artifacts": [],
        "checkpoints": [{
            "id": "checkpoint_final_review",
            "after_task": tasks[-2]["id"] if len(tasks) > 1 else tasks[-1]["id"],
            "type": "human_review",
            "status": "pending",
        }],
    }


def needs_doc(state: AgentState) -> bool:
    markers = {"doc", "document", "documents", "prd", "summary"}
    return bool(_content_types(state) & markers) or "DOC" in _workflow_modules(state)


def needs_deck(state: AgentState) -> bool:
    markers = {"ppt", "slide", "slides", "deck", "presentation", "powerpoint"}
    intent = str(state.get("intent", "")).lower()
    return bool(_content_types(state) & markers) or "DECK" in _workflow_modules(state) or any(
        marker in intent for marker in markers
    )


def needs_canvas(state: AgentState) -> bool:
    markers = {"canvas", "whiteboard", "diagram", "flowchart", "board"}
    intent = str(state.get("intent", "")).lower()
    return bool(_content_types(state) & markers) or "CANVAS" in _workflow_modules(state) or any(
        marker in intent for marker in markers
    )


def _normalize_slide_for_frontend(slide: Dict[str, Any], index: int) -> Dict[str, Any]:
    """把幻灯片内容整理成前端预览和 PPT 渲染都能消费的结构。"""
    content = slide.get("content", "")
    bullets = slide.get("bullets") or []

    if isinstance(content, dict):
        text_parts = []
        for value in content.values():
            if isinstance(value, list):
                text_parts.extend(str(item) for item in value)
            elif value is not None:
                text_parts.append(str(value))
        content = "\n".join(text_parts)
    elif isinstance(content, list):
        content = "\n".join(str(item) for item in content)

    if not content and bullets:
        content = "\n".join(str(item) for item in bullets)

    return {
        **slide,
        "index": slide.get("index", index),
        "title": slide.get("title", f"第 {index + 1} 页"),
        "content": content or "",
        "bullets": bullets,
    }


def _touch(state: AgentState, step: str, progress: float | None = None) -> AgentState:
    """更新节点状态和进度。"""
    state["current_step"] = step
    state["updated_at"] = datetime.utcnow().isoformat()
    if progress is not None:
        state["progress"] = progress
    return state


def _append_message(
    state: AgentState,
    role: str,
    content: str,
    step: str = None,
    requires_confirmation: bool = False,
    **kwargs,
) -> None:
    message = {
        "role": role,
        "content": content,
        "timestamp": state["updated_at"],
    }
    if step:
        message["step"] = step
    if requires_confirmation:
        message["requires_confirmation"] = True
    message.update(kwargs)
    state["messages"].append(message)


async def receive_input(state: AgentState) -> AgentState:
    """接收用户输入。"""
    state["status"] = "running"
    _touch(state, "receive_input", 0.05)

    logger.info("Task %s: received input - %s", state["task_id"], state["intent"][:100])

    _append_message(state, role="user", content=state["intent"], step="receive_input")
    _append_message(state, role="system", content="已接收需求，正在分析...", step="receive_input")

    return state


async def parse_intent(state: AgentState) -> AgentState:
    """解析用户意图。"""
    _touch(state, "parse_intent", 0.12)

    try:
        intent_result = await llm_parse_intent(state["intent"], state.get("context_messages", []))

        state["intent_analysis"] = intent_result
        state["content_types"] = intent_result.get("content_types", ["doc", "slides"])
        state["presentation_scene"] = state.get("presentation_scene") or intent_result.get("presentation_scene")
        state["audience"] = intent_result.get("audience", "管理层")
        state["constraints"] = intent_result.get("constraints", [])

        if state.get("presentation_scene"):
            intent_result["presentation_scene"] = state["presentation_scene"]

        analysis_text = (
            "**需求分析完成**\n\n"
            f"- 核心需求: {intent_result.get('intent_summary', '待分析')}\n"
            f"- 生成内容: {', '.join(state['content_types'])}\n"
            f"- 目标受众: {state['audience']}\n"
        )
        if state.get("presentation_scene"):
            analysis_text += f"- 演示场景: {state['presentation_scene']}\n"
        if intent_result.get("questions"):
            analysis_text += f"\n需要确认: {', '.join(intent_result['questions'])}"
            state["pending_questions"] = intent_result["questions"]

        _append_message(state, "assistant", analysis_text, "parse_intent")
    except Exception as exc:
        logger.exception("Error in parse_intent")
        _append_message(state, "assistant", f"分析出错: {str(exc)}", "parse_intent")
        state["content_types"] = ["doc", "slides"]

    return state


async def plan_workflow(state: AgentState) -> AgentState:
    """规划工作流。"""
    _touch(state, "plan_workflow", 0.2)

    try:
        context = {
            "content_types": state.get("content_types", []),
            "presentation_scene": state.get("presentation_scene"),
            "audience": state.get("audience", "管理层"),
            "constraints": state.get("constraints", []),
        }

        plan = await llm_plan_workflow(state["intent"], context)

        state["workflow_plan"] = plan
        state["steps"] = plan.get("steps", [])
        for step in state["steps"]:
            step["module"] = _normalize_module(step.get("module"))

        modules = _workflow_modules(state)
        if needs_doc(state) and "DOC" not in modules:
            state["steps"].append({"module": "DOC", "action": "create_doc", "needs_approval": False})
        if needs_canvas(state) and "CANVAS" not in modules:
            state["steps"].append({"module": "CANVAS", "action": "generate_canvas", "needs_approval": False})
        if needs_deck(state) and "DECK" not in modules:
            state["steps"].append({"module": "DECK", "action": "generate_slides", "needs_approval": False})

        plan_text = "**执行计划**\n\n"
        for index, step in enumerate(state["steps"]):
            module = step.get("module", "UNKNOWN")
            action = step.get("action", "unknown")
            approval_text = " [待确认]" if step.get("needs_approval", False) else ""
            plan_text += f"{index + 1}. {module} / {action}{approval_text}\n"

        _append_message(state, "assistant", plan_text, "plan_workflow")

        if state["steps"] and state["steps"][0].get("needs_approval"):
            state["waiting_approval"] = True
            _append_message(
                state,
                "assistant",
                '请确认计划是否正确，回复"继续"或提出修改意见。',
                "plan_workflow",
                requires_confirmation=True,
            )

        state["agent_plan"] = _build_agent_plan(state)
        agent_plan_text = "**Agent 编排计划**\n\n"
        for task in state["agent_plan"].get("tasks", []):
            deps = ", ".join(task.get("depends_on") or []) or "none"
            agent_plan_text += f"- {task['id']}: {task['agent']} / {task['action']} (depends_on: {deps})\n"
        _append_message(state, "assistant", agent_plan_text, "plan_workflow")

    except Exception as exc:
        logger.exception("Error in plan_workflow")
        _append_message(state, "assistant", f"规划出错: {str(exc)}", "plan_workflow")
        state["steps"] = [
            {"module": "DOC", "action": "create_doc", "needs_approval": False},
            {"module": "DECK", "action": "generate_slides", "needs_approval": False},
        ]
        state["agent_plan"] = _build_agent_plan(state)

    return state


async def extract_tasks(state: AgentState) -> AgentState:
    """提取具体任务。"""
    _touch(state, "extract_tasks", 0.3)

    tasks = []
    modules = _workflow_modules(state)

    if "DOC" in modules:
        tasks.extend(["理解并归纳文档结构", "生成文档初稿"])
    if "DECK" in modules:
        tasks.extend(["整理 PPT 结构和内容", "生成演示稿"])
    if "CANVAS" in modules:
        tasks.append("生成流程图或结构图")
    if "IM_CONTEXT" in modules:
        tasks.append("读取并分析群聊上下文")

    state["extracted_tasks"] = tasks
    _append_message(
        state,
        "assistant",
        f"**任务拆解完成** ({len(tasks)} 个子任务)\n\n" + "\n".join(f"- {task}" for task in tasks),
        "extract_tasks",
    )

    return state


async def generate_doc(state: AgentState) -> AgentState:
    """生成文档。"""
    _touch(state, "generate_doc", 0.5)
    logger.info("Task %s: generating document", state["task_id"])

    _append_message(state, "assistant", "正在生成文档...", "generate_doc")

    try:
        title = state.get("intent", "未命名文档")
        outline = (state.get("intent_analysis") or {}).get("outline")
        content = await generate_doc_content(title, _intent_with_im_context(state), outline)

        if not content:
            state["error"] = "文档内容生成失败"
            _append_message(state, "assistant", state["error"], "generate_doc")
            return state

        result = await ToolFactory.invoke_tool(
            "DocTool",
            {
                "action": "create_doc",
                "task_id": state["task_id"],
                "title": title,
                "content": content,
            },
        )

        if result.get("success"):
            state["doc_content"] = {
                "doc_id": result.get("doc_id"),
                "title": title,
                "content": content,
                "content_preview": content[:500] + "..." if len(content) > 500 else content,
                "doc_url": result.get("doc_url"),
                "lark_doc_id": result.get("doc_id") if result.get("provider") == "lark_docx" else None,
                "lark_doc_url": result.get("doc_url"),
                "version": 1,
            }
            state["doc_id"] = result.get("doc_id")
            _append_message(
                state,
                "assistant",
                f"**文档已生成**\n\n文档: **{title}**\n\n预览:\n```\n{state['doc_content']['content_preview']}\n```",
                "generate_doc",
            )
        else:
            state["error"] = f"文档保存失败: {result.get('error')}"
            _append_message(state, "assistant", state["error"], "generate_doc")

    except Exception as exc:
        logger.exception("Error generating doc")
        state["error"] = str(exc)
        _append_message(state, "assistant", f"生成失败: {str(exc)}", "generate_doc")

    return state


async def generate_canvas(state: AgentState) -> AgentState:
    """生成画布/白板结果。"""
    _touch(state, "generate_canvas", 0.6)

    _append_message(state, "assistant", "正在生成流程图/结构图...", "generate_canvas")
    try:
        spec = await generate_canvas_spec(
            title=state.get("intent", "Agent-Pilot 画布"),
            intent=state.get("intent", ""),
            doc_content="\n\n".join(
                item for item in [
                    (state.get("doc_content") or {}).get("content", ""),
                    format_im_context_for_prompt(state.get("im_context_summary")),
                ] if item
            ),
            steps=state.get("steps", []),
            # 本地 mock 画布不需要 LLM 参与，避免 Demo 卡在 generate_canvas。
            use_llm=affine_service.is_configured,
        )
        diagram_type = spec.get("diagram_type") or "flow"
        action = "create_architecture_diagram" if diagram_type == "architecture" else "create_flow_diagram"
        result = await ToolFactory.invoke_tool(
            "CanvasTool",
            {
                "action": action,
                "task_id": state["task_id"],
                "title": spec.get("title") or state.get("intent"),
                "nodes": spec.get("nodes", []),
                "edges": spec.get("edges", []),
                "layers": spec.get("layers", []),
            },
        )
        if not result.get("success"):
            state["error"] = f"画布生成失败: {result.get('error')}"
            _append_message(state, "assistant", state["error"], "generate_canvas")
            return state

        state["canvas_content"] = {
            "canvas_id": result.get("canvas_id"),
            "title": result.get("title") or spec.get("title"),
            "provider": result.get("provider"),
            "url": result.get("url"),
            "diagram_type": result.get("diagram_type") or diagram_type,
            "nodes": result.get("nodes") or spec.get("nodes", []),
            "edges": result.get("edges") or spec.get("edges", []),
            "layers": result.get("layers") or spec.get("layers", []),
        }
        _append_message(state, "assistant", "结构图已生成", "generate_canvas")
    except Exception as exc:
        logger.exception("Error generating canvas")
        state["error"] = str(exc)
        _append_message(state, "assistant", f"画布生成失败: {str(exc)}", "generate_canvas")

    return state


async def generate_slides(state: AgentState) -> AgentState:
    """生成 PPT。"""
    _touch(state, "generate_slides", 0.7)
    logger.info("Task %s: generating slides", state["task_id"])

    _append_message(state, "assistant", "正在生成演示稿...", "generate_slides")

    try:
        doc_content = "\n\n".join(
            item for item in [
                (state.get("doc_content") or {}).get("content", state["intent"]),
                format_im_context_for_prompt(state.get("im_context_summary")),
            ] if item
        )
        audience = state.get("audience", "管理层")
        presentation_scene = state.get("presentation_scene")

        deck_spec = await generate_deck_spec(
            title=state.get("intent", "演示稿"),
            doc_content=doc_content,
            audience=audience,
            presentation_scene=presentation_scene,
        )
        metadata = dict(deck_spec.get("metadata", {}))
        metadata.setdefault("feedback_history", [])
        metadata.setdefault("versions", [])
        deck_spec["metadata"] = metadata
        rehearsal = await generate_rehearsal(deck_spec)
        qa = await generate_qa(deck_spec, rehearsal)
        state["deck_spec"] = deck_spec

        raw_slides = deck_spec.get("slides", [])
        slides = [
            _normalize_slide_for_frontend(slide, index)
            for index, slide in enumerate(raw_slides)
        ]

        result = await ToolFactory.invoke_tool(
            "PPTTool",
            {
                "action": "create_slides",
                "task_id": state["task_id"],
                "title": deck_spec.get("title", state["intent"]),
                "slides": slides,
                "deck_spec": deck_spec,
            },
        )

        if result.get("success"):
            final_deck_spec = result.get("deck_spec") or deck_spec
            final_metadata = dict(final_deck_spec.get("metadata", metadata) or {})
            final_metadata.setdefault("feedback_history", [])
            final_metadata.setdefault("versions", [])
            final_slides = [
                _normalize_slide_for_frontend(slide, index)
                for index, slide in enumerate(final_deck_spec.get("slides", raw_slides))
            ]
            state["slides_content"] = {
                "slide_id": result.get("slide_id"),
                "title": final_deck_spec.get("title"),
                "slides": final_slides,
                "file_path": result.get("download_url") or result.get("file_path"),
                "theme": final_deck_spec.get("theme"),
                "visual_profile": final_deck_spec.get("visual_profile") or final_metadata.get("visual_profile"),
                "audience": final_deck_spec.get("audience"),
                "duration_minutes": final_deck_spec.get("duration_minutes"),
                "metadata": final_metadata,
                "rehearsal": rehearsal,
                "qa": qa.get("items", []),
                "feedback_history": final_metadata.get("feedback_history", []),
            }
            state["deck_spec"] = final_deck_spec
            state["slide_id"] = result.get("slide_id")

            slides_count = len(final_slides)
            slide_list = "\n".join(
                f"- 第 {slide.get('index', index) + 1} 页: {slide.get('title', '未命名')}"
                for index, slide in enumerate(final_slides[:5])
            )
            _append_message(
                state,
                "assistant",
                f"**演示稿已生成** ({slides_count} 页)\n\n{slide_list}" + ("\n- ..." if slides_count > 5 else ""),
                "generate_slides",
            )
        else:
            state["error"] = f"PPT 保存失败: {result.get('error')}"
            _append_message(state, "assistant", state["error"], "generate_slides")

    except Exception as exc:
        logger.exception("Error generating slides")
        state["error"] = str(exc)
        _append_message(state, "assistant", f"生成失败: {str(exc)}", "generate_slides")

    return state


async def confirm_or_modify(state: AgentState) -> AgentState:
    """等待用户确认或修改。"""
    _touch(state, "confirm_or_modify", 0.85)

    _append_message(
        state,
        "assistant",
        '**初稿已完成**\n\n请提出修改意见，或输入"确认交付"完成本次任务。',
        "confirm_or_modify",
        requires_confirmation=True,
    )

    return state


async def deliver_result(state: AgentState) -> AgentState:
    """交付结果。"""
    _touch(state, "deliver_result", 1.0)
    state["status"] = "failed" if state.get("error") else "completed"

    delivery = {
        "status": state["status"],
        "message": state.get("error") or "任务完成",
        "progress": state["progress"],
    }

    if state.get("doc_content"):
        doc_payload = {
            "title": state["doc_content"].get("title"),
            "doc_id": state["doc_content"].get("doc_id"),
            "content": state["doc_content"].get("content"),
            "preview": state["doc_content"].get("content_preview"),
            "doc_url": state["doc_content"].get("doc_url"),
            "lark_doc_id": state["doc_content"].get("lark_doc_id"),
            "lark_doc_url": state["doc_content"].get("lark_doc_url"),
            "version": state["doc_content"].get("version", 1),
        }
        delivery["document"] = doc_payload
        delivery["doc"] = doc_payload

    if state.get("slides_content"):
        slides_payload = {
            "title": state["slides_content"].get("title"),
            "slide_id": state["slides_content"].get("slide_id"),
            "slides": state["slides_content"].get("slides", []),
            "slides_count": len(state["slides_content"].get("slides", [])),
            "file_path": state["slides_content"].get("file_path"),
            "theme": state["slides_content"].get("theme"),
            "audience": state["slides_content"].get("audience"),
            "duration_minutes": state["slides_content"].get("duration_minutes"),
            "metadata": state["slides_content"].get("metadata", {}),
            "rehearsal": state["slides_content"].get("rehearsal"),
            "qa": state["slides_content"].get("qa", []),
            "feedback_history": state["slides_content"].get("feedback_history", []),
        }
        delivery["slides"] = slides_payload
        delivery["deck"] = slides_payload

    if state.get("canvas_content"):
        delivery["canvas"] = state["canvas_content"]

    if state["status"] == "completed":
        try:
            archive = await archive_task(
                task_id=state["task_id"],
                title=state.get("intent", "Agent-Pilot 任务"),
                doc_id=(state.get("doc_content") or {}).get("doc_id"),
                slide_id=(state.get("slides_content") or {}).get("slide_id"),
                canvas_id=(state.get("canvas_content") or {}).get("canvas_id"),
                files=[{"type": "pptx", "path": (state.get("slides_content") or {}).get("file_path")}]
                if (state.get("slides_content") or {}).get("file_path")
                else [],
            )
            delivery["archive"] = archive.to_dict()
        except Exception as exc:
            logger.warning("Failed to archive task %s: %s", state["task_id"], str(exc))

    state["result"] = delivery

    card_text = "**任务完成**\n\n"
    if state.get("doc_content"):
        card_text += f"文档: {state['doc_content'].get('title')}\n"
    if state.get("slides_content"):
        slides_info = state["slides_content"]
        card_text += f"PPT: {slides_info.get('title')} ({len(slides_info.get('slides', []))} 页)\n"
    if state.get("canvas_content"):
        card_text += "结构图: 已生成\n"
    card_text += "\n输入“排练”可以获取演讲提示。"

    _append_message(state, "assistant", card_text, "deliver_result")
    _append_message(state, "system", "结果已交付", "deliver_result")

    return state


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
