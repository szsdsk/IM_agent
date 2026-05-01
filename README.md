# Agent-Pilot

Agent-Pilot 是一个面向办公协同场景的 IM Agent 原型项目。它以网页对话和飞书 Bot 为入口，把用户的自然语言或语音需求拆解成可执行工作流，并自动完成需求理解、任务规划、文档生成、PPT 生成、飞书交付、反馈修改和状态同步。

当前 `main` 分支已经合入飞书交付闭环、PPT 逐页反馈、多 Agent Plan-and-Execute 工作流、飞书文档回写、语音输入、画布预览和 PWA 基础能力。

## 核心流程

```text
网页 / 飞书 Bot 输入
-> LangGraph Agent 理解需求
-> Planner 生成可执行任务图
-> Doc / Canvas / PPT / Delivery 等工具确定性执行
-> 网页预览下载 / 飞书 Bot 回传卡片和 PPT 文件
-> 用户继续反馈修改或确认交付
```

## 功能概览

| 模块 | 当前能力 |
| --- | --- |
| 多入口交互 | 支持网页文本输入、网页语音转文字、飞书 Bot 文本消息和飞书 Bot 语音消息。 |
| Agent 编排 | 使用 LangGraph 构建工作流，并加入 Plan-and-Execute 多 Agent 任务图，覆盖需求分析、规划、执行、交付和反馈修改。 |
| LLM 接入 | 使用 LangChain `ChatOpenAI`，兼容 OpenAI-style API，可通过 `.env` 切换 `OPENAI_BASE_URL` 和 `LLM_MODEL`。 |
| 工具层 | `DocTool`、`PPTTool`、`CanvasTool`、`IMTool` 使用 LangChain `StructuredTool` 封装，节点内确定性调用，避免模型随意调用工具造成 Demo 不稳定。 |
| 文档生成 | 支持生成本地 Markdown 文档；配置飞书后可创建飞书云文档、写入内容、保存文档链接。 |
| 飞书文档闭环 | 交付卡片可跳转飞书文档；点击“已在飞书中编辑”或接收文档事件后，可拉取远端内容、更新本地版本并记录差异摘要。 |
| PPT 生成 | 生成结构化 DeckSpec，前端可预览，后端导出 `.pptx` 文件，网页和飞书均可下载。 |
| PPT 反馈修改 | 支持“第 3 页再详细一点”这类自然语言反馈，优先做目标页局部修改，重新导出最新版 PPT。 |
| 演练稿与 Q&A | 为 PPT 生成每页演讲提示、预计时长和 Top Q&A，网页展示并通过飞书 Bot 发送摘要。 |
| 飞书交付 | 支持进度消息、交付卡片、确认交付、需要修改、文档编辑完成、PPT 文件上传回传。 |
| 白板 / 画布 | 接入 `CanvasTool` 与 AFFiNE service；未配置 AFFiNE 时使用本地 mock 画布预览，保证本地 Demo 不失败。 |
| 状态同步 | WebSocket 推送任务进度；前端支持本地状态恢复、离线消息暂存和基础 PWA 能力。 |
| 数据存储 | 默认 SQLite，保存会话、消息、任务、文档、PPT、事件和交付归档等数据。 |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | FastAPI、LangChain、LangGraph、SQLAlchemy、aiosqlite、httpx、python-pptx |
| 前端 | React、TypeScript、Vite、Tailwind CSS、Zustand |
| 飞书 Bot | Node.js、`@larksuiteoapi/node-sdk` |
| 数据库 | SQLite，后续可替换为 PostgreSQL |
| 外部集成 | 飞书 OpenAPI、AFFiNE 可选集成、Rocket.Chat 预留集成 |

## 目录结构

```text
IM_agent/
├── backend/
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 后端配置
│   ├── api/                     # REST、WebSocket、飞书事件和卡片回调
│   ├── agent/                   # LangGraph 编排、Plan-and-Execute 执行逻辑
│   ├── database/                # SQLAlchemy 模型和连接
│   ├── services/                # LLM、飞书、PPT 渲染、语音、同步、交付等服务
│   ├── tools/                   # LangChain StructuredTool 工具层
│   └── tests/                   # 后端单元测试
├── frontend/                    # React + Vite 网页工作台
├── feishu-bot/                  # 飞书 Bot 长连接服务
├── docs/                        # 配置说明和 Demo 测试文档
├── temp/                        # 临时材料和需求文档
├── requirements.txt             # 后端 Python 依赖
└── README.md
```

## 快速开始

### 1. 后端

推荐使用 Python 3.11。Windows + Conda 示例：

```powershell
conda activate IM_agent
cd D:\IM_agent
python -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

常用地址：

| 地址 | 说明 |
| --- | --- |
| `http://localhost:8000/api/health` | 后端健康检查 |
| `http://localhost:8000/docs` | FastAPI Swagger |
| `ws://localhost:8000/api/ws/sessions/{session_id}` | 网页端 WebSocket |

### 2. 前端

```powershell
cd D:\IM_agent\frontend
npm install
npm run dev
```

前端默认通过 Vite 代理访问后端 `/api`。页面支持输入需求、选择场景、录音转写、查看 Agent 进度、预览文档、预览画布、预览 PPT 和下载 PPT。

### 3. 飞书 Bot

```powershell
cd D:\IM_agent\feishu-bot
npm install
node index.js
```

飞书 Bot 负责接收飞书消息并转发给后端。Agent 完成后，后端通过飞书 OpenAPI 把进度、交付卡片、PPT 文件、演练摘要和 Q&A 发回原聊天。

详细配置见 [docs/feishu-bot-setup.md](docs/feishu-bot-setup.md)。

## 环境变量

后端环境变量写在 `backend/.env`，可从 `backend/.env.example` 复制。常用配置如下：

| 变量 | 说明 |
| --- | --- |
| `APP_NAME` | 后端应用名称。 |
| `DEBUG` | 是否开启调试模式。 |
| `MOCK_MODE` | 是否使用 Mock 模式；没有真实模型或外部平台配置时可设为 `true`。 |
| `DATABASE_URL` | 数据库地址，默认 SQLite。 |
| `OPENAI_API_KEY` | OpenAI-compatible 模型服务 API Key。 |
| `OPENAI_BASE_URL` | OpenAI-compatible API 地址，例如 SiliconFlow、MiniMax 或 OpenAI。 |
| `LLM_MODEL` | 使用的模型名称。 |
| `VOICE_TRANSCRIPTION_ENABLED` | 是否启用网页语音转写入口。 |
| `FEISHU_ASR_ENABLED` | 是否使用飞书 ASR 做语音识别。 |
| `FEISHU_ASR_FORMAT` | 飞书 ASR 音频格式，当前前端录音默认使用 `pcm`。 |
| `FEISHU_ASR_ENGINE_TYPE` | 飞书 ASR 引擎类型，默认 `16k_auto`。 |
| `IM_PROVIDER` | IM 提供方，飞书 Bot 使用 `lark`。 |
| `LARK_APP_ID` | 飞书开放平台应用 App ID。 |
| `LARK_APP_SECRET` | 飞书开放平台应用 App Secret。 |
| `LARK_BOT_ENABLED` | 是否启用飞书 Bot 后端能力。 |
| `LARK_BOT_REQUIRE_MENTION` | 群聊中是否要求 `@Bot` 才触发任务。 |
| `LARK_VERIFICATION_TOKEN` | 飞书事件订阅校验 Token。 |
| `LARK_DEFAULT_CHAT_ID` | 可选默认群 ID；通常从事件消息中自动获取。 |
| `LARK_DOC_FOLDER_TOKEN` | 可选飞书云文档文件夹 Token；配置后生成文档会尽量落到指定文件夹。 |
| `LARK_CARD_CALLBACK_URL` | 飞书卡片请求地址，例如 `https://your-domain.com/api/im/lark/card/action`。 |
| `AFFINE_URL` | 可选 AFFiNE 服务地址；不配置时使用本地 mock 画布。 |
| `AFFINE_TOKEN` | 可选 AFFiNE API Token。 |
| `HOST` / `PORT` | 后端监听地址和端口。 |

## 飞书开放平台配置

当前项目运行时使用飞书 OpenAPI，不再依赖 `lark-cli`。

需要在飞书开放平台完成：

1. 创建企业自建应用，并启用机器人能力。
2. 开通消息接收、消息发送、读取消息资源、上传/发送文件、云文档创建与写入、语音识别等权限。
3. 订阅 `im.message.receive_v1` 事件。
4. 将事件回调地址配置为 `https://your-domain.com/api/im/lark/events`。
5. 将卡片回调地址配置为 `https://your-domain.com/api/im/lark/card/action`。
6. 如果需要文档编辑状态回写，配置文档事件回调到 `https://your-domain.com/api/im/lark/doc/events`。
7. 本地测试不能直接填 `127.0.0.1` 或 `localhost`，需要使用 ngrok、cpolar、Cloudflare Tunnel 等工具暴露公网 HTTPS 地址。
8. 如需让生成的文档出现在指定云文档文件夹，将文件夹 URL 中 `/drive/folder/` 后面的 token 写入 `LARK_DOC_FOLDER_TOKEN`。

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查。 |
| `POST` | `/api/sessions` | 创建网页端会话。 |
| `GET` | `/api/sessions/{id}` | 查询会话。 |
| `GET` | `/api/sessions/{id}/messages` | 查询会话消息。 |
| `POST` | `/api/sessions/{id}/messages` | 发送需求或反馈，并触发 Agent。 |
| `POST` | `/api/voice/transcriptions` | 网页语音转文字。 |
| `GET` | `/api/tasks/{id}` | 查询任务状态。 |
| `POST` | `/api/tasks/{id}/confirm` | 确认或修改任务。 |
| `GET` | `/api/documents/{id}` | 获取生成文档。 |
| `GET` | `/api/documents/{id}/history` | 获取飞书文档版本事件。 |
| `GET` | `/api/slides/{id}` | 获取 PPT 结构数据。 |
| `GET` | `/api/files/slides/{filename}` | 下载 `.pptx` 文件。 |
| `POST` | `/api/im/lark/events` | 飞书事件订阅回调。 |
| `POST` | `/api/im/lark/card/action` | 飞书卡片按钮回调。 |
| `POST` | `/api/im/lark/doc/events` | 飞书文档事件回调。 |
| `WS` | `/api/ws/sessions/{id}` | 网页实时进度推送。 |

## 测试

后端单元测试：

```powershell
cd D:\IM_agent
D:\anaconda\envs\IM_agent\python.exe -m unittest discover backend\tests
```

前端类型检查：

```powershell
cd D:\IM_agent\frontend
npm.cmd exec tsc -- --noEmit
```

前端构建：

```powershell
cd D:\IM_agent\frontend
npm run build
```

## 当前完成度

根据 `temp/require.pdf` 和当前代码，核心比赛 Demo 链路已经基本打通：

| 需求方向 | 状态 | 当前实现 |
| --- | --- | --- |
| IM Agent 入口 | 已完成 | 网页和飞书 Bot 都可发起任务，支持文本和语音。 |
| 需求理解与任务规划 | 已完成 | LangChain + LangGraph + Plan-and-Execute 多 Agent 工作流。 |
| 文档生成与协同 | 已完成 | 本地文档、飞书文档创建写入、飞书编辑后版本回写和差异记录。 |
| PPT 生成与交付 | 已完成 | 结构化 PPT、网页预览下载、飞书文件回传。 |
| PPT 局部修改 | 已完成 | 支持按页反馈，优先局部修订并重新导出。 |
| 演练稿与 Q&A | 已完成 | 网页展示并可通过飞书发送摘要。 |
| 飞书交付闭环 | 已完成 | 卡片按钮、文件上传、状态替换卡、跨群权限基础校验。 |
| 白板 / 画布 | 部分完成 | CanvasTool 与 mock/AFFiNE 接入已完成，真实协同体验仍需完善。 |
| 多端协同 | 部分完成 | PWA、状态恢复、离线暂存和 WebSocket 已有基础能力，复杂冲突合并未完成。 |
| 权限治理和归档 | 部分完成 | 已有基础归档和聊天来源校验，审计、权限策略仍需增强。 |

## Roadmap / ToDo

已完成：

- [x] 网页端文本输入、语音输入、场景选择、进度展示、文档预览、PPT 预览和下载。
- [x] LangChain + LangGraph Agent 工作流重构。
- [x] Plan-and-Execute 多 Agent 执行计划。
- [x] LangChain `StructuredTool` 工具层。
- [x] 本地 `.pptx` 文件生成和下载接口。
- [x] 飞书 Bot 文本 / 语音消息入口。
- [x] 飞书 ASR 语音转写。
- [x] 飞书 OpenAPI 文本消息、卡片消息、文件上传和文件发送。
- [x] 飞书云文档创建、内容写入、文档链接展示。
- [x] 飞书文档编辑后内容回写、版本更新和差异摘要。
- [x] 飞书交付卡片确认 / 修改 / 编辑完成按钮稳定响应，并替换为只读状态卡。
- [x] PPT 逐页反馈修改、演练稿和 Q&A。
- [x] CanvasTool、AFFiNE/mock 画布结果和网页画布预览。
- [x] 响应式 PWA 壳、本地状态恢复和离线消息暂存。
- [x] README、`.env.example` 和飞书配置文档。

待实现：

- [ ] AFFiNE 真实协同编辑体验、画布高级布局和导出。
- [ ] 更完整的多端协同：跨端编辑一致性、复杂离线编辑和冲突合并。
- [ ] 更细粒度的权限、审计、归档中心和交付记录检索。
- [ ] 更稳定的部署脚本、演示脚本和端到端自动化测试。
- [ ] 更丰富的 PPT 版式、主题模板、图表和视觉设计能力。

## License

Internal / Competition use.
