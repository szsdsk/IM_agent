# Agent-Pilot

Agent-Pilot 是一个面向办公协同场景的 IM Agent 原型项目。它以 IM 对话为入口，把用户的自然语言需求拆解成可执行工作流，自动完成需求理解、任务规划、文档生成、PPT 生成、飞书交付与状态同步。

当前版本重点跑通比赛 Demo 主链路：

```text
网页/飞书输入（文本或语音）
-> LangGraph Agent 理解与规划
-> 生成结构化文档
-> 生成 PPT
-> 网页预览下载 / 飞书 Bot 回传交付
-> 飞书文档编辑后状态回写
```

## 功能概览

| 模块 | 当前能力 |
| --- | --- |
| IM 入口 | 支持网页端文本/语音输入，也支持飞书 Bot 接收文本/语音消息 |
| Agent 编排 | 使用 LangGraph 构建工作流节点，覆盖接收输入、意图解析、流程规划、任务抽取、文档生成、PPT 生成、确认交付 |
| LLM 接入 | 使用 LangChain `ChatOpenAI`，兼容 OpenAI-style API，可通过 `.env` 切换模型和 `base_url` |
| 工具层 | DocTool、PPTTool、IMTool 已改造为 LangChain `StructuredTool` 调用形态 |
| 文档生成 | 生成 Markdown 结构化文档；配置飞书后可创建飞书云文档并写入内容 |
| 文档编辑回写 | 飞书交付卡片可打开云文档编辑，编辑完成后通过卡片按钮或文档事件回调同步本地状态、远端内容和版本差异 |
| PPT 生成与修改 | 生成 DeckSpec/页面数据，支持多主题、多布局和演示场景适配；可按“第 N 页...”进行局部反馈修改并重新导出 `.pptx` |
| 演练与 Q&A | 生成每页演讲提示、预计时长和可能 Q&A，网页端展示并通过飞书 Bot 发送摘要 |
| 白板/画布 | 接入 CanvasTool + AFFiNE service；未配置 AFFiNE 时使用本地 mock 画布预览 |
| 语音识别 | 前端录音转 PCM16k，后端调用飞书 ASR；飞书 Bot 语音消息也可转写后触发 Agent |
| 飞书交付 | 基于飞书 OpenAPI 发送进度卡片、交付卡片、文本消息和 PPT 文件；交付卡片点击确认、修改或编辑完成后会替换为只读状态卡，避免重复误操作 |
| 网页工作台 | 响应式工作台：输入与场景选择、流程进度、文档/PPT/画布预览 |
| 状态同步 | WebSocket 推送任务进度，SyncService 提供内存/Redis 两种同步通道；前端支持本地状态恢复和离线消息暂存 |
| 数据存储 | 默认 SQLite，任务、文档、PPT 等结果落库 |

## 需求完成情况

根据 `temp/require.pdf` 的赛题要求，当前 main 分支的完成度如下：

| 赛题要求 | 状态 | 当前实现 |
| --- | --- | --- |
| IM 作为 Agent 入口，支持文本/语音 | 已完成 | 网页端和飞书 Bot 均可发起任务；飞书 Bot 支持文本和语音消息 |
| Agent 任务理解与规划 | 已完成 | LangGraph 工作流 + LangChain 模型层，支持意图解析、流程规划和任务抽取 |
| 文档生成与编辑 | 已完成 | 可生成本地文档预览；配置飞书后可创建云文档、写入内容、落到指定文件夹，并支持编辑内容回写和版本差异 |
| PPT/演示稿生成与导出 | 已完成 | 可生成 PPT 结构、前端预览并下载 `.pptx`；飞书 Bot 可回传 PPT 文件 |
| PPT 演练与修改闭环 | 已完成 | 支持页码自然语言反馈、局部更新、重新导出 PPT、演练稿和 Q&A 展示 |
| 总结与交付 | 已完成 | 网页端下载交付，飞书端通过交付卡片和文件消息完成交付 |
| 自然语言交互 | 已完成 | 支持文本指令和语音转写后的自然语言指令 |
| 飞书或类似 OpenAPI 集成 | 已完成 | 已接入飞书消息、卡片、文件、云文档、语音识别等 OpenAPI |
| 模块化场景编排 | 部分完成 | 已有文档/PPT/交付等确定性节点和 5 类演示场景；更开放的动态编排还可继续增强 |
| 多端协同与一致性 | 部分完成 | 网页端响应式/PWA、本地状态恢复、离线消息暂存、WebSocket 和飞书 Bot 已具备；复杂离线编辑和冲突合并仍需增强 |
| 白板/自由画布 | 部分完成 | 已接入 CanvasTool 和 AFFiNE/mock 画布结果；真实 AFFiNE 协同编辑和高级布局仍需完善 |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Backend | FastAPI、LangChain、LangGraph、SQLAlchemy、aiosqlite、httpx、python-pptx |
| Frontend | React、TypeScript、Vite、Tailwind CSS、Zustand |
| Bot | Node.js、`@larksuiteoapi/node-sdk` |
| Database | SQLite，后续可替换为 PostgreSQL |
| IM Integration | 飞书 OpenAPI |

## 目录结构

```text
IM_agent/
├── backend/
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 后端配置加载
│   ├── api/                     # REST、WebSocket、飞书事件和卡片回调
│   ├── agent/                   # LangGraph 编排和节点逻辑
│   ├── database/                # SQLAlchemy 模型和数据库连接
│   ├── services/                # LLM、飞书、PPT 渲染、语音转写、状态同步等服务
│   └── tools/                   # LangChain StructuredTool 工具层
├── frontend/                    # React + Vite 网页端
├── feishu-bot/                  # 飞书 Bot 长连接服务
├── docs/                        # 配置与使用文档
├── temp/                        # 本地临时材料和需求文档
├── requirements.txt             # 后端 Python 依赖
└── README.md
```

## 快速开始

### 1. 后端

项目推荐 Python 3.11。Windows + Conda 示例：

```powershell
conda activate IM_agent
cd D:\IM_agent
python -m pip install -r requirements.txt
```

复制环境变量示例并填写：

```powershell
Copy-Item backend\.env.example backend\.env
```

启动后端：

```powershell
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

常用地址：

| 地址 | 说明 |
| --- | --- |
| `http://localhost:8000/api/health` | 健康检查 |
| `http://localhost:8000/docs` | FastAPI Swagger |
| `ws://localhost:8000/api/ws/sessions/{session_id}` | 会话 WebSocket |

### 2. 前端

```powershell
cd D:\IM_agent\frontend
npm install
npm run dev
```

Vite 会把 `/api` 代理到后端。页面打开后，可以输入需求、选择演示场景、录音转写，并查看文档预览、PPT 预览和下载结果。

### 3. 飞书 Bot

```powershell
cd D:\IM_agent\feishu-bot
npm install
node index.js
```

飞书 Bot 用于接收飞书消息并转发给后端。Agent 执行完成后，后端会通过飞书 OpenAPI 把进度卡片、交付卡片和 PPT 文件发回原聊天。

更完整的飞书配置见 [docs/feishu-bot-setup.md](docs/feishu-bot-setup.md)。

## 环境变量

后端环境变量写在 `backend/.env`，可从 `backend/.env.example` 复制。常用配置如下：

| 变量 | 说明 |
| --- | --- |
| `MOCK_MODE` | 是否使用 Mock 模式；本地无真实模型时可设为 `true` |
| `DATABASE_URL` | 数据库地址，默认 SQLite |
| `OPENAI_API_KEY` | LLM API Key |
| `OPENAI_BASE_URL` | OpenAI-compatible API 地址 |
| `LLM_MODEL` | 使用的模型名称 |
| `VOICE_TRANSCRIPTION_ENABLED` | 是否启用语音转写 |
| `FEISHU_ASR_ENABLED` | 是否启用飞书 ASR |
| `FEISHU_ASR_FORMAT` | 飞书 ASR 音频格式，前端录音默认使用 `pcm` |
| `FEISHU_ASR_ENGINE_TYPE` | 飞书 ASR 引擎类型，默认 `16k_auto` |
| `IM_PROVIDER` | 当前 IM 提供方，飞书 Bot 使用 `lark` |
| `LARK_APP_ID` | 飞书开放平台应用 App ID |
| `LARK_APP_SECRET` | 飞书开放平台应用 App Secret |
| `LARK_BOT_ENABLED` | 是否启用飞书 Bot 后端能力 |
| `LARK_BOT_REQUIRE_MENTION` | 群聊中是否要求 @Bot 才处理消息 |
| `LARK_VERIFICATION_TOKEN` | 飞书事件订阅校验 token |
| `LARK_DEFAULT_CHAT_ID` | 可选默认群 ID |
| `LARK_DOC_FOLDER_TOKEN` | 可选飞书云文档目标文件夹 token；不配置时文档可能只在应用默认位置可访问 |
| `LARK_CARD_CALLBACK_URL` | 飞书卡片请求地址 |
| `AFFINE_URL` | 可选 AFFiNE 服务地址，不配置时使用本地 mock 画布 |
| `AFFINE_TOKEN` | 可选 AFFiNE API Token |

## 飞书开放平台配置

当前项目使用飞书 OpenAPI，不依赖 `lark-cli` 作为运行时通道。

需要在飞书开放平台中完成：

- 创建企业自建应用并启用机器人能力。
- 开通消息接收、消息发送、读取消息资源、上传/发送文件、云文档创建与写入、语音识别等权限。
- 订阅 `im.message.receive_v1` 事件。
- 将事件订阅地址配置为 `https://your-domain.com/api/im/lark/events`。
- 将卡片回调地址配置为 `https://your-domain.com/api/im/lark/card/action`。
- 如果要接收云文档编辑事件，可配置文档事件回调到 `https://your-domain.com/api/im/lark/doc/events`。
- 本地测试不能直接使用 `127.0.0.1` 作为飞书回调地址，需要用 ngrok、cpolar、Cloudflare Tunnel 等工具暴露公网 HTTPS 地址。
- 如需让生成的云文档出现在指定文件夹，请把飞书文件夹 URL 中 `/drive/folder/` 后面的 token 配置到 `LARK_DOC_FOLDER_TOKEN`。

本地开发时，飞书必须能访问后端公网地址，可以使用 ngrok、Cloudflare Tunnel 等工具暴露本地服务。

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 后端健康检查 |
| `POST` | `/api/sessions` | 创建网页端会话 |
| `GET` | `/api/sessions/{id}` | 查询会话 |
| `GET` | `/api/sessions/{id}/messages` | 查询会话消息 |
| `POST` | `/api/sessions/{id}/messages` | 发送需求并触发 Agent |
| `POST` | `/api/voice/transcriptions` | 前端语音转写 |
| `GET` | `/api/tasks/{id}` | 查询任务状态 |
| `POST` | `/api/tasks/{id}/confirm` | 确认或修改任务 |
| `GET` | `/api/documents/{id}` | 获取生成文档 |
| `GET` | `/api/documents/{id}/history` | 获取飞书文档编辑版本历史 |
| `GET` | `/api/slides/{id}` | 获取生成 PPT 数据 |
| `GET` | `/api/files/slides/{filename}` | 下载本地 PPT 文件 |
| `POST` | `/api/im/lark/events` | 飞书事件订阅回调 |
| `POST` | `/api/im/lark/card/action` | 飞书卡片交互回调 |
| `POST` | `/api/im/lark/doc/events` | 飞书文档变更回调 |
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

先确认后端正在运行，再检查前端代理是否能访问：

```text
/api/ws/sessions/{session_id}
```

如果后端重启过，刷新前端页面通常会重新创建 session 并连接 WebSocket。

## Roadmap / ToDo

已完成：

- [x] 网页端文本输入、语音输入、场景选择、进度展示、文档预览、PPT 预览和下载
- [x] LangChain + LangGraph Agent 工作流重构
- [x] LangChain StructuredTool 工具层改造
- [x] 本地 `.pptx` 文件生成和下载接口
- [x] PPT 主题模板系统和场景化生成
- [x] 飞书 Bot 文本/语音消息入口
- [x] 飞书 ASR 语音转写
- [x] 飞书 OpenAPI 文本消息、卡片消息、文件上传和文件发送
- [x] 飞书云文档创建、指定文件夹落盘、内容写入和网页端编辑跳转
- [x] 飞书文档编辑后远端内容回写、版本更新和差异摘要展示
- [x] 飞书交付卡片确认/修改/编辑完成入口稳定响应，并在点击后替换为只读状态卡
- [x] WebSocket 任务进度推送和 SyncService 基础同步能力
- [x] PPT 逐页反馈修改、演练稿和 Q&A 训练材料
- [x] AFFiNE CanvasTool 和网页端画布预览
- [x] 响应式 PWA 壳、本地状态恢复和离线消息暂存
- [x] 基础归档记录和飞书跨群修改保护
- [x] README、`.env.example` 和飞书配置文档

待实现：

- [ ] AFFiNE 真实协同编辑体验、画布高级布局和导出
- [ ] 更完整的多端协同：跨端编辑一致性、复杂离线编辑和冲突合并
- [ ] 权限、审批、团队协作治理和交付归档策略
- [ ] 更完整的自动化测试、部署文档和演示脚本

## License

Internal / Competition use.
