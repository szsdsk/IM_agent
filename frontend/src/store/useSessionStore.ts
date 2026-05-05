import { create } from 'zustand'
import type { CanvasArtifact, Task, Document, Slide, Message, SessionSnapshot, SessionStatus } from '../types'

const STORAGE_KEY = 'agent-pilot-session-state'
const CLIENT_ID_KEY = 'agent-pilot-client-id'

function createClientId(): string {
  if (typeof window === 'undefined') return `server-${Date.now()}`
  const existing = window.localStorage.getItem(CLIENT_ID_KEY)
  if (existing) return existing
  const next =
    typeof window.crypto?.randomUUID === 'function'
      ? window.crypto.randomUUID()
      : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`
  window.localStorage.setItem(CLIENT_ID_KEY, next)
  return next
}

function detectDeviceType(): 'desktop' | 'mobile' {
  if (typeof window === 'undefined') return 'desktop'
  return window.matchMedia('(max-width: 768px)').matches ? 'mobile' : 'desktop'
}

interface SessionState {
  sessionId: string | null
  clientId: string
  deviceType: 'desktop' | 'mobile'
  task: Task | null
  status: SessionStatus
  currentStep: string
  activeAgent: string
  progressMessage: string
  progress: number
  doc: Document | null
  slides: Slide | null
  canvas: CanvasArtifact | null
  messages: Message[]
  seenEventIds: string[]
  wsConnected: boolean

  setSessionId: (id: string) => void
  hydrateSnapshot: (snapshot: SessionSnapshot) => void
  markEventSeen: (eventId?: string) => boolean
  setTask: (task: Task | null) => void
  setStatus: (status: SessionState['status']) => void
  setCurrentStep: (step: string) => void
  setActiveAgent: (agent: string) => void
  setProgressMessage: (message: string) => void
  setProgress: (progress: number) => void
  setDoc: (doc: Document | null) => void
  setSlides: (slides: Slide | null) => void
  setCanvas: (canvas: CanvasArtifact | null) => void
  addMessage: (message: Message) => void
  setMessages: (messages: Message[]) => void
  setWsConnected: (connected: boolean) => void
  resetState: () => void
}

function loadPersistedState(): Partial<SessionState> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function persistState(partial: Partial<SessionState>): void {
  if (typeof window === 'undefined') return
  try {
    const current = loadPersistedState()
    const next = {
      ...current,
      ...partial,
      wsConnected: false,
      status: partial.status === 'running' ? 'connected' : partial.status ?? current.status,
    }
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // 本地存储失败不影响主流程。
  }
}

const baseInitialState = {
  sessionId: null,
  clientId: createClientId(),
  deviceType: detectDeviceType(),
  task: null,
  status: 'idle' as const,
  currentStep: '',
  activeAgent: '',
  progressMessage: '',
  progress: 0,
  doc: null,
  slides: null,
  canvas: null,
  messages: [],
  seenEventIds: [],
  wsConnected: false,
}

function timestampMs(value: string): number {
  // 后端 SQLite 中的 UTC 时间可能没有时区后缀；前端统一按 UTC 解析。
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const ms = new Date(normalized).getTime()
  return Number.isNaN(ms) ? 0 : ms
}

function sameMessage(a: Message, b: Message): boolean {
  if (a.id === b.id) return true
  if (a.role !== b.role || a.content.trim() !== b.content.trim()) return false
  // 用户输入会先乐观显示，再被后端事件/快照回填；2 分钟内同内容视为同一条。
  if (a.role === 'user') return Math.abs(timestampMs(a.timestamp) - timestampMs(b.timestamp)) <= 2 * 60 * 1000
  return false
}

function mergeMessages(messages: Message[]): Message[] {
  const merged: Message[] = []
  for (const message of messages) {
    const existingIndex = merged.findIndex((item) => sameMessage(item, message))
    if (existingIndex >= 0) {
      // 保留后端事件 id，同时优先使用能被正确解析的时间戳。
      merged[existingIndex] = {
        ...merged[existingIndex],
        ...message,
        timestamp: message.timestamp || merged[existingIndex].timestamp,
      }
      continue
    }
    merged.push(message)
  }
  return merged.slice(-80)
}

const initialState = {
  ...baseInitialState,
  ...loadPersistedState(),
}
if (Array.isArray(initialState.messages)) {
  initialState.messages = mergeMessages(initialState.messages)
}

export const useSessionStore = create<SessionState>((set) => ({
  ...initialState,

  setSessionId: (id) => {
    persistState({ sessionId: id })
    set({ sessionId: id })
  },
  hydrateSnapshot: (snapshot) => {
    const next = {
      sessionId: snapshot.session.id,
      task: snapshot.task,
      status: (snapshot.task?.status === 'completed'
        ? 'completed'
        : snapshot.task?.status === 'failed'
          ? 'failed'
          : snapshot.task
            ? 'running'
            : 'connected') as SessionState['status'],
      currentStep: snapshot.task?.current_step || '',
      activeAgent: snapshot.task?.result_json?.active_agent || '',
      progressMessage: '',
      progress: snapshot.task?.progress || 0,
      doc: snapshot.doc,
      slides: snapshot.slides,
      canvas: snapshot.canvas || null,
      messages: mergeMessages(snapshot.messages || []),
    }
    persistState(next)
    set(next)
  },
  markEventSeen: (eventId) => {
    if (!eventId) return false
    let seen = false
    set((state) => {
      seen = state.seenEventIds.includes(eventId)
      if (seen) return state
      const seenEventIds = [...state.seenEventIds, eventId].slice(-200)
      return { seenEventIds }
    })
    return seen
  },
  setTask: (task) => {
    persistState({ task })
    set({ task })
  },
  setStatus: (status) => {
    persistState({ status })
    set({ status })
  },
  setCurrentStep: (step) => {
    persistState({ currentStep: step })
    set({ currentStep: step })
  },
  setActiveAgent: (agent) => {
    persistState({ activeAgent: agent })
    set({ activeAgent: agent })
  },
  setProgressMessage: (message) => {
    persistState({ progressMessage: message })
    set({ progressMessage: message })
  },
  setProgress: (progress) => {
    persistState({ progress })
    set({ progress })
  },
  setDoc: (doc) => {
    persistState({ doc })
    set({ doc })
  },
  setSlides: (slides) => {
    persistState({ slides })
    set({ slides })
  },
  setCanvas: (canvas) => {
    persistState({ canvas })
    set({ canvas })
  },
  
  addMessage: (message) => 
    set((state) => {
      const messages = mergeMessages([...state.messages, message])
      persistState({ messages })
      return { messages }
    }),

  setMessages: (messages) => {
    const merged = mergeMessages(messages)
    persistState({ messages: merged })
    set({ messages: merged })
  },

  setWsConnected: (connected) => set({ wsConnected: connected }),

  resetState: () => {
    if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY)
    set(baseInitialState)
  }
}))
