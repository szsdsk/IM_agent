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
  lark_doc_url?: string | null
  last_edited_by?: string | null
  last_edited_at?: string | null
  diff_summary?: string | null
  changed_lines?: number | null
}

export interface DocumentHistoryItem {
  id: string
  event_type: string
  payload: Record<string, any>
  created_at: string
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
  theme?: string
  visual_profile?: string | null
  slides?: VisualSlideItem[]
  metadata?: Record<string, any>
  rehearsal?: RehearsalPlan | null
  qa?: QAItem[]
  feedback_history?: FeedbackHistoryItem[]
}

export interface VisualSlideItem {
  title?: string
  layout?: string
  layout_variant?: string | null
  visual_profile?: string | null
  content?: unknown
  bullets?: string[]
  highlight_metrics?: Array<Record<string, string>>
  sections?: Array<Record<string, string>>
  timeline?: Array<Record<string, string>>
  process_steps?: Array<Record<string, string>>
  chart?: {
    type: 'bar' | 'pie' | 'line' | 'horizontal_bar'
    title?: string
    categories: string[]
    series: Array<{
      name: string
      values: number[]
    }>
  }
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
  elements?: Array<Record<string, any>>
  viewport?: {
    x: number
    y: number
    width: number
    height: number
  }
  metadata?: Record<string, any>
  exportable?: boolean
}

export interface Health {
  status: string
  timestamp: string
  version: string
  local_ip?: string | null
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

export interface SessionSnapshot {
  session: Session
  tasks: Task[]
  task: Task | null
  documents: Document[]
  doc: Document | null
  slides_artifacts: Slide[]
  slides: Slide | null
  canvas?: CanvasArtifact | null
  messages: Message[]
  events: Array<Record<string, any>>
  last_event_id?: string | null
}


export type PresentationScene =
  | 'management_briefing'
  | 'project_review'
  | 'proposal_pitch'
  | 'postmortem'
  | 'training'

export interface WebSocketMessage {
  type:
    | 'message.created'
    | 'task.created'
    | 'task.progress'
    | 'task.completed'
    | 'task.failed'
    | 'artifact.updated'
    | 'delivery.created'
    | 'session.sync'
    | 'agent.message'
    | 'pong'
    | 'doc.updated'
    | 'slides.updated'
    | 'canvas.updated'
    | 'sync.request'
    | 'sync.response'
    | string
  event_id?: string
  task_id?: string
  session_id?: string
  source_client_id?: string
  device_type?: string
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
