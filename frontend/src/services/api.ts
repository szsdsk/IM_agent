import type { Session, Task, Document, Slide, Message, Health } from '../types'

const API_BASE = '/api'

async function fetchAPI<T>(url: string, options: RequestInit = {}): Promise<T> {
  const defaultOptions: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  }

  const response = await fetch(`${API_BASE}${url}`, defaultOptions)
  if (!response.ok) {
    throw new Error(`API Error: ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  async createSession(userId?: string): Promise<Session> {
    return fetchAPI<Session>('/sessions', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    })
  },

  async getSession(sessionId: string): Promise<Session> {
    return fetchAPI<Session>(`/sessions/${sessionId}`)
  },

  async getSessionMessages(sessionId: string): Promise<Message[]> {
    return fetchAPI<Message[]>(`/sessions/${sessionId}/messages`)
  },

  async sendMessage(sessionId: string, content: string, userId?: string): Promise<Task> {
    return fetchAPI<Task>(`/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, user_id: userId }),
    })
  },

  async getTask(taskId: string): Promise<Task> {
    return fetchAPI<Task>(`/tasks/${taskId}`)
  },

  async confirmTask(taskId: string, confirmed: boolean, feedback?: string): Promise<Task> {
    return fetchAPI<Task>(`/tasks/${taskId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ confirmed, feedback }),
    })
  },

  async getDocument(documentId: string): Promise<Document> {
    return fetchAPI<Document>(`/documents/${documentId}`)
  },

  async getSlides(slideId: string): Promise<Slide> {
    return fetchAPI<Slide>(`/slides/${slideId}`)
  },

  // 前端只用 health 判断后端是否存活。
  async healthCheck(): Promise<Health> {
    return fetchAPI<Health>('/health')
  },
}
