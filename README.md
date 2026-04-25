# Agent-Pilot

基于 IM 的办公协同智能助手。把群聊里的需求一句话或一段对话，自动转化为**文档（PRD）+ 演示稿（PPT）+ 流程图/画布**，并以**交付卡片**回投到 IM。

> 当前为 MVP 基线版本：后端工作流已端到端跑通（意图分析 → 规划 → 文档生成 → PPT 生成 → 交付）。

---

## 核心能力

| 模块 | 能力 |
|---|---|
| **意图理解** | LLM 解析用户输入，识别内容类型（doc/slides/canvas/summary）、目标受众、约束条件 |
| **任务规划** | 自动拆解为有序子任务，关键节点支持人工确认（`needs_approval`） |
| **文档生成** | PRD 模板（背景/目标/需求详情/里程碑/风险），Markdown 输出，可对接 AFFiNE |
| **PPT 生成** | DeckSpec 中间格式 → Slidev Markdown / `python-pptx` PPTX / PDF |
| **画布生成** | 流程图、架构图（AFFiNE Canvas） |
| **排练材料** | 每页讲稿、预计时间、Q&A 预测、提示要点 |
| **多端同步** | Redis Pub/Sub + WebSocket（含内存模式 fallback） |
| **交付归档** | 结构化 DeliveryCard（Markdown + Rocket.Chat 卡片格式），JSON 文件落盘 |

---

## 架构

```
┌──────────────────────────────────────────────────────┐
│                     Frontend                         │
│           (AgentPanel / DeliveryCard)                │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼───────────────────────────────┐
│              FastAPI Backend (main.py)               │
│  ┌─────────────────────────────────────────────────┐ │
│  │           Agent Orchestrator                    │ │
│  │  receive → parse → plan → extract → doc        │ │
│  │      → canvas → slides → confirm → deliver     │ │
│  └─────────────────────────────────────────────────┘ │
└──┬─────────┬────────┬─────────┬────────┬─────────┬───┘
   │         │        │         │        │         │
┌──▼──┐  ┌───▼──┐  ┌──▼───┐  ┌──▼──┐  ┌──▼───┐  ┌──▼──┐
│ LLM │  │Rocket│  │AFFiNE│  │Deck │  │Sync  │  │Deliv│
│Mini │  │.Chat │  │ Doc/ │  │Spec/│  │Redis/│  │ery  │
│ Max │  │      │  │Canvas│  │Rendr│  │ WS   │  │Card │
└─────┘  └──────┘  └──────┘  └─────┘  └──────┘  └─────┘
```

---

## 工作流状态机

```
created → planning → waiting_approval → generating_doc
                                        ↓
                     archived ← delivered ← reviewing ← generating_deck
```

每个节点产出 emoji 化的进度消息（`📋 需求分析完成`、`📄 文档已生成`、`📊 演示稿已生成` 等）。

---

## 快速开始

### 1. 依赖

```bash
pip install -r requirements.txt
```

主要依赖：`fastapi`、`uvicorn`、`httpx`、`pydantic`、`python-pptx`、`sqlalchemy`、`aiosqlite`、`redis`。

### 2. 配置

复制 `backend/.env.example` 为 `backend/.env`（或直接编辑 `backend/.env`）：

```env
OPENAI_API_KEY=<your-minimax-key>
OPENAI_BASE_URL=https://api.minimaxi.com/v1
LLM_MODEL=abab6.5s-chat

# 可选 - 真实集成（不填则走 mock）
ROCKET_CHAT_URL=https://your-rocketchat-instance
ROCKET_CHAT_USER=pilot-bot
ROCKET_CHAT_PASSWORD=...
AFFINE_URL=https://your-affine-instance
AFFINE_TOKEN=...

DEBUG=true
MOCK_MODE=true
```

### 3. 启动

```bash
cd IM_agent
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

服务启动后访问：
- API 根：`http://localhost:8000/`
- API 文档：`http://localhost:8000/docs`
- WebSocket：`ws://localhost:8000/api/ws/sessions/{session_id}`

### 4. 端到端调用

```bash
# 创建 session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"alice"}' | jq -r .id)

# 发送需求
curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content":"帮我写一份关于AI Agent的产品需求文档，目标受众是管理层"}'
```

---

## 目录结构

```
IM_agent/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── config.py                  # 配置加载（含 MiniMax 适配）
│   ├── .env                       # 本地配置（gitignored）
│   ├── agent/
│   │   ├── orchestrator.py        # 工作流编排
│   │   ├── nodes.py               # 9 个节点（接入 LLM）
│   │   └── state.py               # AgentState 类型
│   ├── api/
│   │   ├── endpoints.py           # REST + WebSocket
│   │   └── schemas.py             # Pydantic 模型
│   ├── database/                  # SQLAlchemy + SQLite
│   ├── services/
│   │   ├── llm_service.py         # MiniMax 客户端 + 6 套 prompts
│   │   ├── rocket_chat_service.py # IM 集成
│   │   ├── affine_service.py      # 文档/画布服务
│   │   ├── deck_spec.py           # PPT 中间格式
│   │   ├── deck_renderer.py       # Slidev / PPTX / PDF 渲染
│   │   ├── delivery_service.py    # 交付卡片 + 归档
│   │   └── sync_service.py        # 多端同步
│   └── tools/
│       ├── doc_tool.py            # 文档工具
│       ├── ppt_tool.py            # PPT 工具（接入 DeckSpec）
│       ├── im_tool.py             # IM 工具
│       └── lark_tool.py           # 飞书工具
├── frontend/                       # React + Vite（待改造）
├── requirements.txt
└── .gitignore
```

---

## LLM Prompt 模板

`backend/services/llm_service.py` 中预置了 6 套 system prompt：

| 名称 | 用途 |
|---|---|
| `intent_parser` | 解析用户意图，输出 JSON（intent_summary / content_types / audience / constraints / questions） |
| `planner` | 工作流规划，输出 steps（module + action + needs_approval） |
| `doc_writer` | PRD 文档撰写（背景/目标/需求详情/里程碑/风险） |
| `slides_generator` | PPT 结构生成（DeckSpec JSON） |
| `summarizer` | 群聊上下文总结（话题/观点/共识/待办/决策） |
| `rehearsal` | 排练材料（讲稿/时长/Q&A/提示） |

---

## API 概要

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/sessions` | 创建会话 |
| `GET` | `/api/sessions/{id}` | 查询会话 |
| `GET` | `/api/sessions/{id}/messages` | 历史消息 |
| `POST` | `/api/sessions/{id}/messages` | 发送需求并触发工作流 |
| `GET` | `/api/tasks/{id}` | 查询任务 |
| `POST` | `/api/tasks/{id}/confirm` | 确认/否决待审批节点 |
| `GET` | `/api/documents/{id}` | 获取文档 |
| `GET` | `/api/slides/{id}` | 获取 PPT |
| `WS` | `/api/ws/sessions/{id}` | 实时推送进度 |

---

## 路线图

### 已完成（基线 v0.1）
- [x] LLM 服务（MiniMax 适配）
- [x] 9 节点工作流（接入 LLM）
- [x] 文档生成（PRD）
- [x] PPT 生成（DeckSpec → PPTX/Slidev/PDF）
- [x] 交付卡片 + 归档
- [x] 多端同步服务（含 mock）
- [x] FastAPI + WebSocket 端到端

### 待办（v0.2+）
- [ ] 前端 AgentPanel / DeliveryCard 组件
- [ ] Rocket.Chat 真实实例对接
- [ ] AFFiNE 真实实例对接
- [ ] Redis 多端联调
- [ ] 块级文档协作（CRDT/OT）
- [ ] 排练模式 UI
- [ ] 角色权限 / 审批流

---

## License

Internal / Competition use.
