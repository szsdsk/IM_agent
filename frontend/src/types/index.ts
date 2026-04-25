export type SessionStatus =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'running'
  | 'completed'
  | 'failed'
  | 'error'

export interface Task {
  id: string
  session_id: string
  intent: string
  status: 'pending' | 'running' | 'waiting' | 'completed' | 'failed'
  current_step: string
  progress: number
  result_json: Record<string, any> | null
  created_at: string
  updated_at: string
}

export interface Document {
  id: string
  task_id: string
  content: string
  version: number
  created_at: string
}

export interface Slide {
  id: string
  task_id: string
  slides_json: Record<string, any> | any[] | null
  file_path: string | null
  created_at: string
}

export interface LarkCliStatus {
  // 后端是否允许真实调用飞书 CLI。
  enabled: boolean
  // 当前机器是否能找到 lark-cli 可执行文件。
  available: boolean
  // 当前 lark-cli 是否已经完成登录授权。
  authenticated: boolean
  // 后端实际使用的 CLI 命令或路径。
  bin: string
  // CLI 调用身份，例如 user。
  as_identity: string
  message?: string
  error?: string
}

export interface Health {
  status: string
  timestamp: string
  version: string
  // 飞书状态是附加能力，旧后端不返回时前端也能兼容。
  lark_cli?: LarkCliStatus
}

export interface LarkSyncResponse {
  success: boolean
  // 当前只实现 lark_cli，保留字段方便未来扩展其他同步通道。
  provider: 'lark_cli'
  artifact_id: string
  artifact_type?: string
  // 同步成功后用于在前端打开飞书资源。
  lark_url?: string | null
  lark_token?: string | null
  message?: string | null
  error?: string | null
  details?: Record<string, any> | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  step?: string
}

export interface Session {
  id: string
  user_id: string | null
  status: string
  created_at: string
}

export interface WebSocketMessage {
  type: 'task.progress' | 'task.completed' | 'task.failed' | 'session.sync' | 'agent.message' | 'pong'
  task_id?: string
  session_id?: string
  step?: string
  message?: string
  progress?: number
  status?: string
  data?: Record<string, any>
  result?: Record<string, any>
  error?: string
  timestamp: string
}
