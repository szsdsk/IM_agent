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
  doc_url?: string | null
  lark_doc_id?: string | null
  last_edited_by?: string | null
  last_edited_at?: string | null
}

export interface Slide {
  id: string
  task_id: string
  slides_json: SlideDeckPayload | any[] | null
  file_path: string | null
  created_at: string
}

export interface SlideDeckPayload {
  title?: string
  slides?: Record<string, any>[]
  metadata?: Record<string, any>
  rehearsal?: RehearsalPlan | null
  qa?: QAItem[]
  feedback_history?: FeedbackHistoryItem[]
}

export interface RehearsalPlan {
  slides?: RehearsalSlide[]
  total_duration_minutes?: number
  tips?: string[]
}

export interface RehearsalSlide {
  slide_index: number
  speaker_notes: string
  duration_seconds?: number
  qa_questions?: string[]
}

export interface QAItem {
  slide_index?: number | null
  question: string
  answer: string
}

export interface FeedbackHistoryItem {
  feedback: string
  target_slide_indexes?: number[]
  target_slide_numbers?: number[]
  mode?: string
  created_at?: string
}

export interface CanvasArtifact {
  canvas_id?: string
  title?: string
  provider?: string
  url?: string | null
  diagram_type?: string
  nodes?: Array<Record<string, any>>
  edges?: Array<Record<string, any>>
  layers?: string[][]
}

export interface Health {
  status: string
  timestamp: string
  version: string
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


export type PresentationScene =
  | 'management_briefing'
  | 'project_review'
  | 'proposal_pitch'
  | 'postmortem'
  | 'training'

export interface WebSocketMessage {
  type: 'task.progress' | 'task.completed' | 'task.failed' | 'session.sync' | 'agent.message' | 'pong' | 'doc.updated'
  task_id?: string
  session_id?: string
  step?: string
  message?: string
  progress?: number
  status?: string
  data?: Record<string, any>
  state?: Record<string, any>
  result?: Record<string, any>
  error?: string
  timestamp: string
}
