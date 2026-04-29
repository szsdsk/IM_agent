# 飞书 Bot 配置说明

当前项目的飞书能力走 OpenAPI + Bot 事件回调，不再依赖本机命令行工具作为运行时通道。

## 后端配置

在 `backend/.env` 中配置：

```env
IM_PROVIDER=lark
LARK_BOT_ENABLED=true
LARK_BOT_REQUIRE_MENTION=true
LARK_APP_ID=cli_xxxxxxxxxxxxx
LARK_APP_SECRET=xxxxxxxxxxxxx
LARK_VERIFICATION_TOKEN=xxxxxxxxxxxxx

VOICE_TRANSCRIPTION_ENABLED=true
FEISHU_ASR_ENABLED=true
FEISHU_ASR_FORMAT=pcm
FEISHU_ASR_ENGINE_TYPE=16k_auto

# 卡片按钮回调地址，在飞书开放平台 Bot 配置中填写同一个公网地址。
LARK_CARD_CALLBACK_URL=https://your-public-domain/api/im/lark/card/action
```

## 飞书开放平台

1. 创建企业自建应用。
2. 启用机器人能力。
3. 开通接收消息、发送消息、上传/发送文件、读取消息资源、语音识别、云文档创建与写入相关权限。
4. 订阅 `im.message.receive_v1` 事件。
5. 将事件回调地址配置为：

```text
https://your-public-domain/api/im/lark/events
```

如需使用飞书卡片按钮回调，将卡片交互地址配置为：

```text
https://your-public-domain/api/im/lark/card/action
```

如需在用户编辑飞书云文档后同步本地状态，可额外配置文档变更事件回调：

```text
https://your-public-domain/api/im/lark/doc/events
```

本地开发时，飞书必须能访问你的后端地址，可以使用 ngrok、Cloudflare Tunnel 等工具暴露本地服务。

## 运行流程

1. 用户在飞书群里 @Bot 并发送文本或语音。
2. 飞书把事件推送到 `/api/im/lark/events`。
3. 后端创建或复用会话，并启动 Agent 工作流。
4. Agent 生成文档和 PPT。
5. 后端通过飞书 OpenAPI 把进度、交付卡片和 PPT 文件发回原聊天。
6. 用户可从交付卡片打开飞书云文档编辑，编辑完成后通过卡片按钮或文档事件回调同步状态。

当前暂未实现加密事件回调，飞书控制台中请先关闭事件加密。
