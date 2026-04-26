# Lark / Feishu CLI Setup

Agent-Pilot 使用官方 `@larksuite/cli` 与飞书交互。后端不会保存飞书 access token，也不会直接手写 OpenAPI 调用；真实同步发生时，后端通过子进程调用本机 `lark-cli`。

当前主要能力：

- 上传本地生成的 PPTX 到飞书云空间。
- 创建飞书文档。
- 可选发送飞书群消息。
- 在 `/api/health` 返回 CLI 是否可用、是否已登录。

## 1. Install CLI

```powershell
npm install -g @larksuite/cli
```

检查是否安装成功：

```powershell
lark-cli --version
lark-cli --help
```

Windows 上如果提示找不到 `lark-cli`，先确认 npm 全局目录：

```powershell
npm config get prefix
```

常见全局命令目录是：

```text
C:\Users\<your-user>\AppData\Roaming\npm
```

如果目录不存在，可以创建并配置 npm prefix：

```powershell
$npmGlobal = "$env:APPDATA\npm"
New-Item -ItemType Directory -Force $npmGlobal | Out-Null
npm config set prefix $npmGlobal
```

然后把该目录加入用户 PATH，并重新打开 PowerShell。

## 2. Initialize CLI App

首次使用需要初始化 CLI 配置：

```powershell
lark-cli config init --new
```

按终端提示打开浏览器并完成配置。完成后检查：

```powershell
lark-cli config show
```

如果后续授权时报：

```text
device authorization failed: The request is missing a required parameter: client_secret.
```

说明当前 CLI 配置拿不到 App Secret。推荐重新初始化：

```powershell
lark-cli config init --new
```

如果你已经有 App ID 和 App Secret，也可以手动写入配置。不要把 Secret 发给别人，也不要提交到 Git：

```powershell
$secret = Read-Host "Paste App Secret"
$secret | lark-cli config init --app-id "your_app_id" --app-secret-stdin --brand feishu
Remove-Variable secret
```

## 3. Login and Grant Scopes

推荐先使用官方推荐权限登录：

```powershell
lark-cli auth login --recommend
```

上传 PPT 到云空间至少需要 Drive 上传权限：

```powershell
lark-cli auth login --scope "drive:file:upload"
```

如果仍然遇到授权问题，可以授权整个 Drive 域：

```powershell
lark-cli auth login --domain drive
```

检查登录状态：

```powershell
lark-cli auth status
```

确认输出中包含：

```text
tokenStatus: valid
scope: ... drive:file:upload ...
```

## 4. Configure Agent-Pilot

复制模板：

```powershell
Copy-Item backend\.env.example backend\.env
```

编辑 `backend\.env`：

```env
LARK_CLI_ENABLED=true
LARK_CLI_AS=user
LARK_CLI_TIMEOUT_SECONDS=30
```

如果后端健康检查显示找不到 `lark-cli`，请显式指定 npm 生成的 `.cmd` 文件：

```env
LARK_CLI_BIN=C:\Users\<your-user>\AppData\Roaming\npm\lark-cli.cmd
```

然后重启后端：

```powershell
cd D:\IM_agent
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

访问健康检查：

```text
http://localhost:8000/api/health
```

期望看到：

```json
{
  "status": "healthy",
  "lark_cli": {
    "enabled": true,
    "available": true,
    "authenticated": true
  }
}
```

## 5. Sync PPT to Feishu

启动前后端后，在前端生成 PPT，点击“同步到飞书”。

当前前端默认只上传文件，不发送群消息：

```json
{ "notify": false }
```

因此不配置 `LARK_DEFAULT_CHAT_ID` 也不会影响上传。

如果你后续希望同步成功后发送飞书群消息，需要：

1. 获取飞书群 `chat_id`。
2. 在 `backend\.env` 中配置：

```env
LARK_DEFAULT_CHAT_ID=oc_xxxxxxxxx
```

3. 调用同步接口时传入 `notify: true`。

## Troubleshooting

### Backend says CLI binary not found

检查 PowerShell 是否能找到 CLI：

```powershell
Get-Command lark-cli
```

如果 PowerShell 找得到但后端找不到，优先在 `.env` 写完整路径：

```env
LARK_CLI_BIN=C:\Users\<your-user>\AppData\Roaming\npm\lark-cli.cmd
```

重启后端后再访问 `/api/health`。

### `unknown flag: --format`

当前 CLI 部分命令默认输出 JSON，但不支持 `--format`。项目代码已经不再追加该参数。如果仍看到这个错误，确认后端代码是最新版本并重启后端。

### `unknown flag: --file`

说明本机 `@larksuite/cli` 版本过旧或命令语法不一致。先查看帮助：

```powershell
lark-cli drive +upload --help
```

如果帮助里没有 `--file`，升级 CLI：

```powershell
npm install -g @larksuite/cli@latest
```

### `unsafe file path`

`lark-cli drive +upload --file` 要求传入当前目录内的相对路径。项目代码已经在上传时切换到文件所在目录，并传入 `./filename.pptx`。如果仍出现该错误，请确认后端代码已更新并重启。

### `need_user_authorization`

这表示当前用户 token 对 Drive 上传权限不足。重新授权：

```powershell
lark-cli auth login --scope "drive:file:upload"
lark-cli auth status
```

如果仍失败：

```powershell
lark-cli auth login --domain drive
```

### Uploaded file has no extension

项目上传时会自动保留原始文件后缀，例如 `.pptx`。如果云空间旧文件没有后缀，请删除旧文件后重新同步，或在飞书里手动重命名。

### Message send failed

上传文件和发送群消息是两步。文件同步成功后，如果没有配置群 ID，消息发送会失败。配置：

```env
LARK_DEFAULT_CHAT_ID=oc_xxxxxxxxx
```

如果只是演示上传，保持前端默认 `notify: false` 即可。

## Security Notes

- 不要提交 `.env`。
- 不要把 App Secret、API Key、token 发到聊天或日志里。
- `lark-cli` 的本机配置通常位于用户目录，不应放入仓库。
- 如果换机器部署，需要在目标机器重新安装、初始化并登录 `lark-cli`。
