import { api } from './api'
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

    const store = useSessionStore.getState()
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = new URLSearchParams({
      client_id: store.clientId,
      device_type: store.deviceType,
    })
    const wsUrl = `${protocol}//${window.location.host}/api/ws/sessions/${this.sessionId}?${params.toString()}`

    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = async () => {
      useSessionStore.getState().setWsConnected(true)
      useSessionStore.getState().setStatus('connected')
      this.reconnectAttempts = 0

      // WebSocket 连接成功后先拉一次快照，避免重连期间漏掉事件。
      try {
        if (this.sessionId) {
          const snapshot = await api.getSessionState(this.sessionId)
          useSessionStore.getState().hydrateSnapshot(snapshot)
        }
      } catch (error) {
        console.warn('Failed to hydrate session snapshot:', error)
      }
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
      useSessionStore.getState().setWsConnected(false)

      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.reconnectAttempts += 1
        this.reconnectTimer = window.setTimeout(() => {
          this.initWebSocket()
        }, 1000 * Math.min(this.reconnectAttempts, 5))
      } else {
        useSessionStore.getState().setStatus('error')
      }
    }
  }

  private payload(data: WebSocketMessage): Record<string, any> {
    return data.data || {}
  }

  private handleMessage(data: WebSocketMessage): void {
    const store = useSessionStore.getState()
    if (store.markEventSeen(data.event_id)) return

    switch (data.type) {
      case 'message.created': {
        const payload = this.payload(data)
        if (!payload.content) return
        if (data.source_client_id && data.source_client_id === store.clientId) return
        store.addMessage({
          id: data.event_id || `msg-${Date.now()}`,
          role: payload.role || 'system',
          content: payload.content,
          timestamp: data.timestamp,
        })
        break
      }

      case 'task.created': {
        const task = this.payload(data).task
        if (task) {
          store.setTask(task)
          store.setStatus('running')
          store.setCurrentStep(task.current_step || 'receive_input')
          store.setProgress(task.progress || 0)
        }
        break
      }

      case 'task.progress': {
        const payload = this.payload(data)
        const step = data.step ?? payload.step
        const progress = data.progress ?? payload.progress
        const status = data.status ?? payload.status
        const message = data.message ?? payload.message

        if (data.task_id) {
          store.setTask({
            id: data.task_id,
            session_id: data.session_id || this.sessionId || '',
            intent: store.task?.intent || '',
            status: (status as any) || 'running',
            current_step: step || store.currentStep,
            progress: progress ?? store.progress,
            result_json: store.task?.result_json || null,
            created_at: store.task?.created_at || data.timestamp,
            updated_at: data.timestamp,
          })
        }
        if (step) store.setCurrentStep(step)
        if (progress !== undefined) store.setProgress(progress)
        if (status) store.setStatus(status as SessionStatus)

        if (message) {
          store.addMessage({
            id: data.event_id || `msg-${Date.now()}`,
            role: 'system',
            content: message,
            timestamp: data.timestamp,
            step,
          })
        }
        break
      }

      case 'artifact.updated': {
        const payload = this.payload(data)
        const artifactType = payload.artifact_type
        const artifact = payload.artifact
        if (artifactType === 'document' && artifact) store.setDoc(artifact)
        if (artifactType === 'slides' && artifact) store.setSlides(artifact)
        if (artifactType === 'canvas' && artifact) store.setCanvas(artifact)
        break
      }

      case 'task.completed': {
        const payload = this.payload(data)
        const result = data.result || payload.result
        store.setStatus('completed')
        store.setProgress(1)

        const resultDoc = result?.doc || result?.document
        const resultSlides = result?.slides || result?.deck
        const resultCanvas = result?.canvas

        if (data.task_id) {
          store.setTask({
            id: data.task_id,
            session_id: data.session_id || this.sessionId || '',
            intent: store.task?.intent || '',
            status: 'completed',
            current_step: 'deliver_result',
            progress: 1,
            result_json: result || null,
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
        if (resultCanvas) store.setCanvas(resultCanvas)
        store.addMessage({
          id: data.event_id || `msg-${Date.now()}`,
          role: 'assistant',
          content: '任务已完成！',
          timestamp: data.timestamp,
        })
        break
      }

      case 'task.failed': {
        const payload = this.payload(data)
        const error = data.error || payload.error
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
          id: data.event_id || `msg-${Date.now()}`,
          role: 'system',
          content: `任务失败：${error || '未知错误'}`,
          timestamp: data.timestamp,
        })
        break
      }

      case 'delivery.created': {
        const payload = this.payload(data)
        const delivery = payload.delivery || {}
        if (delivery.status === 'confirmed') {
          store.setStatus('completed')
          store.addMessage({
            id: data.event_id || `delivery-${Date.now()}`,
            role: 'system',
            content: '交付已确认，当前任务已锁定。',
            timestamp: data.timestamp,
          })
        }
        break
      }

      case 'agent.message': {
        const payload = this.payload(data)
        store.addMessage({
          id: data.event_id || `msg-${Date.now()}`,
          role: 'assistant',
          content: payload.content || '',
          timestamp: data.timestamp,
        })
        break
      }

      case 'session.sync':
      case 'sync.response':
        if (data.state) {
          store.hydrateSnapshot(data.state as any)
        }
        break

      case 'doc.updated': {
        const payload = this.payload(data)
        const changes = payload.changes || {}
        const docId = payload.doc_id
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
        const editor = changes.last_edited_by ? ` by ${changes.last_edited_by}` : ''
        const changed = changes.changed_lines !== undefined ? `，变更 ${changes.changed_lines} 行` : ''
        store.addMessage({
          id: data.event_id || `doc-${Date.now()}`,
          role: 'system',
          content: `文档已在飞书中编辑${editor}，版本已更新至 v${changes.version || '?'}${changed}`,
          timestamp: data.timestamp,
        })
        break
      }

      case 'pong':
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

  sendMessage(content: string, presentationScene?: string, feedbackTaskId?: string): void {
    this.send({
      type: 'message',
      content,
      presentation_scene: presentationScene,
      feedback_task_id: feedbackTaskId,
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
