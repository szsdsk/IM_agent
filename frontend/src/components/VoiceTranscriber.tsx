import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { wsService } from '../services/websocket'
import { useSessionStore } from '../store/useSessionStore'
import type { Message, PresentationScene } from '../types'

const STEP_LABELS: Record<string, string> = {
  receive_input: 'Pilot Agent：已接收 IM 指令',
  parse_intent: 'Pilot Agent：正在理解用户意图',
  plan_workflow: 'Planner Agent：正在拆解任务并编排流程',
  extract_tasks: 'Planner Agent：正在生成可执行任务清单',
  generate_doc: 'Doc Agent：正在生成发布评审文档',
  generate_canvas: 'Canvas Agent：正在生成流程图画布',
  generate_slides: 'Deck Agent：正在生成管理层汇报 PPT',
  generate_rehearsal: 'Rehearsal Agent：正在准备讲稿与 Q&A',
  prepare_delivery: 'Delivery Agent：正在归档并准备回传飞书',
  confirm_or_modify: 'Pilot Agent：等待确认或修改意见',
  deliver_result: 'Delivery Agent：正在交付结果',
}

const sceneOptions: Array<{ value: PresentationScene; label: string }> = [
  { value: 'management_briefing', label: '管理层汇报' },
  { value: 'project_review', label: '项目评审' },
  { value: 'proposal_pitch', label: '方案提案' },
  { value: 'postmortem', label: '复盘总结' },
  { value: 'training', label: '培训讲解' },
]

const QUEUE_KEY = 'agent-pilot-pending-messages'

interface PendingMessage {
  content: string
  presentationScene: PresentationScene
  feedbackTaskId?: string
  createdAt: string
}

function isFeedbackLike(content: string): boolean {
  const text = content.toLowerCase()
  if (isNewGenerationRequest(text)) return false

  return hasSlideReference(text) || [
    '改',
    '修改',
    '调整',
    '优化',
    '替换',
    '删除',
    '增加',
    '补充',
    '更详细',
    '丰富',
    '具体一点',
    '换成',
    '排练',
    '演练',
    '讲稿',
    'q&a',
    'qa',
    '问答',
  ].some((marker) => text.includes(marker))
}

function hasSlideReference(content: string): boolean {
  return /第\s*[0-9一二两三四五六七八九十百]+\s*[页张]/i.test(content) || /(?:slide|page|p)\s*#?\s*[0-9]+/i.test(content)
}

function isNewGenerationRequest(content: string): boolean {
  const text = content.toLowerCase()
  const createMarkers = ['生成', '创建', '制作', '做一个', '做一份', '新建', '写一个', '来一个', 'create', 'generate', 'make']
  const artifactMarkers = ['ppt', '演示', '幻灯片', 'deck', 'slides', '文档', '报告', '画布', '流程图']
  const revisionMarkers = ['修改', '调整', '优化', '替换', '删除', '补充', '改成', '更详细', '丰富', '具体一点']
  return (
    createMarkers.some((marker) => text.includes(marker)) &&
    artifactMarkers.some((marker) => text.includes(marker)) &&
    !hasSlideReference(text) &&
    !revisionMarkers.some((marker) => text.includes(marker))
  )
}

function loadPendingMessages(): PendingMessage[] {
  try {
    const raw = window.localStorage.getItem(QUEUE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function savePendingMessages(messages: PendingMessage[]): void {
  window.localStorage.setItem(QUEUE_KEY, JSON.stringify(messages))
}

function mixToMono(buffer: AudioBuffer): Float32Array<ArrayBufferLike> {
  if (buffer.numberOfChannels === 1) return buffer.getChannelData(0)
  const mixed = new Float32Array(buffer.length)
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, i) => buffer.getChannelData(i))
  for (let i = 0; i < buffer.length; i += 1) {
    let sum = 0
    for (let c = 0; c < channels.length; c += 1) sum += channels[c][i]
    mixed[i] = sum / channels.length
  }
  return mixed
}

function encodePcm16(samples: Float32Array<ArrayBufferLike>): Blob {
  const buffer = new ArrayBuffer(samples.length * 2)
  const view = new DataView(buffer)
  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(i * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true)
  }
  return new Blob([buffer], { type: 'audio/pcm' })
}

async function convertToPcm16k(blob: Blob): Promise<Blob> {
  const input = await blob.arrayBuffer()
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(input)
    const mono = mixToMono(decoded)
    const targetRate = 16000
    const targetLength = Math.round((mono.length * targetRate) / decoded.sampleRate)
    const offline = new OfflineAudioContext(1, targetLength, targetRate)
    const sourceBuffer = offline.createBuffer(1, mono.length, decoded.sampleRate)
    sourceBuffer.getChannelData(0).set(mono)
    const source = offline.createBufferSource()
    source.buffer = sourceBuffer
    source.connect(offline.destination)
    source.start(0)
    const rendered = await offline.startRendering()
    return encodePcm16(rendered.getChannelData(0))
  } finally {
    await context.close()
  }
}

function messageTime(message: Message): string {
  // 后端历史消息来自 UTC，但旧 SQLite 记录可能没有 Z 后缀；这里补齐时区避免显示少 8 小时。
  const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(message.timestamp) ? message.timestamp : `${message.timestamp}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function renderProgressLabel(step: string): string {
  if (!step) return '处理中'
  return STEP_LABELS[step] || step
}

export default function VoiceTranscriber() {
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [sending, setSending] = useState(false)
  const [draft, setDraft] = useState('')
  const [presentationScene, setPresentationScene] = useState<PresentationScene>('management_briefing')
  const [error, setError] = useState('')
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  const {
    messages,
    sessionId,
    clientId,
    deviceType,
    task,
    status,
    currentStep,
    progressMessage,
    progress,
    setSessionId,
    setTask,
    setStatus,
    setCurrentStep,
    setProgress,
    setDoc,
    setSlides,
    setCanvas,
    addMessage,
  } = useSessionStore()

  const stopTracks = () => {
    recorderRef.current?.stream.getTracks().forEach((t) => t.stop())
    streamRef.current?.getTracks().forEach((t) => t.stop())
    recorderRef.current = null
    streamRef.current = null
  }

  const ensureSession = async () => {
    if (sessionId) return sessionId
    const session = await api.createSession()
    setSessionId(session.id)
    wsService.connect(session.id)
    return session.id
  }

  const sendDraft = async () => {
    const content = draft.trim()
    if (!content || sending || status === 'running') return

    setError('')
    setSending(true)
    setDraft('')
    try {
      const feedbackTaskId = task?.id && isFeedbackLike(content) ? task.id : undefined
      if (feedbackTaskId) {
        setStatus('running')
        setCurrentStep('confirm_or_modify')
        setProgress(0.1)
      } else {
        setTask(null)
        setDoc(null)
        setSlides(null)
        setCanvas(null)
        setStatus('running')
        setCurrentStep('receive_input')
        setProgress(0)
      }
      addMessage({
        id: `user-${Date.now()}`,
        role: 'user',
        content,
        timestamp: new Date().toISOString(),
      })
      if (!navigator.onLine) {
        const pending = loadPendingMessages()
        pending.push({ content, presentationScene, feedbackTaskId, createdAt: new Date().toISOString() })
        savePendingMessages(pending)
        addMessage({
          id: `offline-${Date.now()}`,
          role: 'system',
          content: '当前离线，消息已暂存，恢复网络后会自动发送。',
          timestamp: new Date().toISOString(),
        })
        setStatus('connected')
        return
      }
      const activeSessionId = await ensureSession()
      const nextTask = await api.sendMessage(
        activeSessionId,
        content,
        undefined,
        presentationScene,
        feedbackTaskId,
        clientId,
        deviceType
      )
      setTask(nextTask)
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    } catch (e) {
      setError(e instanceof Error ? e.message : '发送失败')
      setStatus('error')
    } finally {
      setSending(false)
    }
  }

  useEffect(() => {
    const flushPending = async () => {
      if (!navigator.onLine) return
      const pending = loadPendingMessages()
      if (!pending.length) return
      try {
        const activeSessionId = await ensureSession()
        savePendingMessages([])
        for (const item of pending) {
          const nextTask = await api.sendMessage(
            activeSessionId,
            item.content,
            undefined,
            item.presentationScene,
            item.feedbackTaskId,
            clientId,
            deviceType
          )
          setTask(nextTask)
        }
        addMessage({
          id: `online-${Date.now()}`,
          role: 'system',
          content: `已发送 ${pending.length} 条离线暂存消息。`,
          timestamp: new Date().toISOString(),
        })
      } catch (e) {
        savePendingMessages(pending)
        setError(e instanceof Error ? e.message : '离线消息补发失败')
      }
    }

    window.addEventListener('online', flushPending)
    flushPending()
    return () => window.removeEventListener('online', flushPending)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, status])

  const handleRecord = async () => {
    setError('')
    if (recording) {
      recorderRef.current?.stop()
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('当前浏览器不支持录音。')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : ''
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      streamRef.current = stream
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        setRecording(false)
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        chunksRef.current = []
        stopTracks()
        if (!blob.size) {
          setError('没有录到有效音频。')
          return
        }
        setTranscribing(true)
        try {
          const pcmBlob = await convertToPcm16k(blob)
          const result = await api.transcribeVoice(pcmBlob)
          const transcript = (result.text || '').trim()
          if (transcript) setDraft(transcript)
        } catch (e) {
          setError(e instanceof Error ? e.message : '语音转写失败')
        } finally {
          setTranscribing(false)
        }
      }

      recorder.start()
      setRecording(true)
    } catch {
      setError('麦克风权限未开启或不可用。')
      stopTracks()
      setRecording(false)
    }
  }

  return (
    <section className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-6">
        {messages.length === 0 ? (
          <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center text-center">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-gray-900 text-lg font-semibold text-white">
              AI
            </div>
            <h2 className="text-2xl font-semibold text-gray-900">今天要一起完成什么？</h2>
            <p className="mt-2 max-w-md text-sm leading-6 text-gray-500">
              直接描述任务，或者录音转成文字。我会在当前对话里保留短期上下文，继续帮你生成文稿、PPT、画布和后续修改。
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-5">
            {messages.map((message) => {
              const isUser = message.role === 'user'
              return (
                <div key={message.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[82%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
                    <div
                      className={`whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm ${
                        isUser
                          ? 'rounded-br-md bg-gray-900 text-white'
                          : message.role === 'system'
                            ? 'rounded-bl-md border border-gray-200 bg-white text-gray-500'
                            : 'rounded-bl-md border border-gray-200 bg-white text-gray-800'
                      }`}
                    >
                      {message.content}
                    </div>
                    <span className="px-1 text-[11px] text-gray-400">{messageTime(message)}</span>
                  </div>
                </div>
              )
            })}
            {status === 'running' && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-md border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500 shadow-sm">
                  正在处理...
                </div>
              </div>
            )}
            {(status === 'running' || status === 'completed' || status === 'failed') && (
              <div className="flex justify-start">
                <div className="w-full max-w-[82%] rounded-2xl rounded-bl-md border border-gray-200 bg-white px-4 py-3 shadow-sm">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-gray-800">执行进度</p>
                    <p className="text-xs text-gray-500">
                      {Math.max(0, Math.min(100, Math.round((progress || 0) * 100)))}%
                    </p>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100">
                    <div
                      className={`h-full rounded-full transition-all ${
                        status === 'failed' ? 'bg-red-500' : status === 'completed' ? 'bg-emerald-500' : 'bg-blue-500'
                      }`}
                      style={{ width: `${Math.max(5, Math.min(100, Math.round((progress || 0) * 100)))}%` }}
                    />
                  </div>
                  <p className="mt-2 text-xs text-gray-600">
                    当前执行：{progressMessage || renderProgressLabel(currentStep)}
                  </p>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <div className="flex-none pb-4">
        <div className="mx-auto max-w-3xl rounded-2xl border border-gray-200 bg-white p-3 shadow-lg shadow-gray-200/60">
          {error && <p className="mb-2 rounded-md bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}

          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendDraft()
              }
            }}
            placeholder={transcribing ? '正在转写语音...' : '输入需求，Shift + Enter 换行'}
            disabled={sending || transcribing}
            className="max-h-44 min-h-[72px] w-full resize-none border-0 bg-transparent px-1 py-1 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400 disabled:bg-transparent"
          />

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 pt-2">
            <div className="flex items-center gap-2">
              <select
                value={presentationScene}
                onChange={(e) => setPresentationScene(e.target.value as PresentationScene)}
                disabled={sending || status === 'running'}
                className="h-8 rounded-md border border-gray-200 bg-gray-50 px-2 text-xs text-gray-700 outline-none disabled:opacity-60"
              >
                {sceneOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>

              <button
                onClick={handleRecord}
                disabled={transcribing || sending}
                className={`h-8 rounded-md px-3 text-xs font-medium disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400 ${
                  recording ? 'bg-red-600 text-white' : 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                }`}
              >
                {recording ? '停止录音' : transcribing ? '转写中...' : '语音'}
              </button>
            </div>

            <button
              onClick={sendDraft}
              disabled={!draft.trim() || sending || transcribing || status === 'running'}
              className="h-8 rounded-md bg-gray-900 px-4 text-xs font-medium text-white hover:bg-black disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-400"
            >
              {sending ? '发送中...' : '发送'}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
