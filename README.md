# Agent-Pilot

Agent-Pilot 是一个面向办公协同场景的 IM Agent 原型项目。它把 IM 对话中的自然语言需求转换为可执行任务流，自动完成需求理解、流程规划、文档生成、PPT 生成，并通过网页端或飞书 bot 完成交付。

当前版本重点跑通比赛 Demo 的主链路：

```text
飞书/网页输入 -> Agent 理解与规划 -> 生成文档 -> 生成 PPT -> 本地预览下载/飞书 bot 回传
```

> 说明：网页端目前只保留本地预览和下载能力；飞书交付统一走 bot/OpenAPI 流程，不再在网页上提供“同步到飞书”按钮。

## 功能概览

| 模块 | 当前能力 |
| --- | --- |
| IM 入口 | 支持飞书 bot 接收文本消息，也保留网页端输入入口 |
| Agent 流程 | 后端按 receive、parse、plan、extract、doc、slides、confirm、deliver 等节点推进 |
| LLM 接入 | 使用 OpenAI-compatible Chat Completions 接口，可通过 `.env` 切换模型和 base url |
| 文档生成 | 生成结构化 Markdown 文档内容，并写入任务结果 |
| PPT 生成 | 生成 DeckSpec/页面数据，并导出本地 `.pptx` 文件 |
| 网页端 | 支持会话输入、进度查看、文档预览、PPT 预览、本地 PPT 下载 |
| 飞书 bot | 基于飞书 OpenAPI 发送进度消息、完成消息，并把生成的 PPT 文件发回聊天 |
| 数据存储 | 默认使用 SQLite，任务、文档、PPT 等数据落库 |

## 需求完成情况

根据 `temp/require.pdf` 的赛题要求，当前项目状态如下：

| 需求项 | 状态 | 说明 |
| --- | --- | --- |
| IM 作为 Agent 入口 | 已完成 | 已接入飞书 bot 文本消息，网页端也可触发任务 |
| Agent 任务理解与规划 | 已完成 | 后端已有意图解析、流程规划、任务抽取等节点 |
| 文档生成 | 已完成 | 可生成 PRD/说明类 Markdown 文档内容 |
| PPT 生成与导出 | 已完成 | 可生成 PPT 页面数据和本地 `.pptx` 文件 |
| 交付结果 | 部分完成 | 网页端可下载，飞书 bot 可回传文件；完整归档和分享链接仍待完善 |
| 多端实时同步 | 部分完成 | 已有 WebSocket 进度推送；移动端/桌面端双端一致性还未完整实现 |
| 文档/白板编辑 | 部分完成 | 文档生成已完成，真实文档编辑、白板/画布协作仍待接入 |
| PPT 修改和演练 | 部分完成 | 已能生成基础 PPT；基于用户反馈的编辑闭环和演练模式还未完整实现 |
| 自然语言文本/语音指令 | 部分完成 | 文本指令已支持，语音指令未接入 |
| 飞书或类似 OpenAPI 集成 | 部分完成 | bot 消息收发、文件上传/发送已接入；云文档深度协作后续再做 |
| 离线和冲突合并 | 未完成 | 暂未实现离线编辑、CRDT/OT 或冲突解决策略 |

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Backend | FastAPI、SQLAlchemy、aiosqlite、httpx、python-pptx |
| Frontend | React、TypeScript、Vite、Tailwind CSS、Zustand |
| Bot | Node.js、`@larksuiteoapi/node-sdk` |
| Database | SQLite，后续可替换为 PostgreSQL |
| IM Integration | 飞书 OpenAPI，Rocket.Chat 仍保留基础服务封装 |

## 目录结构

```text
IM_agent/
├── backend/
│   ├── main.py                  # FastAPI 应用入口
│   ├── config.py                # 后端配置加载
│   ├── api/                     # REST、WebSocket、飞书事件回调接口
│   ├── agent/                   # Agent 编排和节点逻辑
│   ├── database/                # SQLAlchemy 模型和数据库连接
│   ├── services/                # LLM、飞书 bot、PPT 渲染、交付等服务
│   └── tools/                   # Agent 可调用工具
├── frontend/                    # React + Vite 网页端
├── feishu-bot/                  # 飞书 bot 长连接服务
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

`feishu-bot` 目录下也需要按该目录的示例配置 bot 运行参数，至少要保证 bot 能连接飞书并知道后端地址。

## API 概览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 后端健康检查 |
| `POST` | `/api/sessions` | 创建网页端会话 |
| `GET` | `/api/sessions/{id}` | 查询会话 |
| `GET` | `/api/sessions/{id}/messages` | 查询会话事件消息 |
| `POST` | `/api/sessions/{id}/messages` | 发送需求并触发 Agent 流程 |
| `GET` | `/api/tasks/{id}` | 查询任务状态 |
| `POST` | `/api/tasks/{id}/confirm` | 确认或修改任务 |
| `GET` | `/api/documents/{id}` | 获取生成文档 |
| `GET` | `/api/slides/{id}` | 获取生成 PPT 数据 |
| `GET` | `/api/files/slides/{filename}` | 下载本地 PPT 文件 |
| `POST` | `/api/im/lark/events` | 飞书事件订阅回调 |
| `WS` | `/api/ws/sessions/{id}` | 网页端实时进度推送 |

## Roadmap

已完成：

- [x] 网页端输入、进度展示、文档预览、PPT 预览和下载
- [x] Agent 基础工作流：接收输入、解析需求、规划流程、生成文档、生成 PPT、交付结果
- [x] 后端本地 `.pptx` 文件生成和下载接口
- [x] 飞书 bot 文本消息入口
- [x] 飞书 OpenAPI 文本消息发送、文件上传和文件消息发送
- [x] README 和 `.env.example` 基础文档

进行中：

- [ ] 多端同步从“网页进度推送”升级为移动端/桌面端双端一致性
- [ ] 飞书 bot 与网页端的任务状态统一展示
- [ ] 更稳定的 PPT 内容质量、版式和视觉模板
- [ ] 文档生成后的可编辑协作流程

待实现：

- [ ] 语音指令入口
- [ ] 白板/自由画布生成和编辑
- [ ] PPT 反馈修改、演练稿和 Q&A 训练闭环
- [ ] 离线编辑、冲突检测和冲突合并
- [ ] 权限、审批和团队协作治理
- [ ] 更完整的自动化测试和部署文档

## License

Internal / Competition use.
