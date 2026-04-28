# Agent-Pilot

Agent-Pilot 是一个面向办公协同场景的 IM Agent 原型项目。它把 IM 对话中的自然语言需求转换为可执行任务流，自动完成需求理解、流程规划、文档生成、PPT 生成，并通过网页端或飞书 bot 完成交付。

当前版本重点跑通比赛 Demo 的主链路：

```text
飞书/网页输入（文字+语音）-> Agent 理解与规划 -> 生成文档 -> 生成 PPT -> 本地预览下载/飞书 bot 回传
```

## 功能概览

| 模块 | 当前能力 |
| --- | --- |
| IM 入口 | 支持飞书 bot 接收文本/语音消息，网页端支持文字输入和语音录制 |
| 场景选择 | 管理层汇报、项目评审、方案提案、复盘总结、培训讲解 |
| Agent 流程 | 后端按 receive、parse、plan、extract、doc、slides、confirm、deliver 等节点推进 |
| LLM 接入 | 使用 OpenAI-compatible Chat Completions 接口，可通过 `.env` 切换模型和 base url |
| 文档生成 | 生成结构化 Markdown 文档，可写入飞书云文档（Docx API） |
| PPT 生成 | 生成 DeckSpec/页面数据，支持 3 套主题 + 4 种布局 + 演示场景适配，导出本地 `.pptx` 文件 |
| 语音识别 | 前端录音 PCM16k 编码，后端调用飞书 ASR 语音转写 |
| 飞书交互卡片 | 进度卡片 + 交付卡片（含确认/修改按钮），替代纯文本消息 |
| 网页端 | 三栏工作台：左侧输入（文字+语音+场景），中间流程进度，右侧文档/PPT 预览 |
| 飞书 bot | 基于飞书 OpenAPI 发送交互卡片、文件，卡片按钮回调确认/修改 |
| 多端同步 | SyncService 内存/Redis 双模式，Orchestrator 广播进度/交付，前端多标签页同步 |
| 数据存储 | 默认使用 SQLite，任务、文档、PPT 等数据落库 |

## 前端布局

前端是一个三栏工作台：

| 区域 | 内容 |
| --- | --- |
| 左侧 | 消息输入、语音录制、场景选择、消息记录 |
| 中间 | Agent 状态和流程进度 |
| 右侧 | 文档预览和 PPT 预览 |

左侧输入区支持两种输入方式：

- 直接打字，然后点击发送
- 点击语音录音，识别结果会填入输入框，确认后点击发送

场景选择也在左侧输入区内，发送消息时会一起传给后端。

## 场景说明

不同场景共用同一套 Agent 流程，但会影响内容结构和 PPT 表达重点：

| 场景 | 侧重点 |
| --- | --- |
| 管理层汇报 | 先结论后细节，强调结果、价值、决策点 |
| 项目评审 | 强调方案、计划、风险、依赖 |
| 方案提案 | 强调痛点、机会、价值、收益和落地路径 |
| 复盘总结 | 强调结果回顾、问题分析、经验沉淀、改进动作 |
| 培训讲解 | 结构更细，讲解性更强，适合教学和知识传递 |

## 语音识别

项目使用飞书 ASR 进行语音转写。

前端录音后会先在浏览器内转换为：

- `16kHz`
- `mono`
- `PCM16`
- 原始 `.pcm` 字节

然后后端调用飞书 `speech/v1/speech/recognize` 接口识别。

## 需求完成情况

根据 `temp/require.pdf` 的赛题要求，当前项目状态如下：

| 需求项 | 状态 | 说明 |
| --- | --- | --- |
| IM 作为 Agent 入口 | 已完成 | 已接入飞书 bot 文本/语音消息，网页端也可触发任务 |
| Agent 任务理解与规划 | 已完成 | 后端已有意图解析、流程规划、任务抽取等节点 |
| 文档生成 | 已完成 | 可生成文档并写入飞书云文档，前端可跳转飞书编辑 |
| PPT 生成与导出 | 已完成 | 支持多主题多布局+演示场景适配，导出带视觉效果的 `.pptx` 文件 |
| 交付结果 | 已完成 | 网页端可下载，飞书交互卡片含确认/修改按钮，bot 回传文件 |
| 多端实时同步 | 已完成 | WebSocket + SyncService（内存/Redis），多标签页进度同步 |
| 文档/白板编辑 | 部分完成 | 飞书云文档可编辑，编辑后回写状态待完善；白板/画布未接入 |
| PPT 修改和演练 | 部分完成 | 卡片交互回调支持确认/修改，演练模型已定义但未接入 workflow |
| 自然语言文本/语音指令 | 已完成 | 文本指令已支持，语音指令通过飞书 ASR 已接入 |
| 飞书或类似 OpenAPI 集成 | 已完成 | bot 消息收发、交互卡片、文件上传/发送、云文档写入、语音转写已接入 |
| 离线和冲突合并 | 未完成 | 暂未实现离线编辑、CRDT/OT 或冲突解决策略 |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Backend | FastAPI、LangChain、LangGraph、SQLAlchemy、aiosqlite、httpx、python-pptx |
| Frontend | React、TypeScript、Vite、Tailwind CSS、Zustand |
| Bot | Node.js、`@larksuiteoapi/node-sdk` |
| Database | SQLite，后续可替换为 PostgreSQL |
| IM Integration | 飞书 OpenAPI（消息、卡片、文档、语音） |

## 目录结构

```text
IM_agent/
├── backend/
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 后端配置加载
│   ├── api/                     # REST、WebSocket、飞书事件回调接口
│   ├── agent/                   # Agent 编排和节点逻辑
│   ├── database/                # SQLAlchemy 模型和数据库连接
│   ├── services/                # LLM、飞书 bot、PPT 渲染、语音转写、交付等服务
│   └── tools/                   # Agent 可调用工具
├── frontend/                    # React + Vite 网页端
├── feishu-bot/                  # 飞书 bot 长连接服务
├── docs/                        # 文档
├── temp/                        # 临时文档和需求材料，本地使用
├── requirements.txt             # 后端 Python 依赖
└── README.md
```

## 快速开始

### 1. 后端环境

项目当前使用 Python 3.11 更稳定。Windows + Conda 示例：

```powershell
conda activate IM_agent
cd D:\IM_agent
python -m pip install -r requirements.txt
```

复制环境变量示例并填写：

```powershell
Copy-Item backend\.env.example backend\.env
```

后端启动：

```powershell
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

常用地址：

| 地址 | 说明 |
| --- | --- |
| `http://localhost:8000/api/health` | 健康检查 |
| `http://localhost:8000/docs` | FastAPI Swagger |
| `ws://localhost:8000/api/ws/sessions/{session_id}` | 会话 WebSocket |

### 2. 前端环境

```powershell
cd D:\IM_agent\frontend
npm install
npm run dev
```

Vite 默认会把 `/api` 代理到后端。访问前端页面后，可以直接输入需求并查看执行进度、文档预览和 PPT 下载。

### 3. 飞书 bot 环境

```powershell
cd D:\IM_agent\feishu-bot
npm install
node index.js
```

飞书 bot 用于接收飞书消息并转发给后端。后端执行完成后，会使用飞书 OpenAPI 把进度消息和 PPT 文件发回原聊天。

## 飞书 Bot 配置

在飞书开放平台中配置事件订阅地址：

```text
https://your-domain.com/api/im/lark/events
```

如果使用飞书卡片回调，配置：

```text
https://your-domain.com/api/im/lark/card/action
```

需要启用的能力通常包括：

- 接收消息事件
- 读取消息资源
- 发送消息
- 上传/发送文件
- 语音识别相关权限
- 云文档创建和写入

## 环境变量

后端环境变量写在 `backend/.env`，字段说明见 `backend/.env.example`。核心配置如下：

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | LLM API Key |
| `OPENAI_BASE_URL` | OpenAI-compatible API 地址 |
| `LLM_MODEL` | 使用的模型名称 |
| `DATABASE_URL` | 数据库地址，默认 SQLite |
| `LARK_APP_ID` | 飞书开放平台应用 App ID |
| `LARK_APP_SECRET` | 飞书开放平台应用 App Secret |
| `LARK_VERIFICATION_TOKEN` | 飞书事件订阅校验 token，可为空 |
| `LARK_BOT_ENABLED` | 是否启用飞书 bot 后端能力 |
| `LARK_BOT_REQUIRE_MENTION` | 群聊中是否要求 @bot 才处理消息 |
| `LARK_DEFAULT_CHAT_ID` | 可选默认群 ID，用于部分交付场景 |
| `LARK_CARD_CALLBACK_URL` | 飞书卡片请求网址，在飞书开放平台 Bot 配置中设置 |
| `VOICE_TRANSCRIPTION_ENABLED` | 是否启用语音转写 |
| `FEISHU_ASR_ENABLED` | 是否启用飞书 ASR |
| `FEISHU_ASR_FORMAT` | 飞书 ASR 音频格式，默认 `pcm` |
| `FEISHU_ASR_ENGINE_TYPE` | 飞书 ASR 引擎类型，默认 `16k_auto` |

`feishu-bot` 目录下也需要按该目录的示例配置 bot 运行参数，至少要保证 bot 能连接飞书并知道后端地址。

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 后端健康检查 |
| `POST` | `/api/sessions` | 创建网页端会话 |
| `GET` | `/api/sessions/{id}` | 查询会话 |
| `GET` | `/api/sessions/{id}/messages` | 查询会话事件消息 |
| `POST` | `/api/sessions/{id}/messages` | 发送需求并触发 Agent 流程 |
| `POST` | `/api/voice/transcriptions` | 前端语音转写 |
| `GET` | `/api/tasks/{id}` | 查询任务状态 |
| `POST` | `/api/tasks/{id}/confirm` | 确认或修改任务 |
| `GET` | `/api/documents/{id}` | 获取生成文档 |
| `GET` | `/api/slides/{id}` | 获取生成 PPT 数据 |
| `GET` | `/api/files/slides/{filename}` | 下载本地 PPT 文件 |
| `POST` | `/api/im/lark/events` | 飞书事件订阅回调 |
| `POST` | `/api/im/lark/card/action` | 飞书卡片交互回调（确认交付/需要修改） |
| `WS` | `/api/ws/sessions/{id}` | 网页端实时进度推送 |

## 常见问题

### 飞书 ASR 返回 `1040101 invalid param`

优先检查：

- `FEISHU_ASR_FORMAT=pcm`
- 前端是否已经重新构建并加载最新代码
- 后端是否重启
- 飞书应用是否有语音识别相关权限
- `LARK_APP_ID` 和 `LARK_APP_SECRET` 是否正确

### 前端显示 Agent 未连接

检查后端是否运行，并确认前端代理能访问：

```text
/api/ws/sessions/{session_id}
```

如果后端重启过，刷新前端页面通常会重新创建 session 并连接 WebSocket。

## Roadmap

已完成：

- [x] 网页端输入、进度展示、文档预览、PPT 预览和下载
- [x] Agent 基础工作流：接收输入、解析需求、规划流程、生成文档、生成 PPT、交付结果
- [x] 后端本地 `.pptx` 文件生成和下载接口
- [x] 飞书 bot 文本消息入口
- [x] 飞书 OpenAPI 文本消息发送、文件上传和文件消息发送
- [x] README 和 `.env.example` 基础文档
- [x] PPT 主题模板系统（business_blue / tech_dark / minimal 三套主题，4 种布局渲染）
- [x] 飞书云文档写入（Docx API 创建文档 + Markdown 转 Block 写入）
- [x] 飞书交互卡片（进度卡片 + 交付卡片，替代纯文本消息）
- [x] 多端 SyncService 接入（Orchestrator 广播进度/交付，前端 session.sync 事件处理）
- [x] LLM 主题推荐（DeckSpecModel 新增 theme 字段）
- [x] 飞书卡片交互回调（确认交付/需要修改按钮 + POST /api/im/lark/card/action 端点）
- [x] 多端同步 Redis 模式验证（内存/Redis 双通道测试通过）
- [x] 语音输入（前端录音 + 飞书 ASR 转写 + VoiceTranscriber 组件）
- [x] 演示场景选择（5 种场景适配不同 PPT 风格和内容侧重）

进行中：

- [ ] 文档在线编辑体验优化（飞书文档编辑后回写状态）

待实现：

- [ ] 白板/自由画布生成和编辑
- [ ] PPT 反馈修改、演练稿和 Q&A 训练闭环
- [ ] 离线编辑、冲突检测和冲突合并
- [ ] 权限、审批和团队协作治理
- [ ] 更完整的自动化测试和部署文档

## License

Internal / Competition use.
