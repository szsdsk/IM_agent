# Plan-and-Execute Demo Testing

This file contains ready-to-run demo prompts for the multi-agent flow. The
same payloads are also available as JSON in `data/demo_agent_requests.json`.

## Full Chain Demo

Use this to verify the complete flow:

```text
请根据下面这次产品讨论，先生成一份需求文档，再生成流程图画布，最后生成一份5分钟管理层汇报PPT，并准备逐页讲稿和可能被问到的Q&A。

群聊上下文：
- 产品经理：我们要在下个版本上线“客户续费风险预警”，目标是提前14天发现高风险客户。
- 销售负责人：希望能看到风险等级、关键原因、建议跟进动作，并且能把结果推送到飞书群。
- 数据同学：第一版可以使用登录频次下降、工单数量上升、合同到期时间、核心功能使用率四类信号。
- 客服负责人：需要把高风险客户同步给客户成功经理，避免重复打扰客户。
- 研发负责人：本期建议先做规则引擎，不做复杂机器学习模型；两周内完成MVP。
- 设计同学：页面上需要一个客户列表、风险标签、原因说明和一键生成跟进话术。

产出要求：
1. 文档包含背景、目标、用户角色、核心流程、MVP范围、风险与里程碑。
2. 画布用流程图表达从数据采集到飞书通知的闭环。
3. PPT面向管理层，重点突出业务价值、落地路径和风险控制。
```

Expected visible steps:

```text
receive_input
parse_intent
plan_workflow
extract_tasks
generate_doc
generate_canvas
generate_slides
generate_rehearsal
prepare_delivery
confirm_or_modify
deliver_result
```

Expected agents:

```text
pilot_agent
planner_agent
doc_agent
canvas_agent
deck_agent
rehearsal_agent
delivery_agent
sync_agent
```

## Canvas-First Demo

```text
请先生成一张系统架构图画布，再基于架构图生成项目评审PPT。主题是“企业知识库智能问答系统”。

实际内容：系统包含飞书文档同步、文档解析、向量索引、权限过滤、RAG问答、答案引用溯源、反馈闭环。桌面端负责管理知识库和查看问答日志，移动端负责随时提问和接收答案卡片。请把架构分成数据接入层、索引层、问答层、协同端和监控层。
```

## Deck-Only Demo

```text
不用生成文档，直接做一份6页客户提案PPT，并生成讲稿和Q&A。主题是“为连锁零售门店提供AI巡店助手”。内容包括：门店陈列合规检查、货架缺货识别、促销物料识别、异常照片自动归档、店长日报、区域经理周报。目标客户是零售运营负责人，语气要偏商业提案。
```

## Targeted Feedback Demo

Run this after a deck exists:

```text
把第4页改成风险与应对，不要继续讲功能；补充数据质量、销售跟进负担、飞书通知打扰三类风险，每类给一个缓解动作。
```

## API Smoke Test

```powershell
$demo = Get-Content data\demo_agent_requests.json -Raw | ConvertFrom-Json

$session = Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/api/v1/sessions `
  -ContentType "application/json" `
  -Body (@{ user_id = $demo.session_user } | ConvertTo-Json)

$scenario = $demo.scenarios | Where-Object { $_.id -eq "full_chain_product_launch" }
$body = @{
  content = $scenario.content
  user_id = $demo.session_user
  presentation_scene = $scenario.presentation_scene
} | ConvertTo-Json -Depth 8

$task = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/sessions/$($session.id)/messages" `
  -ContentType "application/json" `
  -Body $body

$task.result_json.agent_plan.tasks | Format-Table id, agent, action, step, status
$task.result_json.artifacts
$task.result_json.result.canvas
```
