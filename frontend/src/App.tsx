import { useEffect, useState } from 'react'
import AgentStatus from './components/AgentStatus'
import ProgressTimeline from './components/ProgressTimeline'
import DocViewer from './components/DocViewer'
import SlideViewer from './components/SlideViewer'
import CanvasViewer from './components/CanvasViewer'
import VoiceTranscriber from './components/VoiceTranscriber'
import { api } from './services/api'
import { wsService } from './services/websocket'
import { useSessionStore } from './store/useSessionStore'

export default function App() {
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
  const sessionId = useSessionStore((state) => state.sessionId)
  const setSessionId = useSessionStore((state) => state.setSessionId)

  useEffect(() => {
    const checkHealth = async () => {
      try {
        await api.healthCheck()
        setBackendHealthy(true)
      } catch {
        setBackendHealthy(false)
      }
    }

    checkHealth()
    const interval = setInterval(checkHealth, 5000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    let cancelled = false

    const connectSession = async () => {
      try {
        if (sessionId) {
          wsService.connect(sessionId)
          return
        }
        const urlSessionId = new URLSearchParams(window.location.search).get('session_id')
        if (urlSessionId) {
          setSessionId(urlSessionId)
          wsService.connect(urlSessionId)
          return
        }
        const session = await api.createSession()
        if (cancelled) return
        setSessionId(session.id)
        wsService.connect(session.id)
      } catch (error) {
        console.error('Failed to connect websocket session:', error)
      }
    }

    connectSession()

    return () => {
      cancelled = true
    }
  }, [sessionId, setSessionId])

  const copySyncLink = async () => {
    if (!sessionId) return
    const url = new URL(window.location.href)
    url.searchParams.set('session_id', sessionId)
    if (['localhost', '127.0.0.1', '0.0.0.0', '[::1]', '::1'].includes(url.hostname)) {
      try {
        const health = await api.healthCheck()
        if (health.local_ip) {
          url.hostname = health.local_ip
        }
      } catch {
        // 获取局域网 IP 失败时保留 localhost 链接，避免影响复制功能本身。
      }
    }
    await navigator.clipboard.writeText(url.toString())
    setShareCopied(true)
    window.setTimeout(() => setShareCopied(false), 1500)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b shadow-sm">
        <div className="max-w-[1920px] mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-sm font-bold text-blue-600" aria-hidden="true">
              AI
            </span>
            <h1 className="text-xl font-semibold text-gray-800">Agent-Pilot 智能办公助手</h1>
          </div>
          <div className="flex items-center gap-3">
            {sessionId && (
              <button
                onClick={copySyncLink}
                className="rounded-md border border-blue-200 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-50"
              >
                {shareCopied ? '已复制同步链接' : '复制同步链接'}
              </button>
            )}
            <span
              className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs ${
                backendHealthy === null
                  ? 'bg-gray-100 text-gray-500'
                  : backendHealthy
                    ? 'bg-green-100 text-green-700'
                    : 'bg-red-100 text-red-700'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  backendHealthy === null
                    ? 'bg-gray-400'
                    : backendHealthy
                      ? 'bg-green-500'
                      : 'bg-red-500'
                }`}
              />
              {backendHealthy === null ? '检查连接中...' : backendHealthy ? '后端正常' : '后端未连接'}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-[1920px] mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-3 flex flex-col gap-6">
            <VoiceTranscriber />
          </div>

          <div className="lg:col-span-3 flex flex-col gap-6">
            <AgentStatus />
            <ProgressTimeline />
          </div>

          <div className="lg:col-span-6 space-y-6">
            <DocViewer />
            <CanvasViewer />
            <SlideViewer />
          </div>
        </div>
      </main>

      <footer className="mt-12 py-4 text-center text-xs text-gray-500 border-t">
        <p>Agent-Pilot © 2024 - 智能办公协同系统</p>
      </footer>
    </div>
  )
}
