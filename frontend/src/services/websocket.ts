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
        if (data.task_id) {
          store.setTask({
            id: data.task_id,
            session_id: data.session_id || this.sessionId || '',
            intent: store.task?.intent || '',
            status: (data.status as any) || 'running',
            current_step: data.step || store.currentStep,
            progress: data.progress ?? store.progress,
            result_json: store.task?.result_json || null,
            created_at: store.task?.created_at || data.timestamp,
            updated_at: data.timestamp,
          })
        }
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
        const resultCanvas = data.result?.canvas

        if (data.task_id) {
          store.setTask({
            id: data.task_id,
            session_id: data.session_id || this.sessionId || '',
            intent: store.task?.intent || '',
            status: 'completed',
            current_step: 'deliver_result',
            progress: 1,
            result_json: data.result || null,
            created_at: store.task?.created_at || data.timestamp,
            updated_at: data.timestamp,
          })
        }

        if (resultDoc) {
          store.setDoc({
            id: resultDoc.doc_id || data.task_id || `doc-${Date.now()}`,
            task_id: data.task_id || '',
            content: resultDoc.content || resultDoc.preview || '',
            version: resultDoc.version || 1,
            created_at: data.timestamp,
            doc_url: resultDoc.doc_url || resultDoc.lark_doc_url || null,
            lark_doc_url: resultDoc.lark_doc_url || resultDoc.doc_url || null,
            lark_doc_id: resultDoc.lark_doc_id || null,
            last_edited_by: resultDoc.last_edited_by || null,
            last_edited_at: resultDoc.last_edited_at || null,
          } as any)
        }
        if (resultSlides) {
          store.setSlides({
            id: resultSlides.slide_id || data.task_id || `slide-${Date.now()}`,
            task_id: data.task_id || '',
            slides_json: resultSlides,
            file_path: resultSlides.file_path || null,
            created_at: data.timestamp,
          })
        }
        if (resultCanvas) {
          store.setCanvas(resultCanvas)
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
        if (data.task_id) {
          store.setTask({
            id: data.task_id,
            session_id: data.session_id || this.sessionId || '',
            intent: store.task?.intent || '',
            status: 'failed',
            current_step: store.currentStep,
            progress: 0,
            result_json: null,
            created_at: store.task?.created_at || data.timestamp,
            updated_at: data.timestamp,
          })
        }
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

      case 'doc.updated':
        // Document edited in Feishu - update local state and notify user
        if (data.data) {
          const changes = data.data.changes || {}
          const docId = data.data.doc_id
          const currentDoc = store.doc
          if (currentDoc && (currentDoc.id === docId || currentDoc.lark_doc_id === docId || currentDoc.lark_doc_id === changes.lark_doc_id)) {
            store.setDoc({
              ...currentDoc,
              content: changes.content ?? currentDoc.content,
              lark_doc_id: changes.lark_doc_id || currentDoc.lark_doc_id,
              lark_doc_url: changes.lark_doc_url || currentDoc.lark_doc_url,
              last_edited_by: changes.last_edited_by || currentDoc.last_edited_by,
              last_edited_at: changes.last_edited_at || currentDoc.last_edited_at,
              version: changes.version || currentDoc.version,
              diff_summary: changes.diff_summary || currentDoc.diff_summary,
              changed_lines: changes.changed_lines ?? currentDoc.changed_lines,
            } as any)
          }
          // Notify user
          const editor = changes.last_edited_by ? ` by ${changes.last_edited_by}` : ''
          const changed = changes.changed_lines !== undefined ? `，变更 ${changes.changed_lines} 行` : ''
          store.addMessage({
            id: `msg-${Date.now()}`,
            role: 'system',
            content: `文档已在飞书中编辑${editor}，版本已更新至 v${changes.version || '?'}${changed}`,
            timestamp: data.timestamp,
          })
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

  sendMessage(content: string, presentationScene?: string): void {
    this.send({
      type: 'message',
      content,
      presentation_scene: presentationScene,
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
