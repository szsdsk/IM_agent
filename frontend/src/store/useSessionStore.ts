import { create } from 'zustand'
import type { Task, Document, Slide, Message, SessionStatus } from '../types'

interface SessionState {
  sessionId: string | null
  task: Task | null
  status: SessionStatus
  currentStep: string
  progress: number
  doc: Document | null
  slides: Slide | null
  messages: Message[]
  wsConnected: boolean

  setSessionId: (id: string) => void
  setTask: (task: Task | null) => void
  setStatus: (status: SessionState['status']) => void
  setCurrentStep: (step: string) => void
  setProgress: (progress: number) => void
  setDoc: (doc: Document | null) => void
  setSlides: (slides: Slide | null) => void
  addMessage: (message: Message) => void
  setMessages: (messages: Message[]) => void
  setWsConnected: (connected: boolean) => void
  resetState: () => void
}

const initialState = {
  sessionId: null,
  task: null,
  status: 'idle' as const,
  currentStep: '',
  progress: 0,
  doc: null,
  slides: null,
  messages: [],
  wsConnected: false
}

export const useSessionStore = create<SessionState>((set) => ({
  ...initialState,

  setSessionId: (id) => set({ sessionId: id }),
  setTask: (task) => set({ task }),
  setStatus: (status) => set({ status }),
  setCurrentStep: (step) => set({ currentStep: step }),
  setProgress: (progress) => set({ progress }),
  setDoc: (doc) => set({ doc }),
  setSlides: (slides) => set({ slides }),
  
  addMessage: (message) => 
    set((state) => ({ 
      messages: [...state.messages, message] 
    })),

  setMessages: (messages) => set({ messages }),

  setWsConnected: (connected) => set({ wsConnected: connected }),

  resetState: () => set(initialState)
}))
