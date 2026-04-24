import { useEffect, useState } from 'react'
import ChatBox from './components/ChatBox'
import AgentStatus from './components/AgentStatus'
import ProgressTimeline from './components/ProgressTimeline'
import DocViewer from './components/DocViewer'
import SlideViewer from './components/SlideViewer'
import { api } from './services/api'

export default function App() {
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null)

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
            <ChatBox className="h-[600px]" />
          </div>

          <div className="lg:col-span-3 flex flex-col gap-6">
            <AgentStatus />
            <ProgressTimeline />
          </div>

          <div className="lg:col-span-6 space-y-6">
            <DocViewer />
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
