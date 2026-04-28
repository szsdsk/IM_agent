# Feishu Bot Setup

This project now uses Feishu as the default IM provider.

## Backend configuration

Set these values in `backend/.env`:

```env
IM_PROVIDER=lark
LARK_BOT_ENABLED=true
LARK_BOT_REQUIRE_MENTION=true
LARK_APP_ID=cli_xxxxxxxxxxxxx
LARK_APP_SECRET=xxxxxxxxxxxxx
LARK_VERIFICATION_TOKEN=xxxxxxxxxxxxx
```

Keep `LARK_CLI_ENABLED=true` only if you also want the existing document/file sync flow that calls `lark-cli`.

## Feishu Open Platform

1. Create an internal app in Feishu Open Platform.
2. Enable the bot capability.
3. Add permissions for receiving and sending IM messages.
4. Subscribe to the `im.message.receive_v1` event.
5. Use HTTP event callback mode and set the request URL to:

```text
https://your-public-domain/api/im/lark/events
```

For local development, expose the backend with a tunnel such as ngrok or Cloudflare Tunnel, because Feishu must be able to reach the callback URL.

## Runtime flow

1. A user mentions the bot in a Feishu group.
2. Feishu posts the event to `/api/im/lark/events`.
3. The backend creates a session and task.
4. Agent-Pilot runs the existing workflow.
5. Progress and final delivery are sent back to the same Feishu chat.

Encrypted event callbacks are not implemented in this project yet. Leave event encryption disabled in the Feishu console for now.
