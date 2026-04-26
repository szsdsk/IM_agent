# Agent-Pilot

Agent-Pilot 是一个面向 IM 办公场景的智能内容生成助手。用户可以通过前端网页或飞书 Bot 输入需求，系统会自动完成需求理解、任务规划、文档生成、PPT 生成和结果交付。

当前版本重点支持：

- 前端三栏工作台：左侧消息输入，中间 Agent 流程，右侧文档/PPT 预览
- 前端文字输入和语音输入
- 飞书 Bot 文本/语音消息接入
- 飞书 ASR 语音转写
- 按演示场景生成不同风格的 PPT 内容
- FastAPI 后端、WebSocket 进度推送、SQLite 本地数据存储

## 功能概览

| 模块 | 能力 |
|---|---|
| 消息输入 | 前端支持文字输入和录音转写，飞书 Bot 支持文本和语音消息 |
| 场景选择 | 管理层汇报、项目评审、方案提案、复盘总结、培训讲解 |
| Agent 流程 | 接收输入、分析需求、规划流程、提取任务、生成文档、生成 PPT、确认/修改、交付结果 |
| 文档生成 | 生成 Markdown 文档内容，可扩展到飞书文档/AFFiNE |
| PPT 生成 | 生成 DeckSpec，并渲染为本地 PPTX |
| 实时状态 | 前端通过 WebSocket 展示 Agent 当前步骤、进度和消息 |
| 飞书集成 | 支持飞书事件回调、Bot 消息、语音资源下载、ASR 转写、文件交付 |

## 前端布局

前端是一个三栏工作台：

| 区域 | 内容 |
|---|---|
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
|---|---|
| 管理层汇报 | 先结论后细节，强调结果、价值、决策点 |
| 项目评审 | 强调方案、计划、风险、依赖 |
| 方案提案 | 强调痛点、机会、价值、收益和落地路径 |
| 复盘总结 | 强调结果回顾、问题分析、经验沉淀、改进动作 |
| 培训讲解 | 结构更细，讲解性更强，适合教学和知识传递 |

## 语音识别

项目当前使用飞书 ASR。

前端录音后会先在浏览器内转换为：

- `16kHz`
- `mono`
- `PCM16`
- 原始 `.pcm` 字节

然后后端调用飞书 `speech_to_text/v1/speech/file_recognize` 接口识别。

后端会确保飞书 ASR 请求满足当前接口要求：

- `format=pcm`
- `file_id` 为合法的 16 位标识
- `engine_type` 默认使用 `FEISHU_ASR_ENGINE_TYPE`

## 快速开始

### 1. 安装后端依赖

```bash
pip install -r backend/requirements.txt
```

如果你使用仓库根目录的聚合依赖，也可以执行：

```bash
pip install -r requirements.txt
```

### 2. 安装前端依赖

```bash
cd frontend
npm install
```

### 3. 配置环境变量

复制示例配置：

```bash
cp backend/.env.example backend/.env
```

Windows PowerShell 可以使用：

```powershell
Copy-Item backend/.env.example backend/.env
```

关键配置：

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

HOST=0.0.0.0
PORT=8000
```

注意：飞书 ASR 当前链路只使用飞书，不再依赖外部 Whisper/ASR 服务。

### 4. 启动后端

在仓库根目录执行：

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

接口文档：

```text
http://localhost:8000/docs
```

### 5. 启动前端

```bash
cd frontend
npm run dev
```

默认访问：

```text
http://localhost:5173
```

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

具体权限名称可能随飞书开放平台版本变化，以控制台实际展示为准。

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/sessions` | 创建前端会话 |
| `POST` | `/api/sessions/{session_id}/messages` | 发送文字需求并触发 Agent |
| `POST` | `/api/voice/transcriptions` | 前端语音转写 |
| `POST` | `/api/im/lark/events` | 飞书事件回调 |
| `POST` | `/api/im/lark/card/action` | 飞书卡片回调 |
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
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── endpoints.py
│   │   └── schemas.py
│   ├── agent/
│   │   ├── orchestrator.py
│   │   ├── nodes.py
│   │   └── state.py
│   ├── database/
│   ├── services/
│   │   ├── llm_service.py
│   │   ├── speech_service.py
│   │   ├── lark_bot_service.py
│   │   ├── deck_spec.py
│   │   └── deck_renderer.py
│   └── tools/
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   ├── services/
│   │   ├── store/
│   │   └── types/
│   └── package.json
├── docs/
├── requirements.txt
└── README.md
```

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

## 当前状态

这是一个可运行的 MVP。核心链路已经打通：

```text
文字/语音输入 -> 场景选择 -> Agent 工作流 -> 文档/PPT 生成 -> 前端预览/飞书交付
```

后续可以继续增强：

- 飞书文档写入
- 更完整的 PPT 模板系统
- 任务历史列表
- 多轮修改体验
- 更细的权限和配置自检
