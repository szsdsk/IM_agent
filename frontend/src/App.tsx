import { useEffect, useMemo, useState } from 'react'
import DocViewer from './components/DocViewer'
import SlideViewer from './components/SlideViewer'
import CanvasViewer from './components/CanvasViewer'
import SyncQRCode from './components/SyncQRCode'
import VoiceTranscriber from './components/VoiceTranscriber'
import { api } from './services/api'
import { wsService } from './services/websocket'
import { useSessionStore } from './store/useSessionStore'
import type { Message } from './types'

const CONVERSATION_HISTORY_KEY = 'agent-pilot-conversation-history'

type ArtifactPanel = 'doc' | 'slides' | 'canvas' | null

interface ConversationHistoryItem {
  id: string
  title: string
  createdAt: string
  updatedAt: string
}

function loadConversationHistory(): ConversationHistoryItem[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(CONVERSATION_HISTORY_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveConversationHistory(items: ConversationHistoryItem[]): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(CONVERSATION_HISTORY_KEY, JSON.stringify(items.slice(0, 30)))
}

function conversationTitle(messages: Message[], fallback?: string): string {
  const firstUserMessage = messages.find((message) => message.role === 'user' && message.content.trim())
  const title = firstUserMessage?.content || fallback || '新对话'
  return title.length > 24 ? `${title.slice(0, 24)}...` : title
}

function formatConversationTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function App() {
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null)
  const [shareCopied, setShareCopied] = useState(false)
  const [qrOpen, setQrOpen] = useState(false)
  const [syncUrl, setSyncUrl] = useState('')
  const [syncUrlLoading, setSyncUrlLoading] = useState(false)
  const [syncUrlError, setSyncUrlError] = useState<string | null>(null)
  const [creatingConversation, setCreatingConversation] = useState(false)
  const [selectedArtifact, setSelectedArtifact] = useState<ArtifactPanel>(null)
  const [conversationHistory, setConversationHistory] = useState<ConversationHistoryItem[]>(() => loadConversationHistory())

  const sessionId = useSessionStore((state) => state.sessionId)
  const messages = useSessionStore((state) => state.messages)
  const task = useSessionStore((state) => state.task)
  const doc = useSessionStore((state) => state.doc)
  const slides = useSessionStore((state) => state.slides)
  const canvas = useSessionStore((state) => state.canvas)
  const setSessionId = useSessionStore((state) => state.setSessionId)
  const hydrateSnapshot = useSessionStore((state) => state.hydrateSnapshot)
  const resetState = useSessionStore((state) => state.resetState)

  const sortedConversationHistory = useMemo(
    () => [...conversationHistory].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    [conversationHistory]
  )

  const hasArtifacts = Boolean(doc || slides || canvas)

  const upsertConversation = (id: string, title = '新对话', timestamp = new Date().toISOString()) => {
    setConversationHistory((current) => {
      const existing = current.find((item) => item.id === id)
      const next = existing
        ? current.map((item) =>
            item.id === id
              ? {
                  ...item,
                  title: title || item.title,
                  updatedAt: timestamp,
                }
              : item
          )
        : [
            {
              id,
              title,
              createdAt: timestamp,
              updatedAt: timestamp,
            },
            ...current,
          ]
      saveConversationHistory(next)
      return next.slice(0, 30)
    })
  }

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
      if (creatingConversation) return
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
        upsertConversation(session.id, '新对话', session.created_at)
        wsService.connect(session.id)
      } catch (error) {
        console.error('Failed to connect websocket session:', error)
      }
    }

    connectSession()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creatingConversation, sessionId, setSessionId])

  useEffect(() => {
    if (!sessionId) return
    upsertConversation(sessionId, conversationTitle(messages, task?.intent), new Date().toISOString())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, messages, task?.intent])

  useEffect(() => {
    if (selectedArtifact === 'doc' && !doc) setSelectedArtifact(null)
    if (selectedArtifact === 'slides' && !slides) setSelectedArtifact(null)
    if (selectedArtifact === 'canvas' && !canvas) setSelectedArtifact(null)
  }, [canvas, doc, selectedArtifact, slides])

  useEffect(() => {
    if (!sessionId) {
      setQrOpen(false)
      setSyncUrl('')
      setSyncUrlError(null)
    }
  }, [sessionId])

  const startNewConversation = async () => {
    if (creatingConversation) return
    setCreatingConversation(true)
    setSelectedArtifact(null)
    try {
      wsService.disconnect()
      resetState()
      const url = new URL(window.location.href)
      url.searchParams.delete('session_id')
      window.history.replaceState({}, '', url.toString())

      const session = await api.createSession()
      upsertConversation(session.id, '新对话', session.created_at)
      setSessionId(session.id)
      wsService.connect(session.id)
    } catch (error) {
      console.error('Failed to create new conversation:', error)
    } finally {
      setCreatingConversation(false)
    }
  }

  const openConversation = async (conversationId: string) => {
    if (!conversationId || conversationId === sessionId || creatingConversation) return
    setCreatingConversation(true)
    setSelectedArtifact(null)
    try {
      wsService.disconnect()
      resetState()
      const url = new URL(window.location.href)
      url.searchParams.set('session_id', conversationId)
      window.history.replaceState({}, '', url.toString())
      setSessionId(conversationId)
      wsService.connect(conversationId)
      const snapshot = await api.getSessionState(conversationId)
      hydrateSnapshot(snapshot)
      upsertConversation(conversationId, conversationTitle(snapshot.messages, snapshot.task?.intent), new Date().toISOString())
    } catch (error) {
      console.error('Failed to open conversation:', error)
    } finally {
      setCreatingConversation(false)
    }
  }

  const deleteConversation = async (conversationId: string) => {
    if (!conversationId || creatingConversation) return
    const confirmed = window.confirm('删除这个对话后，它的短期记忆和产物记录也会被清除。确定删除吗？')
    if (!confirmed) return

    setCreatingConversation(true)
    const remaining = conversationHistory
      .filter((item) => item.id !== conversationId)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    setConversationHistory(remaining)
    saveConversationHistory(remaining)

    try {
      await api.deleteSession(conversationId)
    } catch (error) {
      console.error('Failed to delete conversation:', error)
    }

    try {
      if (conversationId === sessionId) {
        wsService.disconnect()
        resetState()
        setSelectedArtifact(null)
        const url = new URL(window.location.href)
        url.searchParams.delete('session_id')
        window.history.replaceState({}, '', url.toString())

        const nextConversation = remaining[0]
        if (nextConversation) {
          setSessionId(nextConversation.id)
          wsService.connect(nextConversation.id)
          const snapshot = await api.getSessionState(nextConversation.id)
          hydrateSnapshot(snapshot)
        } else {
          const session = await api.createSession()
          upsertConversation(session.id, '新对话', session.created_at)
          setSessionId(session.id)
          wsService.connect(session.id)
        }
      }
    } catch (error) {
      console.error('Failed to switch conversation after delete:', error)
    } finally {
      setCreatingConversation(false)
    }
  }

  const buildSyncLink = async () => {
    if (!sessionId) return ''
    const url = new URL(window.location.href)
    url.searchParams.set('session_id', sessionId)
    if (['localhost', '127.0.0.1', '0.0.0.0', '[::1]', '::1'].includes(url.hostname)) {
      try {
        const health = await api.healthCheck()
        if (health.local_ip) {
          url.hostname = health.local_ip
        }
      } catch {
        // Keep the current host if LAN IP detection fails.
      }
    }
    return url.toString()
  }

  const copySyncLink = async () => {
    const link = await buildSyncLink()
    if (!link) return
    await navigator.clipboard.writeText(link)
    setSyncUrl(link)
    setShareCopied(true)
    window.setTimeout(() => setShareCopied(false), 1500)
  }

  const openSyncQr = async () => {
    if (!sessionId) return
    if (qrOpen) {
      setQrOpen(false)
      return
    }

    setQrOpen(true)
    setSyncUrlLoading(true)
    setSyncUrlError(null)
    try {
      const link = await buildSyncLink()
      setSyncUrl(link)
    } catch (error) {
      console.error('Failed to create sync QR code:', error)
      setSyncUrlError('二维码生成失败')
    } finally {
      setSyncUrlLoading(false)
    }
  }

  const renderArtifactPanel = () => {
    if (selectedArtifact === 'doc') return <DocViewer className="h-full" />
    if (selectedArtifact === 'slides') return <SlideViewer className="h-full" />
    if (selectedArtifact === 'canvas') {
      return <CanvasViewer className="h-full" onOpenArtifact={(artifact) => setSelectedArtifact(artifact)} />
    }
    return null
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#f7f7f5] text-gray-900">
      <aside className="hidden w-72 flex-none border-r border-gray-200 bg-[#f3f3ee] p-3 lg:flex lg:flex-col">
        <div className="mb-3 flex items-center gap-2 px-2 py-1">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-gray-900 text-sm font-semibold text-white">
            AI
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-sm font-semibold text-gray-900">Agent-Pilot</h1>
            <p className="text-xs text-gray-500">智能办公助手</p>
          </div>
        </div>

        <button
          onClick={startNewConversation}
          disabled={creatingConversation}
          className="mb-3 flex h-10 w-full items-center justify-center rounded-md border border-gray-300 bg-white px-3 text-sm font-medium text-gray-800 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {creatingConversation ? '创建中...' : '+ 新建对话'}
        </button>

        <div className="mb-2 flex items-center justify-between px-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">历史对话</h2>
          <span className="text-xs text-gray-400">{sortedConversationHistory.length}</span>
        </div>

        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
          {sortedConversationHistory.length === 0 ? (
            <p className="px-2 py-3 text-xs text-gray-500">还没有历史对话</p>
          ) : (
            sortedConversationHistory.map((conversation) => {
              const active = conversation.id === sessionId
              return (
                <div
                  key={conversation.id}
                  className={`group flex items-center rounded-md transition ${
                    active ? 'bg-white text-gray-950 shadow-sm' : 'text-gray-700 hover:bg-white/70'
                  }`}
                >
                  <button
                    onClick={() => openConversation(conversation.id)}
                    className="min-w-0 flex-1 px-3 py-2 text-left"
                  >
                    <div className="truncate text-sm font-medium">{conversation.title}</div>
                    <div className="mt-0.5 truncate text-xs text-gray-400">
                      {formatConversationTime(conversation.updatedAt)}
                    </div>
                  </button>
                  <button
                    onClick={() => deleteConversation(conversation.id)}
                    disabled={creatingConversation}
                    title="删除对话"
                    className="mr-1 flex h-7 w-7 flex-none items-center justify-center rounded-md text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40 lg:opacity-0 lg:group-hover:opacity-100"
                  >
                    ×
                  </button>
                </div>
              )
            })
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 flex-none items-center justify-between border-b border-gray-200 bg-white px-4">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-gray-900">
              {conversationTitle(messages, task?.intent)}
            </p>
            <p className="text-xs text-gray-500">
              {backendHealthy === null ? '正在检查连接...' : backendHealthy ? '后端正常' : '后端未连接'}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {hasArtifacts && (
              <div className="hidden items-center gap-1 rounded-md border border-gray-200 bg-gray-50 p-1 md:flex">
                {doc && (
                  <button
                    onClick={() => setSelectedArtifact(selectedArtifact === 'doc' ? null : 'doc')}
                    className={`rounded px-2 py-1 text-xs ${
                      selectedArtifact === 'doc' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'
                    }`}
                  >
                    文稿
                  </button>
                )}
                {slides && (
                  <button
                    onClick={() => setSelectedArtifact(selectedArtifact === 'slides' ? null : 'slides')}
                    className={`rounded px-2 py-1 text-xs ${
                      selectedArtifact === 'slides' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'
                    }`}
                  >
                    PPT
                  </button>
                )}
                {canvas && (
                  <button
                    onClick={() => setSelectedArtifact(selectedArtifact === 'canvas' ? null : 'canvas')}
                    className={`rounded px-2 py-1 text-xs ${
                      selectedArtifact === 'canvas' ? 'bg-gray-900 text-white' : 'text-gray-600 hover:bg-white'
                    }`}
                  >
                    画布
                  </button>
                )}
              </div>
            )}

            {sessionId && (
              <>
                <button
                  onClick={copySyncLink}
                  className="rounded-md border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
                >
                  {shareCopied ? '已复制' : '复制链接'}
                </button>
                <div className="relative">
                  <button
                    aria-expanded={qrOpen}
                    onClick={openSyncQr}
                    className="rounded-md border border-gray-200 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
                  >
                    二维码
                  </button>
                  {qrOpen && (
                    <div className="absolute right-0 top-full z-40 mt-2 w-64 rounded-md border border-gray-200 bg-white p-3 shadow-xl">
                      <div className="mb-2 flex items-center justify-between">
                        <p className="text-sm font-medium text-gray-900">扫描二维码</p>
                        <button
                          onClick={() => setQrOpen(false)}
                          className="flex h-7 w-7 items-center justify-center rounded-md text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                        >
                          ×
                        </button>
                      </div>
                      <div className="flex min-h-[200px] items-center justify-center rounded-md bg-white p-2 text-gray-900">
                        {syncUrlLoading ? (
                          <span className="text-xs text-gray-400">生成中...</span>
                        ) : syncUrlError ? (
                          <span className="text-xs text-red-500">{syncUrlError}</span>
                        ) : (
                          <SyncQRCode className="text-gray-900" value={syncUrl} />
                        )}
                      </div>
                      <p className="mt-2 break-all rounded bg-gray-50 px-2 py-1 text-[11px] leading-4 text-gray-500">
                        {syncUrl || '同步链接'}
                      </p>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <main className="flex min-w-0 flex-1 flex-col">
            <div className="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col px-4">
              {hasArtifacts && (
                <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm">
                  <span className="mr-1 text-xs font-medium text-gray-500">已生成产物</span>
                  {doc && (
                    <button
                      onClick={() => setSelectedArtifact('doc')}
                      className={`rounded-full px-3 py-1.5 text-xs ${
                        selectedArtifact === 'doc' ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      文稿
                    </button>
                  )}
                  {slides && (
                    <button
                      onClick={() => setSelectedArtifact('slides')}
                      className={`rounded-full px-3 py-1.5 text-xs ${
                        selectedArtifact === 'slides' ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      PPT
                    </button>
                  )}
                  {canvas && (
                    <button
                      onClick={() => setSelectedArtifact('canvas')}
                      className={`rounded-full px-3 py-1.5 text-xs ${
                        selectedArtifact === 'canvas' ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      画布
                    </button>
                  )}
                </div>
              )}

              <VoiceTranscriber />

              {hasArtifacts && (
                <div className="mb-4 flex flex-wrap gap-2 border-t border-gray-200 pt-3 md:hidden">
                  {doc && (
                    <button
                      onClick={() => setSelectedArtifact(selectedArtifact === 'doc' ? null : 'doc')}
                      className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700"
                    >
                      查看文稿
                    </button>
                  )}
                  {slides && (
                    <button
                      onClick={() => setSelectedArtifact(selectedArtifact === 'slides' ? null : 'slides')}
                      className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700"
                    >
                      查看 PPT
                    </button>
                  )}
                  {canvas && (
                    <button
                      onClick={() => setSelectedArtifact(selectedArtifact === 'canvas' ? null : 'canvas')}
                      className="rounded-full border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700"
                    >
                      查看画布
                    </button>
                  )}
                </div>
              )}
            </div>
          </main>

          {selectedArtifact && (
            <aside
              className={`fixed inset-y-0 right-0 z-30 flex w-full flex-col border-l border-gray-200 bg-white shadow-2xl xl:static xl:z-auto xl:flex-none xl:shadow-none ${
                selectedArtifact === 'canvas' ? 'md:w-[720px] 2xl:w-[860px]' : 'md:w-[520px]'
              }`}
            >
              <div className="flex h-14 items-center justify-between border-b border-gray-200 px-4">
                <div>
                  <p className="text-sm font-semibold text-gray-900">
                    {selectedArtifact === 'doc' ? '文稿预览' : selectedArtifact === 'slides' ? 'PPT 预览' : '画布预览'}
                  </p>
                  <p className="text-xs text-gray-500">点击顶部产物按钮可切换或关闭</p>
                </div>
                <button
                  onClick={() => setSelectedArtifact(null)}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100"
                >
                  ×
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">{renderArtifactPanel()}</div>
            </aside>
          )}
        </div>
      </section>
    </div>
  )
}
