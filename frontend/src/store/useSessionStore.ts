import { create } from 'zustand'
import type { CanvasArtifact, Task, Document, Slide, Message, SessionStatus } from '../types'

const STORAGE_KEY = 'agent-pilot-session-state'

interface SessionState {
  sessionId: string | null
  task: Task | null
  status: SessionStatus
  currentStep: string
  progress: number
  doc: Document | null
  slides: Slide | null
  canvas: CanvasArtifact | null
  messages: Message[]
  wsConnected: boolean

  setSessionId: (id: string) => void
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
  task: null,
  status: 'idle' as const,
  currentStep: '',
  progress: 0,
  doc: null,
  slides: null,
  canvas: null,
  messages: [],
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
