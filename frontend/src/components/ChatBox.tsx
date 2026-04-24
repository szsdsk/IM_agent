import { useState, useRef, useEffect } from 'react'
import { useSessionStore } from '../store/useSessionStore'
import { api } from '../services/api'
import { wsService } from '../services/websocket'

interface ChatBoxProps {
  className?: string
}

const stepNames: Record<string, string> = {
  receive_input: '接收输入',
  parse_intent: '分析需求',
  plan_workflow: '规划流程',
  extract_tasks: '提取任务',
  generate_doc: '生成文档',
  generate_slides: '生成 PPT',
  confirm_or_modify: '等待确认',
  deliver_result: '交付结果',
}

export default function ChatBox({ className = '' }: ChatBoxProps) {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const { messages, sessionId, status, setTask, addMessage, setSessionId } = useSessionStore()

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || sending) return

    const content = input.trim()
    setInput('')
    setSending(true)

    try {
      let activeSessionId = sessionId

      if (!activeSessionId) {
        const session = await api.createSession()
        activeSessionId = session.id
        setSessionId(session.id)
        wsService.connect(session.id)
      }

      addMessage({
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      })

      const task = await api.sendMessage(activeSessionId, content)
      setTask(task)
    } catch (error) {
      console.error('Failed to send message:', error)
      addMessage({
        id: `error-${Date.now()}`,
        role: 'system',
        content: '发送失败，请重试',
        timestamp: new Date().toISOString(),
      })
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const getMessageStyle = (role: string) => {
    switch (role) {
      case 'user':
        return 'bg-primary-500 text-white ml-auto'
      case 'assistant':
        return 'bg-gray-100 text-gray-800 mr-auto'
      case 'system':
        return 'bg-gray-50 text-gray-500 text-sm mx-auto'
      default:
        return 'bg-gray-100 text-gray-800 mr-auto'
    }
  }

  return (
    <div className={`flex flex-col h-full border rounded-lg bg-white shadow-sm ${className}`}>
      <div className="px-4 py-3 border-b bg-gray-50 rounded-t-lg">
        <h3 className="font-medium text-gray-800">Agent 对话</h3>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center text-gray-400 text-sm text-center">
            <p>请输入您的需求，我将为您自动完成任务</p>
          </div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id}
              className={`max-w-[80%] px-4 py-2 rounded-lg ${getMessageStyle(msg.role)}`}
            >
              {msg.step && (
                <div className="text-xs opacity-70 mb-1">{stepNames[msg.step] || msg.step}</div>
              )}
              <p className="whitespace-pre-wrap">{msg.content}</p>
              <div className="text-xs opacity-50 mt-1">
                {new Date(msg.timestamp).toLocaleTimeString()}
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-3 border-t">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="请输入您的需求..."
            disabled={sending || status === 'running'}
            className="flex-1 px-3 py-2 border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-gray-50 disabled:text-gray-500"
            rows={2}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending || status === 'running'}
            className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {sending ? '发送中...' : '发送'}
          </button>
        </div>
      </div>
    </div>
  )
}
