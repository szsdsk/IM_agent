import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { wsService } from '../services/websocket'
import { useSessionStore } from '../store/useSessionStore'
import type { PresentationScene } from '../types'

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
  return (
    /第\s*[0-9一二两三四五六七八九十百]+\s*[页張张]/i.test(content) ||
    /(?:slide|page|p)\s*#?\s*[0-9]+/i.test(content)
  )
}

function isNewGenerationRequest(content: string): boolean {
  const text = content.toLowerCase()
  const createMarkers = ['生成', '创建', '制作', '做一个', '做一份', '新建', '写一个', '来一个', 'create', 'generate', 'make']
  const artifactMarkers = ['ppt', '演示', '幻灯片', 'deck', 'slides', '文档', '报告', '画布', '流程图']
  const revisionMarkers = ['修改', '调整', '优化', '替换', '删掉', '删除', '补充', '改成', '更详细', '丰富', '具体一点']
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
        // 新任务需要清空上一轮产物和进度，避免看起来像从旧流程中途继续。
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
    <section className="flex h-[600px] flex-col rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold text-gray-800">消息</h2>

      <div className="mb-3 flex-1 overflow-y-auto rounded-md border bg-gray-50 p-3 text-sm text-gray-700">
        {messages.length === 0 ? (
          <p className="text-gray-400">输入文字或录一段语音开始任务。</p>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={`mb-2 rounded px-3 py-2 ${
                m.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white text-gray-700'
              }`}
            >
              {m.content}
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      <label className="mb-1 text-xs font-medium text-gray-500">场景</label>
      <select
        value={presentationScene}
        onChange={(e) => setPresentationScene(e.target.value as PresentationScene)}
        disabled={sending || status === 'running'}
        className="mb-2 rounded-md border px-3 py-2 text-sm text-gray-800 disabled:bg-gray-50"
      >
        {sceneOptions.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            sendDraft()
          }
        }}
        placeholder={transcribing ? '正在转写语音...' : '输入需求，或先录音转成文字'}
        disabled={sending || transcribing}
        className="h-24 w-full resize-none rounded-md border px-3 py-2 text-sm disabled:bg-gray-50"
      />

      <div className="mt-2 flex gap-2">
        <button
          onClick={handleRecord}
          disabled={transcribing || sending}
          className={`rounded-md px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-gray-300 ${
            recording ? 'bg-red-600' : 'bg-gray-700'
          }`}
        >
          {recording ? '停止录音' : transcribing ? '转写中...' : '语音'}
        </button>
        <button
          onClick={sendDraft}
          disabled={!draft.trim() || sending || transcribing || status === 'running'}
          className="flex-1 rounded-md bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-gray-300"
        >
          {sending ? '发送中...' : '发送'}
        </button>
      </div>
    </section>
  )
}
