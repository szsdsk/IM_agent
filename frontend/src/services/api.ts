import type { CanvasArtifact, Session, SessionSnapshot, Task, Document, DocumentHistoryItem, Slide, Message, Health, PresentationScene } from '../types'

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
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || `API Error: ${response.statusText}`)
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

  async deleteSession(sessionId: string): Promise<{ success: boolean; session_id: string }> {
    return fetchAPI<{ success: boolean; session_id: string }>(`/sessions/${sessionId}`, {
      method: 'DELETE',
    })
  },

  async getSessionMessages(sessionId: string): Promise<Message[]> {
    return fetchAPI<Message[]>(`/sessions/${sessionId}/messages`)
  },

  async getSessionState(sessionId: string): Promise<SessionSnapshot> {
    return fetchAPI<SessionSnapshot>(`/sessions/${sessionId}/state`)
  },

  async sendMessage(
    sessionId: string,
    content: string,
    userId?: string,
    presentationScene?: PresentationScene,
    feedbackTaskId?: string,
    clientId?: string,
    deviceType?: string
  ): Promise<Task> {
    return fetchAPI<Task>(`/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        content,
        user_id: userId,
        presentation_scene: presentationScene,
        feedback_task_id: feedbackTaskId,
        client_id: clientId,
        device_type: deviceType,
      }),
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

  async updateCanvas(
    taskId: string,
    canvas: CanvasArtifact,
    clientId?: string,
    deviceType?: string
  ): Promise<{ success: boolean; canvas: CanvasArtifact; task: Task }> {
    return fetchAPI<{ success: boolean; canvas: CanvasArtifact; task: Task }>(`/tasks/${taskId}/canvas`, {
      method: 'PATCH',
      body: JSON.stringify({
        canvas,
        client_id: clientId,
        device_type: deviceType,
      }),
    })
  },

  async getDocument(documentId: string): Promise<Document> {
    return fetchAPI<Document>(`/documents/${documentId}`)
  },

  async getDocumentHistory(documentId: string): Promise<DocumentHistoryItem[]> {
    return fetchAPI<DocumentHistoryItem[]>(`/documents/${documentId}/history`)
  },

  async getSlides(slideId: string): Promise<Slide> {
    return fetchAPI<Slide>(`/slides/${slideId}`)
  },

  // 前端只用 health 判断后端是否存活。
  async healthCheck(): Promise<Health> {
    return fetchAPI<Health>('/health')
  },

  async transcribeVoice(
    audioBlob: Blob,
    language = 'zh'
  ): Promise<{ success: boolean; text?: string; error?: string; provider?: string }> {
    const formData = new FormData()
    const fileName = audioBlob.type.includes('pcm') ? 'voice.pcm' : 'voice.webm'
    formData.append('file', audioBlob, fileName)
    const response = await fetch(`${API_BASE}/voice/transcriptions?language=${encodeURIComponent(language)}`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(err.detail || '语音转写失败')
    }
    return response.json()
  },
}
