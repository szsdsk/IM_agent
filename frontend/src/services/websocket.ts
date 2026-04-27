import { useSessionStore } from '../store/useSessionStore'
import type { SessionStatus, WebSocketMessage } from '../types'

class WebSocketService {
  private ws: WebSocket | null = null
  private sessionId: string | null = null
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectTimer: number | null = null

  connect(sessionId: string): void {
    if (this.ws?.readyState === WebSocket.OPEN && this.sessionId === sessionId) {
      return
    }

    this.sessionId = sessionId
    this.reconnectAttempts = 0
    useSessionStore.getState().setStatus('connecting')

    this.initWebSocket()
  }

  private initWebSocket(): void {
    if (!this.sessionId) return

    this.cleanup()

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/ws/sessions/${this.sessionId}`

    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => {
      console.log('WebSocket connected')
      useSessionStore.getState().setWsConnected(true)
      useSessionStore.getState().setStatus('connected')
      this.reconnectAttempts = 0
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data) as WebSocketMessage
        this.handleMessage(data)
      } catch (error) {
        console.error('WebSocket message parse error:', error)
      }
    }

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      useSessionStore.getState().setStatus('error')
    }

    this.ws.onclose = () => {
      console.log('WebSocket closed')
      useSessionStore.getState().setWsConnected(false)

      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts++
        this.reconnectTimer = window.setTimeout(() => {
          this.initWebSocket()
        }, 1000 * Math.min(this.reconnectAttempts, 5))
      } else {
        useSessionStore.getState().setStatus('error')
      }
    }
  }

  private handleMessage(data: WebSocketMessage): void {
    const store = useSessionStore.getState()

    switch (data.type) {
      case 'task.progress':
        if (data.step) store.setCurrentStep(data.step)
        if (data.progress !== undefined) store.setProgress(data.progress)
        if (data.status) store.setStatus(data.status as SessionStatus)

        if (data.message) {
          store.addMessage({
            id: `msg-${Date.now()}`,
            role: 'system',
            content: data.message,
            timestamp: data.timestamp,
            step: data.step,
          })
        }
        break

      case 'task.completed':
        store.setStatus('completed')
        store.setProgress(1)
        const resultDoc = data.result?.doc || data.result?.document
        const resultSlides = data.result?.slides || data.result?.deck

        if (resultDoc) {
          store.setDoc({
            id: resultDoc.doc_id || data.task_id || `doc-${Date.now()}`,
            task_id: data.task_id || '',
            content: resultDoc.content || resultDoc.preview || '',
            version: 1,
            created_at: data.timestamp,
            doc_url: resultDoc.doc_url || null,
          } as any)
        }
        if (resultSlides) {
          store.setSlides({
            id: resultSlides.slide_id || data.task_id || `slide-${Date.now()}`,
            task_id: data.task_id || '',
            slides_json: resultSlides.slides || [],
            file_path: resultSlides.file_path || null,
            created_at: data.timestamp,
          })
        }
        store.addMessage({
          id: `msg-${Date.now()}`,
          role: 'assistant',
          content: '任务已完成！',
          timestamp: data.timestamp,
        })
        break

      case 'task.failed':
        store.setStatus('failed')
        store.setProgress(0)
        store.addMessage({
          id: `msg-${Date.now()}`,
          role: 'system',
          content: `任务失败：${data.error || '未知错误'}`,
          timestamp: data.timestamp,
        })
        break

      case 'agent.message':
        store.addMessage({
          id: `msg-${Date.now()}`,
          role: 'assistant',
          content: data.data?.content || '',
          timestamp: data.timestamp,
        })
        break

      case 'pong':
        break

      case 'session.sync':
        // Sync state from another tab/client
        if (data.state) {
          const syncState = data.state
          const tasks = syncState.tasks || {}
          const latestTask = Object.values(tasks).pop() as any
          if (latestTask) {
            if (latestTask.current_step) store.setCurrentStep(latestTask.current_step)
            if (latestTask.progress !== undefined) store.setProgress(latestTask.progress)
            if (latestTask.status) store.setStatus(latestTask.status as SessionStatus)
          }
        }
        break
    }
  }

  send(message: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    } else {
      console.warn('WebSocket not connected, message not sent')
    }
  }

  sendMessage(content: string): void {
    this.send({
      type: 'message',
      content,
    })
  }

  ping(): void {
    this.send({ type: 'ping' })
  }

  disconnect(): void {
    this.cleanup()
    this.sessionId = null
    this.reconnectAttempts = 0
    useSessionStore.getState().setWsConnected(false)
  }

  private cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  getSessionId(): string | null {
    return this.sessionId
  }
}

export const wsService = new WebSocketService()
