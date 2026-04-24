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
