import { useEffect, useRef, useState, type MouseEvent, type WheelEvent } from 'react'

import { api } from '../services/api'
import { useSessionStore } from '../store/useSessionStore'
import type { CanvasArtifact } from '../types'

type ArtifactKind = 'doc' | 'slides' | 'canvas'

interface CanvasViewerProps {
  className?: string
  onOpenArtifact?: (artifact: ArtifactKind) => void
}

interface CanvasPoint {
  x: number
  y: number
}

interface CanvasStyle {
  fill?: string
  stroke?: string
  text?: string
  accent?: string
}

interface CanvasNodeElement {
  type: 'node'
  id: string
  text: string
  kind?: string
  artifact_type?: ArtifactKind | null
  description?: string
  x: number
  y: number
  width: number
  height: number
  style?: CanvasStyle
}

interface CanvasEdgeElement {
  type: 'edge'
  id: string
  source: string
  target: string
  label?: string
  points?: CanvasPoint[]
}

interface CanvasGroupElement {
  type: 'group'
  id: string
  label?: string
  x: number
  y: number
  width: number
  height: number
  style?: CanvasStyle
}

interface CanvasViewport {
  x: number
  y: number
  width: number
  height: number
}

interface NodeDragState {
  id: string
  startClientX: number
  startClientY: number
  originalX: number
  originalY: number
}

const DEFAULT_NODE_STYLE: CanvasStyle = {
  fill: '#FFFFFF',
  stroke: '#CBD5E1',
  text: '#1E293B',
  accent: '#3B82F6',
}

function normalizeText(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function detectArtifactKind(node: Record<string, any>): ArtifactKind | null {
  const explicit = normalizeText(node.artifact_type)
  if (explicit === 'doc' || explicit === 'slides' || explicit === 'canvas') return explicit

  const haystack = [node.type, node.kind, node.text, node.label, node.name, node.title, node.id]
    .map(normalizeText)
    .join(' ')

  if (/(文稿|文档|doc|document|prd|report|generate_doc)/.test(haystack)) return 'doc'
  if (/(ppt|slides|slide|deck|演示|幻灯片|generate_slides)/.test(haystack)) return 'slides'
  if (/(画布|canvas|whiteboard|白板|generate_canvas)/.test(haystack)) return 'canvas'
  return null
}

function artifactLabel(kind: ArtifactKind): string {
  if (kind === 'doc') return '文档'
  if (kind === 'slides') return 'PPT'
  return '画布'
}

function artifactActionLabel(kind: ArtifactKind): string {
  return kind === 'canvas' ? '重置画布视图' : `打开${artifactLabel(kind)}`
}

function providerLabel(provider?: string): string {
  if (provider === 'affine') return 'AFFiNE 画布'
  if (provider === 'local_canvas') return '本地交互画布'
  return '本地画布'
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function safeFileName(value: string, ext: string): string {
  const base = value.replace(/[\\/:*?"<>|]/g, '_').trim() || 'agent-pilot-canvas'
  return `${base}.${ext}`
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function splitText(text: string, maxChars = 13, maxLines = 3): string[] {
  const chars = Array.from(text || '')
  const lines: string[] = []
  for (let index = 0; index < chars.length && lines.length < maxLines; index += maxChars) {
    lines.push(chars.slice(index, index + maxChars).join(''))
  }
  if (chars.length > maxChars * maxLines && lines.length) {
    lines[lines.length - 1] = `${lines[lines.length - 1].slice(0, -1)}…`
  }
  return lines.length ? lines : ['未命名节点']
}

function normalizeNode(raw: Record<string, any>, index: number): CanvasNodeElement {
  const artifactType = detectArtifactKind(raw)
  return {
    type: 'node',
    id: String(raw.id || `n${index + 1}`),
    text: String(raw.text || raw.label || raw.title || raw.id || `节点 ${index + 1}`),
    kind: String(raw.kind || raw.type || 'process'),
    artifact_type: artifactType,
    description: String(raw.description || raw.summary || ''),
    x: Number(raw.x ?? 80 + index * 260),
    y: Number(raw.y ?? 120),
    width: Number(raw.width ?? 220),
    height: Number(raw.height ?? 88),
    style: raw.style || DEFAULT_NODE_STYLE,
  }
}

function normalizeEdge(raw: Record<string, any>, index: number): CanvasEdgeElement {
  return {
    type: 'edge',
    id: String(raw.id || `e${index + 1}`),
    source: String(raw.source || raw.from || ''),
    target: String(raw.target || raw.to || ''),
    label: String(raw.label || ''),
    points: Array.isArray(raw.points) ? raw.points : undefined,
  }
}

function fallbackFromLegacyCanvas(canvas: CanvasArtifact): {
  groups: CanvasGroupElement[]
  nodes: CanvasNodeElement[]
  edges: CanvasEdgeElement[]
} {
  const legacyNodes = canvas.nodes || []
  const legacyEdges = canvas.edges || []
  const groups: CanvasGroupElement[] = []

  let nodes = legacyNodes.map((node, index) => normalizeNode(node, index))
  if (!nodes.length && canvas.layers?.length) {
    nodes = canvas.layers.flatMap((layer, row) =>
      layer.map((label, col) => normalizeNode({
        id: `l${row + 1}_${col + 1}`,
        text: label,
        x: 112 + col * 292,
        y: 104 + row * 132,
      }, row * 10 + col)),
    )
    canvas.layers.forEach((layer, index) => {
      groups.push({
        type: 'group',
        id: `layer_${index + 1}`,
        label: `Layer ${index + 1}`,
        x: 56,
        y: 76 + index * 132,
        width: Math.max(layer.length * 292 + 88, 900),
        height: 104,
        style: { fill: '#F8FAFC', stroke: '#E2E8F0', text: '#64748B' },
      })
    })
  }

  const edges = legacyEdges.map((edge, index) => normalizeEdge(edge, index))
  return { groups, nodes, edges }
}

function normalizeCanvasElements(canvas: CanvasArtifact): {
  groups: CanvasGroupElement[]
  nodes: CanvasNodeElement[]
  edges: CanvasEdgeElement[]
} {
  const rawElements = canvas.elements || []
  const groups = rawElements
    .filter((element) => element.type === 'group')
    .map((element) => element as CanvasGroupElement)
  const nodes = rawElements
    .filter((element) => element.type === 'node')
    .map((element, index) => normalizeNode(element, index))
  const edges = rawElements
    .filter((element) => element.type === 'edge')
    .map((element, index) => normalizeEdge(element, index))

  if (nodes.length) return { groups, nodes, edges }
  return fallbackFromLegacyCanvas(canvas)
}

function edgePath(edge: CanvasEdgeElement, nodeMap: Map<string, CanvasNodeElement>): string {
  const points = edge.points?.length
    ? edge.points
    : (() => {
        const source = nodeMap.get(edge.source)
        const target = nodeMap.get(edge.target)
        if (!source || !target) return []
        const start = { x: source.x + source.width, y: source.y + source.height / 2 }
        const end = { x: target.x, y: target.y + target.height / 2 }
        const midX = (start.x + end.x) / 2
        return [start, { x: midX, y: start.y }, { x: midX, y: end.y }, end]
      })()

  if (points.length < 2) return ''
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`).join(' ')
}

function edgeLabelPosition(edge: CanvasEdgeElement, nodeMap: Map<string, CanvasNodeElement>): CanvasPoint | null {
  const source = nodeMap.get(edge.source)
  const target = nodeMap.get(edge.target)
  if (!source || !target) return null
  return {
    x: (source.x + source.width + target.x) / 2,
    y: (source.y + target.y) / 2 + 18,
  }
}

function getContentViewport(
  groups: CanvasGroupElement[],
  nodes: CanvasNodeElement[],
  edges: CanvasEdgeElement[],
  fallback: CanvasViewport,
): CanvasViewport {
  const xs: number[] = []
  const ys: number[] = []

  const collectBox = (x: number, y: number, width: number, height: number) => {
    if (![x, y, width, height].every(Number.isFinite)) return
    xs.push(x, x + width)
    ys.push(y, y + height)
  }

  groups.forEach((group) => collectBox(group.x, group.y, group.width, group.height))
  nodes.forEach((node) => collectBox(node.x, node.y, node.width, node.height))
  edges.forEach((edge) => {
    edge.points?.forEach((point) => {
      if (Number.isFinite(point.x) && Number.isFinite(point.y)) {
        xs.push(point.x)
        ys.push(point.y)
      }
    })
  })

  if (!xs.length || !ys.length) return fallback

  const padding = 96
  const minX = Math.min(...xs) - padding
  const minY = Math.min(...ys) - padding
  const maxX = Math.max(...xs) + padding
  const maxY = Math.max(...ys) + padding

  return {
    x: minX,
    y: minY,
    width: Math.max(maxX - minX, 560),
    height: Math.max(maxY - minY, 380),
  }
}

function selectedRelations(node: CanvasNodeElement, edges: CanvasEdgeElement[]): string {
  const incoming = edges.filter((edge) => edge.target === node.id).map((edge) => edge.source)
  const outgoing = edges.filter((edge) => edge.source === node.id).map((edge) => edge.target)
  const parts = []
  if (incoming.length) parts.push(`上游：${incoming.join('、')}`)
  if (outgoing.length) parts.push(`下游：${outgoing.join('、')}`)
  return parts.join('；') || '暂无上下游关系'
}

function rebuildCanvasArtifact(
  canvas: CanvasArtifact,
  groups: CanvasGroupElement[],
  nodes: CanvasNodeElement[],
  edges: CanvasEdgeElement[],
): CanvasArtifact {
  return {
    ...canvas,
    nodes: nodes.map(({ type: _type, ...node }) => ({ ...node })),
    edges: edges.map(({ type: _type, ...edge }) => ({ ...edge })),
    elements: [
      ...groups.map((group) => ({ ...group })),
      ...nodes.map((node) => ({ ...node, type: 'node' as const })),
      ...edges.map((edge) => ({ ...edge, type: 'edge' as const })),
    ],
    metadata: {
      ...(canvas.metadata || {}),
      edited_locally: true,
      edited_at: new Date().toISOString(),
    },
  }
}

export default function CanvasViewer({ className = '', onOpenArtifact }: CanvasViewerProps) {
  const canvas = useSessionStore((state) => state.canvas)
  const doc = useSessionStore((state) => state.doc)
  const slides = useSessionStore((state) => state.slides)
  const task = useSessionStore((state) => state.task)
  const clientId = useSessionStore((state) => state.clientId)
  const deviceType = useSessionStore((state) => state.deviceType)
  const setCanvas = useSessionStore((state) => state.setCanvas)
  const setSlides = useSessionStore((state) => state.setSlides)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [dragStart, setDragStart] = useState<{ x: number; y: number; panX: number; panY: number } | null>(null)
  const [nodeDragStart, setNodeDragStart] = useState<NodeDragState | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draftCanvas, setDraftCanvas] = useState<CanvasArtifact | null>(canvas)
  const [isDirty, setIsDirty] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [pptSyncStatus, setPptSyncStatus] = useState<'idle' | 'syncing' | 'synced' | 'error'>('idle')

  useEffect(() => {
    setDraftCanvas(canvas)
    setIsDirty(false)
    setSaveStatus('idle')
    setPptSyncStatus('idle')
  }, [canvas?.canvas_id, canvas?.metadata?.version])

  if (!canvas) {
    return (
      <div className={`rounded-lg border bg-white p-6 shadow-sm ${className}`}>
        <h3 className="mb-4 font-medium text-gray-800">画布预览</h3>
        <div className="flex h-40 items-center justify-center text-sm text-gray-400">
          暂无画布内容
        </div>
      </div>
    )
  }

  const currentCanvas = draftCanvas || canvas
  const { groups, nodes, edges } = normalizeCanvasElements(currentCanvas)
  const nodeMap = new Map(nodes.map((node) => [node.id, node]))
  const selectedNode = nodes.find((node) => node.id === selectedId) || nodes[0]
  const backendViewport = currentCanvas.viewport || { x: 0, y: 0, width: 960, height: 520 }
  const viewport = getContentViewport(groups, nodes, edges, backendViewport)
  const markerId = `canvas_arrow_${String(currentCanvas.canvas_id || 'local').replace(/[^a-zA-Z0-9_-]/g, '_')}`

  function isArtifactAvailable(kind: ArtifactKind): boolean {
    if (kind === 'doc') return Boolean(doc)
    if (kind === 'slides') return Boolean(slides)
    return Boolean(currentCanvas)
  }

  function updateDraftNodes(nextNodes: CanvasNodeElement[]) {
    setDraftCanvas(rebuildCanvasArtifact(currentCanvas, groups, nextNodes, edges))
    setIsDirty(true)
    setSaveStatus('idle')
  }

  function updateSelectedNode(patch: Partial<CanvasNodeElement>) {
    if (!selectedNode) return
    updateDraftNodes(nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)))
  }

  function handleNodeMouseDown(node: CanvasNodeElement, event: MouseEvent) {
    event.stopPropagation()
    setSelectedId(node.id)
    setNodeDragStart({
      id: node.id,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originalX: node.x,
      originalY: node.y,
    })
  }

  function handleNodeClick(node: CanvasNodeElement, event: MouseEvent) {
    event.stopPropagation()
    setSelectedId(node.id)
  }

  function handleWheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault()
    const direction = event.deltaY > 0 ? 0.9 : 1.1
    setZoom((current) => clamp(Number((current * direction).toFixed(2)), 0.35, 2.4))
  }

  function handleMouseDown(event: MouseEvent<SVGSVGElement>) {
    const target = event.target as Element
    if (target.closest?.('[data-node-id]')) return
    setDragStart({ x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y })
  }

  function handleMouseMove(event: MouseEvent<SVGSVGElement>) {
    if (nodeDragStart) {
      const rect = svgRef.current?.getBoundingClientRect()
      const scaleX = rect?.width ? viewport.width / rect.width : 1
      const scaleY = rect?.height ? viewport.height / rect.height : 1
      const dx = ((event.clientX - nodeDragStart.startClientX) * scaleX) / zoom
      const dy = ((event.clientY - nodeDragStart.startClientY) * scaleY) / zoom
      updateDraftNodes(nodes.map((node) => (
        node.id === nodeDragStart.id
          ? { ...node, x: Math.round(nodeDragStart.originalX + dx), y: Math.round(nodeDragStart.originalY + dy) }
          : node
      )))
      return
    }
    if (!dragStart) return
    setPan({
      x: dragStart.panX + event.clientX - dragStart.x,
      y: dragStart.panY + event.clientY - dragStart.y,
    })
  }

  function resetView() {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }

  async function saveCanvasEdits() {
    if (!task?.id || !currentCanvas) return
    setSaveStatus('saving')
    try {
      const response = await api.updateCanvas(task.id, currentCanvas, clientId, deviceType)
      setCanvas(response.canvas)
      setDraftCanvas(response.canvas)
      setIsDirty(false)
      setSaveStatus('saved')
    } catch (error) {
      console.error('Failed to save canvas:', error)
      setSaveStatus('error')
    }
  }

  async function applyCanvasToSlides() {
    if (!task?.id || !currentCanvas || !slides) return
    setPptSyncStatus('syncing')
    try {
      const response = await api.applyCanvasToSlides(task.id, currentCanvas, clientId, deviceType)
      setCanvas(response.canvas)
      setDraftCanvas(response.canvas)
      setSlides(response.slides)
      setIsDirty(false)
      setSaveStatus('saved')
      setPptSyncStatus('synced')
    } catch (error) {
      console.error('Failed to sync canvas to PPT:', error)
      setPptSyncStatus('error')
    }
  }

  function revertCanvasEdits() {
    setDraftCanvas(canvas)
    setIsDirty(false)
    setSaveStatus('idle')
  }

  function serializedSvg(): string | null {
    if (!svgRef.current) return null
    const clone = svgRef.current.cloneNode(true) as SVGSVGElement
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    clone.setAttribute('width', String(viewport.width))
    clone.setAttribute('height', String(viewport.height))
    return new XMLSerializer().serializeToString(clone)
  }

  function exportJson() {
    downloadBlob(
      new Blob([JSON.stringify(currentCanvas, null, 2)], { type: 'application/json;charset=utf-8' }),
      safeFileName(currentCanvas.title || 'agent-pilot-canvas', 'json'),
    )
  }

  function exportSvg() {
    const source = serializedSvg()
    if (!source) return
    downloadBlob(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }), safeFileName(currentCanvas.title || 'agent-pilot-canvas', 'svg'))
  }

  function exportPng() {
    const source = serializedSvg()
    if (!source) return
    const image = new Image()
    const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml;charset=utf-8' }))
    image.onload = () => {
      const bitmapCanvas = document.createElement('canvas')
      bitmapCanvas.width = Math.round(viewport.width)
      bitmapCanvas.height = Math.round(viewport.height)
      const context = bitmapCanvas.getContext('2d')
      if (!context) return
      context.fillStyle = '#F8FAFC'
      context.fillRect(0, 0, bitmapCanvas.width, bitmapCanvas.height)
      context.drawImage(image, 0, 0)
      bitmapCanvas.toBlob((blob) => {
        if (blob) downloadBlob(blob, safeFileName(currentCanvas.title || 'agent-pilot-canvas', 'png'))
        URL.revokeObjectURL(url)
      }, 'image/png')
    }
    image.src = url
  }

  return (
    <div className={`overflow-hidden rounded-lg border bg-white shadow-sm ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-gray-50 px-4 py-3">
        <div>
          <h3 className="font-medium text-gray-800">画布预览</h3>
          <p className="mt-1 text-xs text-gray-500">
            {providerLabel(currentCanvas.provider)} · {currentCanvas.diagram_type || 'flow'} · {nodes.length} 个节点
            {isDirty ? ' · 有未保存修改' : ''}
            {saveStatus === 'saved' ? ' · 已保存' : ''}
            {saveStatus === 'error' ? ' · 保存失败' : ''}
            {pptSyncStatus === 'synced' ? ' · 已同步到 PPT' : ''}
            {pptSyncStatus === 'error' ? ' · PPT 同步失败' : ''}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={saveCanvasEdits}
            disabled={!isDirty || !task?.id || saveStatus === 'saving'}
            className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {saveStatus === 'saving' ? '保存中...' : '保存修改'}
          </button>
          <button
            type="button"
            onClick={applyCanvasToSlides}
            disabled={!task?.id || !slides || pptSyncStatus === 'syncing'}
            className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-gray-300"
          >
            {pptSyncStatus === 'syncing' ? '同步中...' : '同步到 PPT'}
          </button>
          <button
            type="button"
            onClick={revertCanvasEdits}
            disabled={!isDirty}
            className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            撤销修改
          </button>
          <button type="button" onClick={resetView} className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white">
            适配视图
          </button>
          <button type="button" onClick={exportSvg} className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white">
            导出 SVG
          </button>
          <button type="button" onClick={exportPng} className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white">
            导出 PNG
          </button>
          <button type="button" onClick={exportJson} className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white">
            导出 JSON
          </button>
          {currentCanvas.url && (
            <a
              href={currentCanvas.url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
            >
              打开外部画布
            </a>
          )}
        </div>
      </div>

      <div className="flex flex-col">
        <div className="relative min-h-[360px] bg-slate-50">
          <svg
            ref={svgRef}
            className="h-[360px] w-full cursor-grab touch-none select-none active:cursor-grabbing sm:h-[420px] 2xl:h-[520px]"
            viewBox={`${viewport.x} ${viewport.y} ${viewport.width} ${viewport.height}`}
            onWheel={handleWheel}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={() => {
              setDragStart(null)
              setNodeDragStart(null)
            }}
            onMouseLeave={() => {
              setDragStart(null)
              setNodeDragStart(null)
            }}
            onClick={() => setSelectedId(null)}
          >
            <defs>
              <pattern id="canvas_grid" width="28" height="28" patternUnits="userSpaceOnUse">
                <path d="M 28 0 L 0 0 0 28" fill="none" stroke="#E2E8F0" strokeWidth="1" />
              </pattern>
              <marker id={markerId} markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
                <path d="M0,0 L0,6 L9,3 z" fill="#64748B" />
              </marker>
            </defs>
            <rect x={viewport.x} y={viewport.y} width={viewport.width} height={viewport.height} fill="url(#canvas_grid)" />
            <g transform={`translate(${pan.x} ${pan.y}) scale(${zoom})`}>
              {groups.map((group) => (
                <g key={group.id}>
                  <rect
                    x={group.x}
                    y={group.y}
                    width={group.width}
                    height={group.height}
                    rx="18"
                    fill={group.style?.fill || '#F8FAFC'}
                    stroke={group.style?.stroke || '#E2E8F0'}
                    strokeDasharray="8 8"
                  />
                  {group.label && (
                    <text x={group.x + 18} y={group.y + 28} fill={group.style?.text || '#64748B'} fontSize="13" fontWeight="600">
                      {group.label}
                    </text>
                  )}
                </g>
              ))}

              {edges.map((edge) => {
                const path = edgePath(edge, nodeMap)
                const labelPosition = edgeLabelPosition(edge, nodeMap)
                if (!path) return null
                return (
                  <g key={edge.id}>
                    <path d={path} fill="none" stroke="#64748B" strokeWidth="2.2" markerEnd={`url(#${markerId})`} />
                    {edge.label && labelPosition && (
                      <g>
                        <rect
                          x={labelPosition.x - edge.label.length * 6}
                          y={labelPosition.y - 15}
                          width={edge.label.length * 12 + 16}
                          height="24"
                          rx="12"
                          fill="#FFFFFF"
                          stroke="#E2E8F0"
                        />
                        <text x={labelPosition.x} y={labelPosition.y + 2} textAnchor="middle" fill="#475569" fontSize="12">
                          {edge.label}
                        </text>
                      </g>
                    )}
                  </g>
                )
              })}

              {nodes.map((node) => {
                const style = node.style || DEFAULT_NODE_STYLE
                const selected = selectedId === node.id
                const lines = splitText(node.text)
                return (
                  <g
                    key={node.id}
                    data-node-id={node.id}
                    role="button"
                    tabIndex={0}
                    onMouseDown={(event) => handleNodeMouseDown(node, event)}
                    onClick={(event) => handleNodeClick(node, event)}
                    className="cursor-pointer"
                  >
                    <rect
                      x={node.x}
                      y={node.y}
                      width={node.width}
                      height={node.height}
                      rx="18"
                      fill={style.fill || DEFAULT_NODE_STYLE.fill}
                      stroke={selected ? '#2563EB' : style.stroke || DEFAULT_NODE_STYLE.stroke}
                      strokeWidth={selected ? 3 : 2}
                      filter={selected ? 'drop-shadow(0px 8px 16px rgba(37, 99, 235, 0.18))' : undefined}
                    />
                    <circle cx={node.x + 26} cy={node.y + 25} r="8" fill={style.accent || DEFAULT_NODE_STYLE.accent} />
                    <text x={node.x + 44} y={node.y + 29} fill={style.text || DEFAULT_NODE_STYLE.text} fontSize="12" fontWeight="700">
                      {node.kind || 'process'}
                    </text>
                    {node.artifact_type && (
                      <text x={node.x + node.width - 18} y={node.y + 29} textAnchor="end" fill={style.accent || DEFAULT_NODE_STYLE.accent} fontSize="12" fontWeight="700">
                        {artifactLabel(node.artifact_type)}
                      </text>
                    )}
                    <text x={node.x + 20} y={node.y + 54} fill={style.text || DEFAULT_NODE_STYLE.text} fontSize="15" fontWeight="700">
                      {lines.map((line, index) => (
                        <tspan key={`${node.id}_${index}`} x={node.x + 20} dy={index === 0 ? 0 : 18}>
                          {line}
                        </tspan>
                      ))}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>
          <div className="absolute bottom-3 left-4 rounded-full bg-white/90 px-3 py-1 text-xs text-slate-500 shadow-sm">
            缩放 {Math.round(zoom * 100)}% · 拖拽节点编辑布局，拖拽空白处移动画布
          </div>
        </div>

        <aside className="border-t bg-white p-4">
          <h4 className="font-medium text-gray-800">节点详情</h4>
          {selectedNode ? (
            <div className="mt-4 space-y-3 text-sm">
              <div>
                <p className="text-xs text-gray-400">名称</p>
                <input
                  value={selectedNode.text}
                  onChange={(event) => updateSelectedNode({ text: event.target.value })}
                  className="mt-1 w-full rounded border border-gray-200 px-3 py-2 font-medium text-gray-800 outline-none focus:border-blue-400"
                />
              </div>
              <div>
                <p className="text-xs text-gray-400">类型</p>
                <input
                  value={selectedNode.kind || 'process'}
                  onChange={(event) => updateSelectedNode({ kind: event.target.value })}
                  className="mt-1 w-full rounded border border-gray-200 px-3 py-2 text-gray-700 outline-none focus:border-blue-400"
                />
              </div>
              <div>
                <p className="text-xs text-gray-400">说明</p>
                <textarea
                  value={selectedNode.description || ''}
                  onChange={(event) => updateSelectedNode({ description: event.target.value })}
                  rows={3}
                  className="mt-1 w-full resize-none rounded border border-gray-200 px-3 py-2 text-gray-700 outline-none focus:border-blue-400"
                  placeholder="补充这个节点的职责、输入输出或注意事项"
                />
              </div>
              {selectedNode.artifact_type && (
                <button
                  type="button"
                  onClick={() => {
                    if (selectedNode.artifact_type === 'canvas') {
                      resetView()
                      return
                    }
                    onOpenArtifact?.(selectedNode.artifact_type as ArtifactKind)
                  }}
                  disabled={selectedNode.artifact_type !== 'canvas' && !isArtifactAvailable(selectedNode.artifact_type)}
                  className="w-full rounded bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                >
                  {artifactActionLabel(selectedNode.artifact_type)}
                </button>
              )}
              <div>
                <p className="text-xs text-gray-400">关系</p>
                <p className="mt-1 text-gray-700">{selectedRelations(selectedNode, edges)}</p>
              </div>
              <div>
                <p className="text-xs text-gray-400">同步状态</p>
                <p className="mt-1 text-gray-700">{String(currentCanvas.metadata?.sync_status || 'local_only')}</p>
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-gray-500">点击任意节点查看详情，点击文档 / PPT 节点可联动打开对应产物。</p>
          )}
        </aside>
      </div>
    </div>
  )
}
