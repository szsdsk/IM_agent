# Agent-Pilot

Agent-Pilot 是一个面向办公协同场景的智能 Agent Demo。项目提供内置聊天入口，用户输入需求后，后端 Agent 会完成意图分析、流程规划、文档生成、PPT 生成、预览下载，并可选将交付物同步到飞书云空间。

当前项目重点服务比赛/演示闭环：先保证本地生成、预览、下载稳定，再通过 `lark-cli` 扩展飞书同步能力。

## Features

- 内置 Web 聊天界面，支持通过自然语言提交办公任务。
- 后端基于 FastAPI 提供任务、文档、PPT、下载与飞书同步接口。
- Agent 流程包含输入接收、需求分析、流程规划、任务提取、文档生成、PPT 生成和交付。
- PPT 会落盘为 `.pptx`，前端支持预览和下载。
- 飞书集成基于官方 `@larksuite/cli`，支持将文档或 PPT 同步到飞书。
- 默认本地 Demo 不依赖飞书授权；开启 `LARK_CLI_ENABLED=true` 后才走真实飞书同步。

## Tech Stack

- Backend: Python 3.11, FastAPI, SQLAlchemy, SQLite, LangGraph, python-pptx
- Frontend: React 18, TypeScript, Vite, Tailwind CSS, Zustand
- LLM Provider: OpenAI-compatible Chat Completions API
- Lark Integration: `@larksuite/cli`

## Project Structure

```text
.
|-- backend/                 # FastAPI 后端、Agent 编排、工具层和数据库模型
|   |-- agent/               # Agent 状态流转与节点逻辑
|   |-- api/                 # HTTP / WebSocket 接口
|   |-- database/            # SQLAlchemy 连接与模型
|   |-- .env.example         # 后端环境变量模板
|   |-- services/            # LLM、PPT 渲染、交付等服务
|   |-- tools/               # Doc / PPT / Lark 等工具封装
|   `-- tests/               # 后端单测
|-- frontend/                # React 前端
|   `-- src/
|-- docs/                    # 额外配置文档
|-- temp/                    # 临时文档和本地开发产物，默认不提交
`-- requirements.txt         # 后端依赖入口
```

## Prerequisites

- Python 3.11
- Node.js 18+
- npm
- Conda 可选，但推荐用独立环境运行后端
- 可用的 OpenAI-compatible LLM API Key
- 可选：飞书 CLI，用于同步到飞书

## Quick Start

### 1. Clone and enter project

```powershell
cd D:\IM_agent
```

### 2. Configure environment variables

复制环境变量模板：

```powershell
Copy-Item backend\.env.example backend\.env
```

然后编辑 `backend\.env`，至少配置：

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

如果暂时不测试飞书，同步配置保持关闭即可：

```env
LARK_CLI_ENABLED=false
```

完整配置说明见 [backend/.env.example](./backend/.env.example)。

### 3. Install backend dependencies

推荐使用 Conda 环境，例如：

```powershell
conda create -n IM_agent python=3.11
conda activate IM_agent
python -m pip install -r backend\requirements.txt
```

如果你已经有可用的 `IM_agent` 环境，只需要激活后安装依赖即可。

### 4. Run backend

请在项目根目录启动后端，不要进入 `backend` 子目录启动：

```powershell
cd D:\IM_agent
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：

```text
http://localhost:8000/api/health
```

### 5. Install frontend dependencies

```powershell
cd D:\IM_agent\frontend
npm install
```

### 6. Run frontend

```powershell
cd D:\IM_agent\frontend
npm run dev -- --host 0.0.0.0 --port 3000
```

打开：

```text
http://localhost:3000
```

## Environment Variables

本项目使用 Pydantic Settings 读取环境变量。后端会从以下位置读取：

- `.env`
- `backend/.env`

建议本地开发使用 `backend/.env`，并从 [backend/.env.example](./backend/.env.example) 复制。

核心配置包括：

- `OPENAI_API_KEY`: LLM API Key。
- `OPENAI_BASE_URL`: OpenAI-compatible API 地址。
- `LLM_MODEL`: 模型名称。
- `DATABASE_URL`: SQLite 数据库地址，默认即可。
- `LARK_CLI_ENABLED`: 是否启用真实飞书同步。
- `LARK_CLI_BIN`: `lark-cli` 可执行文件路径。
- `LARK_CLI_AS`: CLI 调用身份，默认 `user`。
- `LARK_DEFAULT_CHAT_ID`: 可选，配置后可用于飞书群消息通知。

飞书 CLI 配置比较容易踩坑，单独见 [docs/lark-cli-setup.md](./docs/lark-cli-setup.md)。

## Lark / Feishu Sync

飞书集成采用官方 `@larksuite/cli`，不直接在代码里维护 OpenAPI token。当前同步策略是：

- 本地文档和 PPT 先生成成功。
- 点击“同步到飞书”后，后端调用 `lark-cli` 上传交付物。
- 飞书同步失败不会影响本地预览和下载。
- 前端默认只同步文件，不自动发送群消息；需要消息通知时可配置 `LARK_DEFAULT_CHAT_ID` 并在接口请求里开启 `notify`。

快速配置入口：

```powershell
npm install -g @larksuite/cli
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth login --scope "drive:file:upload"
lark-cli auth status
```

Windows 上如果后端找不到 `lark-cli`，建议在 `.env` 里显式指定：

```env
LARK_CLI_BIN=C:\Users\<your-user>\AppData\Roaming\npm\lark-cli.cmd
```

更多步骤和排错见 [docs/lark-cli-setup.md](./docs/lark-cli-setup.md)。

## Useful Commands

后端单测：

```powershell
python -m unittest backend.tests.test_lark_tool
```

前端构建：

```powershell
cd frontend
npm run build
```

查看当前分支改动：

```powershell
git status --short --branch
```

## API Overview

常用接口：

- `GET /api/health`: 后端健康检查，并返回飞书 CLI 可用状态。
- `POST /api/sessions`: 创建会话。
- `POST /api/sessions/{session_id}/messages`: 发送用户需求并启动 Agent 任务。
- `GET /api/tasks/{task_id}`: 查询任务状态。
- `GET /api/documents/{document_id}`: 查询生成文档。
- `GET /api/slides/{slide_id}`: 查询生成 PPT 数据。
- `GET /api/files/slides/{filename}`: 下载本地生成的 PPTX。
- `POST /api/artifacts/{artifact_id}/sync/lark`: 将文档或 PPT 同步到飞书。

## Troubleshooting

### Backend import error

如果出现：

```text
Error loading ASGI app. Could not import module "backend.main".
```

通常是启动目录不对。请回到项目根目录运行：

```powershell
cd D:\IM_agent
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend proxy ECONNREFUSED

如果 Vite 显示 `/api/health ECONNREFUSED`，说明后端没有成功运行在 `localhost:8000`。先检查后端窗口是否启动成功，再刷新前端页面。

### LLM returns 400

检查 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 和 `LLM_MODEL` 是否匹配同一个服务商。比如 SiliconFlow 不能直接使用 OpenAI 的 `gpt-4` 模型名。

### PPT generated but not visible

确认任务结果里存在 `slides.file_path`，并且后端 `/api/files/slides/{filename}` 能下载对应文件。当前前端预览和下载都依赖后端返回的本地 PPT 文件路径。

## Security Notes

- 不要提交 `.env`、API Key、App Secret、飞书 token 或本机 CLI 配置。
- `backend/.env.example` 只放占位值，并保持与 `backend/.env` 相同的配置项。
- `temp/`、`data/`、`dist/`、`node_modules/` 默认不提交。

## License

当前仓库尚未声明开源许可证。若计划公开发布，请先补充 LICENSE 文件。
