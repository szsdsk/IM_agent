# Agent-Pilot

Agent-Pilot 是一个面向 IM 办公场景的智能内容生成助手。用户可以通过网页端或飞书 Bot 输入需求，系统会自动完成需求理解、任务规划、文档生成、PPT 生成、语音转写、进度同步和结果交付。

当前主链路：

```text
文字/语音输入 -> 场景选择 -> LangGraph Agent 工作流 -> 文档/PPT 生成 -> 网页预览下载/飞书 Bot 交付
```

## 功能概览

| 模块 | 当前能力 |
|---|---|
| 前端工作台 | 三栏布局：输入区、Agent 进度区、文档/PPT 预览区 |
| 文本输入 | 网页端文本输入、飞书 Bot 文本消息接入 |
| 语音输入 | 网页端录音转写、飞书语音消息下载和 ASR 转写 |
| 场景选择 | 支持管理汇报、项目评审、方案提案、复盘总结、培训讲解 |
| Agent 工作流 | 使用 LangGraph 编排 receive、parse、plan、doc、canvas、slides、confirm、deliver 等节点 |
| LLM 调用 | 使用 LangChain + OpenAI-compatible ChatOpenAI，支持 `OPENAI_BASE_URL` 切换供应商 |
| 工具层 | 使用 LangChain StructuredTool 封装文档、PPT、IM 工具 |
| 文档生成 | 生成 Markdown 文档内容，并落库用于前端预览和后续修改 |
| PPT 生成 | 生成 DeckSpec，并渲染本地 PPTX，支持不同演示场景主题 |
| 飞书集成 | 支持事件回调、消息发送、语音资源下载、ASR、文件上传、交付卡片回调 |
| 实时状态 | 前端通过 WebSocket 展示当前步骤、进度和执行消息 |
| 多端同步 | 已有 Redis/WebSocket 同步服务，Redis 不可用时回退内存模式 |

## 当前进度

项目已经是可运行的 MVP，核心链路已经打通：

- 网页端可以输入文字或录音，触发后端 Agent。
- 飞书 Bot 可以接收文本/语音消息，触发同一套 Agent 工作流。
- 后端可以生成文档和 PPT，并把结果写入数据库。
- 前端可以预览文档、预览 PPT 数据并下载生成的 PPTX。
- 飞书侧可以收到进度消息、交付消息和生成的 PPT 文件。
- LangChain/LangGraph 已经接入到模型调用、工作流编排和工具调用层。

还需要继续打磨的是：PPT 视觉质量、多人协同体验、飞书云文档深度写入、更多自动化测试和生产部署细节。

## 技术栈

| 层级 | 技术 |
|---|---|
| Backend | FastAPI、LangChain、LangGraph、SQLAlchemy、aiosqlite、httpx、python-pptx |
| Frontend | React、TypeScript、Vite、Tailwind CSS、Zustand |
| Bot | Node.js、`@larksuiteoapi/node-sdk` |
| Database | SQLite，后续可替换 PostgreSQL |
| IM Integration | 飞书 OpenAPI，Rocket.Chat 服务封装仍保留 |
| Realtime | WebSocket、Redis Pub/Sub fallback |

## 快速开始

### 1. 安装后端依赖

推荐使用 Python 3.11：

```powershell
conda activate IM_agent
cd D:\IM_agent
python -m pip install -r requirements.txt
```

如果只在 `backend` 目录维护依赖，也可以执行：

```powershell
python -m pip install -r backend\requirements.txt
```

### 2. 配置环境变量

复制示例配置：

```powershell
Copy-Item backend\.env.example backend\.env
```

核心配置：

```env
DEBUG=true
MOCK_MODE=false

OPENAI_API_KEY=your_llm_api_key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your_model

IM_PROVIDER=lark
LARK_BOT_ENABLED=true
LARK_BOT_REQUIRE_MENTION=true
LARK_APP_ID=your_feishu_app_id
LARK_APP_SECRET=your_feishu_app_secret
LARK_VERIFICATION_TOKEN=your_event_verification_token

VOICE_TRANSCRIPTION_ENABLED=true
FEISHU_ASR_ENABLED=true
FEISHU_ASR_FORMAT=pcm
FEISHU_ASR_ENGINE_TYPE=16k_auto
```

飞书 ASR 当前只走飞书 OpenAPI，不依赖外部 Whisper/ASR 服务。

### 3. 启动后端

```powershell
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

常用地址：

| 地址 | 说明 |
|---|---|
| `http://localhost:8000/api/health` | 健康检查 |
| `http://localhost:8000/docs` | FastAPI Swagger |
| `ws://localhost:8000/api/ws/sessions/{session_id}` | 会话 WebSocket |

### 4. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://localhost:5173
```

### 5. 启动飞书 Bot 长连接服务

```powershell
cd feishu-bot
npm install
node index.js
```

飞书开放平台配置见 [docs/feishu-bot-setup.md](docs/feishu-bot-setup.md)。

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 后端健康检查 |
| `POST` | `/api/sessions` | 创建前端会话 |
| `GET` | `/api/sessions/{session_id}` | 查询会话 |
| `GET` | `/api/sessions/{session_id}/messages` | 查询会话消息 |
| `POST` | `/api/sessions/{session_id}/messages` | 发送文字需求并触发 Agent |
| `POST` | `/api/voice/transcriptions` | 前端语音转写 |
| `POST` | `/api/im/lark/events` | 飞书事件回调 |
| `POST` | `/api/im/lark/card/action` | 飞书卡片交互回调 |
| `GET` | `/api/tasks/{task_id}` | 查询任务 |
| `POST` | `/api/tasks/{task_id}/confirm` | 确认或修改任务 |
| `GET` | `/api/documents/{document_id}` | 获取文档 |
| `GET` | `/api/slides/{slide_id}` | 获取 PPT 数据 |
| `GET` | `/api/files/slides/{filename}` | 下载生成的 PPTX |
| `WS` | `/api/ws/sessions/{session_id}` | 前端实时进度推送 |

## 目录结构

```text
IM_agent/
├── backend/
│   ├── api/                 # REST、WebSocket、飞书事件回调
│   ├── agent/               # LangGraph 工作流与节点
│   ├── database/            # SQLAlchemy 模型和连接
│   ├── services/            # LLM、飞书、语音、PPT 渲染等服务
│   └── tools/               # LangChain StructuredTool 工具
├── docs/                    # 配置和集成文档
├── feishu-bot/              # 飞书 Bot 长连接服务
├── frontend/                # React + Vite 前端
├── requirements.txt
└── README.md
```

## Roadmap

已完成：

- [x] 网页端文字输入、语音录制、场景选择
- [x] 飞书 Bot 文本消息接入
- [x] 飞书 Bot 语音消息下载和 ASR 转写
- [x] LangChain 模型调用封装
- [x] LangGraph 条件工作流编排
- [x] LangChain StructuredTool 工具层
- [x] 文档生成和数据库落库
- [x] PPT DeckSpec 生成、本地 PPTX 渲染和下载
- [x] PPT 主题/场景化模板基础能力
- [x] 飞书消息、文件交付和卡片交互回调
- [x] WebSocket 进度推送
- [x] Redis 同步服务和内存 fallback
- [x] README、环境变量示例、飞书 Bot 配置文档

进行中：

- [ ] 提升 PPT 视觉质量和内容密度控制
- [ ] 飞书云文档真实写入和权限管理
- [ ] 多轮修改体验：用户反馈后精准修改文档/PPT
- [ ] 前端任务历史列表和任务恢复
- [ ] 更完整的测试覆盖，包括飞书事件和语音转写链路

待实现：

- [ ] 白板/自由画布的真实生成和编辑
- [ ] 离线编辑、冲突检测和冲突合并
- [ ] 更细的角色权限、审批和团队治理
- [ ] Docker/生产部署文档
- [ ] 可观测性：结构化日志、链路追踪、运行指标

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

## License

Internal / Competition use.
