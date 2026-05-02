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
  progress: 0,
  doc: null,
  slides: null,
  canvas: null,
  messages: [],
  seenEventIds: [],
  wsConnected: false,
}

const initialState = {
  ...baseInitialState,
  ...loadPersistedState(),
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
      progress: snapshot.task?.progress || 0,
      doc: snapshot.doc,
      slides: snapshot.slides,
      messages: snapshot.messages || [],
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
      const messages = [...state.messages, message].slice(-80)
      persistState({ messages })
      return { messages }
    }),

  setMessages: (messages) => {
    persistState({ messages })
    set({ messages })
  },

  setWsConnected: (connected) => set({ wsConnected: connected }),

  resetState: () => {
    if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY)
    set(baseInitialState)
  }
}))
