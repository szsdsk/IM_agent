require("dotenv").config();

const fs = require("fs");
const path = require("path");
const lark = require("@larksuiteoapi/node-sdk");

const appId = process.env.LARK_APP_ID;
const appSecret = process.env.LARK_APP_SECRET;
const backendUrl = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const logFile = path.join(__dirname, "bot.log");
const handledMessages = new Set();

function log(message, data) {
  const line = `${new Date().toISOString()} ${message}${data ? ` ${JSON.stringify(data)}` : ""}`;
  console.log(line);
  fs.appendFileSync(logFile, `${line}\n`, "utf8");
}

process.on("unhandledRejection", (error) => {
  log("Unhandled rejection", {
    message: error && error.message,
    stack: error && error.stack,
  });
});

process.on("uncaughtException", (error) => {
  log("Uncaught exception", {
    message: error && error.message,
    stack: error && error.stack,
  });
});

const sdkLogger = {
  debug: (...args) => log("SDK debug", { args }),
  info: (...args) => log("SDK info", { args }),
  warn: (...args) => log("SDK warn", { args }),
  error: (...args) => log("SDK error", { args }),
};

const client = new lark.Client({
  appId,
  appSecret,
  logger: sdkLogger,
  loggerLevel: lark.LoggerLevel.debug,
});

const wsClient = new lark.WSClient({
  appId,
  appSecret,
  logger: sdkLogger,
  loggerLevel: lark.LoggerLevel.debug,
  onReady: () => log("Feishu WS ready"),
  onError: (error) => log("Feishu WS error", {
    message: error && error.message,
    stack: error && error.stack,
  }),
  onReconnecting: () => log("Feishu WS reconnecting"),
  onReconnected: () => log("Feishu WS reconnected"),
});

async function checkCredentials() {
  if (!appId || !appSecret) {
    log("Missing LARK_APP_ID or LARK_APP_SECRET");
    return;
  }

  const response = await fetch("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  const data = await response.json();
  log("Feishu credential check", {
    ok: response.ok,
    code: data.code,
    msg: data.msg,
    hasToken: Boolean(data.tenant_access_token),
  });
}

function getSenderId(sender) {
  const id = sender && sender.sender_id ? sender.sender_id : {};
  return id.open_id || id.user_id || id.union_id || null;
}

function getText(message) {
  if (!message || message.message_type !== "text") {
    return "";
  }

  try {
    const content = JSON.parse(message.content || "{}");
    return String(content.text || "").trim();
  } catch (error) {
    return String(message.content || "").trim();
  }
}

function stripMentions(text, mentions) {
  let cleaned = text;
  for (const mention of mentions || []) {
    if (mention.name) {
      cleaned = cleaned.replaceAll(`@${mention.name}`, "");
    }
    if (mention.key) {
      cleaned = cleaned.replaceAll(mention.key, "");
    }
  }
  return cleaned.replace(/@\S+/g, "").trim();
}

async function reply(messageId, text) {
  await client.im.message.reply({
    path: { message_id: messageId },
    data: {
      msg_type: "text",
      content: JSON.stringify({ text }),
    },
  });
}

async function safeReply(messageId, text) {
  try {
    await reply(messageId, text);
  } catch (error) {
    log("Feishu reply skipped", {
      message: error && error.message,
      code: error && error.response && error.response.data && error.response.data.code,
      msg: error && error.response && error.response.data && error.response.data.msg,
    });
  }
}

async function postJson(apiPath, body) {
  const response = await fetch(`${backendUrl}${apiPath}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Backend ${response.status}: ${text.slice(0, 500)}`);
  }

  return response.json();
}

async function submitToAgentPilot(event) {
  const message = event.message;
  const messageId = message.message_id;
  const senderId = getSenderId(event.sender);
  const rawText = getText(message);
  const text = stripMentions(rawText, message.mentions);

  if (!text) {
    await safeReply(messageId, "我收到了消息，但目前只处理文本需求。");
    return;
  }

  log("收到飞书消息", {
    messageId,
    chatId: message.chat_id,
    chatType: message.chat_type,
    senderId,
    text,
  });

  await safeReply(messageId, `已接收需求，Agent-Pilot 开始处理：${text}`);

  const session = await postJson("/api/sessions", {
    user_id: senderId,
  });

  const task = await postJson(`/api/sessions/${session.id}/messages`, {
    content: text,
    user_id: senderId,
    room_id: message.chat_id,
  });

  log("Agent-Pilot 任务已完成", {
    sessionId: session.id,
    taskId: task.id,
    status: task.status,
  });
}

async function main() {
  log("Feishu Bot long connection is starting");
  log("Agent-Pilot backend", { backendUrl });
  await checkCredentials();

  await wsClient.start({
    eventDispatcher: new lark.EventDispatcher({}).register({
      "im.message.receive_v1": async (data) => {
        log("Feishu event received", {
          type: data && data.header && data.header.event_type,
          eventId: data && data.header && data.header.event_id,
          keys: data && typeof data === "object" ? Object.keys(data) : [],
          eventKeys: data && data.event && typeof data.event === "object" ? Object.keys(data.event) : [],
        });

        const event = data.event || data || {};
        const message = event.message || {};
        const messageId = message.message_id;

        if (!messageId || handledMessages.has(messageId)) {
          return;
        }

        handledMessages.add(messageId);
        if (handledMessages.size > 1000) {
          handledMessages.clear();
        }

        try {
          await submitToAgentPilot(event);
        } catch (error) {
          log("Failed to submit message to Agent-Pilot", {
            message: error.message,
            stack: error.stack,
          });
          if (messageId) {
            await safeReply(messageId, `Agent-Pilot 处理失败：${error.message}`);
          }
        }
      },
    }),
  });
}

main().catch((error) => {
  log("Feishu Bot startup failed", {
    message: error && error.message,
    stack: error && error.stack,
  });
});
