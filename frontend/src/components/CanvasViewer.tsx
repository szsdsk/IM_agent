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
  const source = nodeMap.get(edge.source)
  const target = nodeMap.get(edge.target)
  if (!source || !target) return ''

  const sourceCenter = { x: source.x + source.width / 2, y: source.y + source.height / 2 }
  const targetCenter = { x: target.x + target.width / 2, y: target.y + target.height / 2 }
  const dx = targetCenter.x - sourceCenter.x
  const dy = targetCenter.y - sourceCenter.y
  const horizontal = Math.abs(dx) >= Math.abs(dy)

  const start = horizontal
    ? { x: dx >= 0 ? source.x + source.width : source.x, y: sourceCenter.y }
    : { x: sourceCenter.x, y: dy >= 0 ? source.y + source.height : source.y }
  const end = horizontal
    ? { x: dx >= 0 ? target.x : target.x + target.width, y: targetCenter.y }
    : { x: targetCenter.x, y: dy >= 0 ? target.y : target.y + target.height }

  // 画布连线使用流程图常见的正交折线，避免贝塞尔曲线在多节点场景里交叉得过于混乱。
  if (horizontal) {
    const midX = (start.x + end.x) / 2
    return `M ${start.x} ${start.y} L ${midX} ${start.y} L ${midX} ${end.y} L ${end.x} ${end.y}`
  }
  const midY = (start.y + end.y) / 2
  return `M ${start.x} ${start.y} L ${start.x} ${midY} L ${end.x} ${midY} L ${end.x} ${end.y}`
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

function arrangeNodesByRelations(nodes: CanvasNodeElement[], edges: CanvasEdgeElement[]): CanvasNodeElement[] {
  const nodeIds = new Set(nodes.map((node) => node.id))
  const validEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]))
  const indegree = new Map(nodes.map((node) => [node.id, 0]))

  validEdges.forEach((edge) => {
    outgoing.get(edge.source)?.push(edge.target)
    indegree.set(edge.target, (indegree.get(edge.target) || 0) + 1)
  })

  const levels = new Map(nodes.map((node) => [node.id, 0]))
  const queue = nodes.filter((node) => (indegree.get(node.id) || 0) === 0).map((node) => node.id)
  const ordered: string[] = []

  while (queue.length) {
    const id = queue.shift()!
    ordered.push(id)
    for (const targetId of outgoing.get(id) || []) {
      levels.set(targetId, Math.max(levels.get(targetId) || 0, (levels.get(id) || 0) + 1))
      indegree.set(targetId, (indegree.get(targetId) || 0) - 1)
      if ((indegree.get(targetId) || 0) === 0) queue.push(targetId)
    }
  }

  // 如果用户手动连出了环，无法完全无交叉；这里把环内剩余节点放到最后一列，至少不让线穿满全图。
  const unresolved = nodes.filter((node) => !ordered.includes(node.id))
  const fallbackLevel = Math.max(0, ...Array.from(levels.values())) + 1
  unresolved.forEach((node, index) => {
    levels.set(node.id, fallbackLevel + index)
  })

  const levelGroups = new Map<number, CanvasNodeElement[]>()
  nodes.forEach((node) => {
    const level = levels.get(node.id) || 0
    levelGroups.set(level, [...(levelGroups.get(level) || []), node])
  })

  const sortedLevels = Array.from(levelGroups.keys()).sort((a, b) => a - b)
  const rowById = new Map<string, number>()
  const arranged: CanvasNodeElement[] = []

  sortedLevels.forEach((level) => {
    const group = levelGroups.get(level) || []
    group.sort((a, b) => {
      const aParents = validEdges.filter((edge) => edge.target === a.id).map((edge) => rowById.get(edge.source) ?? 0)
      const bParents = validEdges.filter((edge) => edge.target === b.id).map((edge) => rowById.get(edge.source) ?? 0)
      const aScore = aParents.length ? aParents.reduce((sum, row) => sum + row, 0) / aParents.length : nodes.indexOf(a)
      const bScore = bParents.length ? bParents.reduce((sum, row) => sum + row, 0) / bParents.length : nodes.indexOf(b)
      return aScore - bScore
    })

    group.forEach((node, row) => {
      rowById.set(node.id, row)
      arranged.push({
        ...node,
        x: 96 + level * 330,
        y: 96 + row * 148,
      })
    })
  })

  return arranged
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
  const [relationTargetId, setRelationTargetId] = useState('')

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

  function nodeLabel(nodeId: string): string {
    return nodeMap.get(nodeId)?.text || nodeId
  }

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

  function updateDraftGraph(nextNodes: CanvasNodeElement[], nextEdges: CanvasEdgeElement[]) {
    setDraftCanvas(rebuildCanvasArtifact(currentCanvas, groups, nextNodes, nextEdges))
    setIsDirty(true)
    setSaveStatus('idle')
    setPptSyncStatus('idle')
  }

  function updateDraftEdges(nextEdges: CanvasEdgeElement[]) {
    updateDraftGraph(nodes, nextEdges)
  }

  function updateSelectedNode(patch: Partial<CanvasNodeElement>) {
    if (!selectedNode) return
    updateDraftNodes(nodes.map((node) => (node.id === selectedNode.id ? { ...node, ...patch } : node)))
  }

  function addCanvasNode() {
    const anchor = selectedNode || nodes[nodes.length - 1]
    const id = `n_${Date.now()}`
    const nextNode: CanvasNodeElement = {
      type: 'node',
      id,
      text: '新观点',
      kind: 'insight',
      artifact_type: null,
      description: '补充这个节点如何支撑 PPT 结构',
      x: Math.round((anchor?.x || 120) + 300),
      y: Math.round(anchor?.y || 120),
      width: 220,
      height: 88,
      style: { fill: '#F0FDF4', stroke: '#16A34A', text: '#14532D', accent: '#22C55E' },
    }
    const nextEdges = anchor
      ? [...edges, { type: 'edge' as const, id: `e_${Date.now()}`, source: anchor.id, target: id, label: '展开' }]
      : edges
    updateDraftGraph([...nodes, nextNode], nextEdges)
    setSelectedId(id)
  }

  function deleteSelectedNode() {
    if (!selectedNode || nodes.length <= 1) return
    const nextNodes = nodes.filter((node) => node.id !== selectedNode.id)
    const nextEdges = edges.filter((edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id)
    updateDraftGraph(nextNodes, nextEdges)
    setSelectedId(nextNodes[0]?.id || null)
  }

  function addRelation() {
    if (!selectedNode || !relationTargetId || relationTargetId === selectedNode.id) return
    const exists = edges.some((edge) => edge.source === selectedNode.id && edge.target === relationTargetId)
    if (exists) return
    updateDraftEdges([
      ...edges,
      { type: 'edge', id: `e_${Date.now()}`, source: selectedNode.id, target: relationTargetId, label: '下一步' },
    ])
    setRelationTargetId('')
  }

  function removeRelation(edgeId: string) {
    updateDraftEdges(edges.filter((edge) => edge.id !== edgeId))
  }

  function autoArrangeByRelations() {
    if (!nodes.length) return
    const nextNodes = arrangeNodesByRelations(nodes, edges)
    updateDraftGraph(nextNodes, edges)
    resetView()
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
          <button type="button" onClick={addCanvasNode} className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white">
            新增节点
          </button>
          <button
            type="button"
            onClick={deleteSelectedNode}
            disabled={!selectedNode || nodes.length <= 1}
            className="rounded border border-red-200 px-3 py-1 text-xs text-red-500 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            删除节点
          </button>
          <button type="button" onClick={autoArrangeByRelations} className="rounded border px-3 py-1 text-xs text-gray-600 hover:bg-white">
            按关系整理
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
        {selectedNode && (
          <div className="basis-full rounded-lg border border-blue-100 bg-white px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-gray-500">添加边：</span>
              <span className="max-w-[260px] truncate font-medium text-gray-800">{selectedNode.text}</span>
              <span className="text-gray-400">→</span>
              <select
                value={relationTargetId}
                onChange={(event) => setRelationTargetId(event.target.value)}
                className="min-w-[220px] rounded border border-gray-200 px-2 py-1 text-gray-700 outline-none focus:border-blue-400"
              >
                <option value="">选择目标节点</option>
                {nodes
                  .filter((node) => node.id !== selectedNode.id)
                  .map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.text}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                onClick={addRelation}
                disabled={!relationTargetId}
                className="rounded bg-blue-600 px-3 py-1 text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                添加边
              </button>
              <span className="text-gray-400">这会把当前节点设为上游，目标节点设为下游。</span>
            </div>
          </div>
        )}
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
                    <path
                      d={path}
                      fill="none"
                      stroke="#64748B"
                      strokeWidth="2.2"
                      strokeLinejoin="round"
                      strokeLinecap="round"
                      markerEnd={`url(#${markerId})`}
                    />
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
            缩放 {Math.round(zoom * 100)}% · 拖拽节点改排版，右侧增删关系改结构
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
                <div className="mt-2 flex gap-2">
                  <select
                    value={relationTargetId}
                    onChange={(event) => setRelationTargetId(event.target.value)}
                    className="min-w-0 flex-1 rounded border border-gray-200 px-2 py-2 text-xs text-gray-700 outline-none focus:border-blue-400"
                  >
                    <option value="">选择下游节点</option>
                    {nodes
                      .filter((node) => node.id !== selectedNode.id)
                      .map((node) => (
                        <option key={node.id} value={node.id}>
                          {node.text}
                        </option>
                      ))}
                  </select>
                  <button
                    type="button"
                    onClick={addRelation}
                    disabled={!relationTargetId}
                    className="rounded bg-slate-900 px-3 py-2 text-xs text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-gray-300"
                  >
                    添加下游
                  </button>
                </div>
                <div className="mt-2 space-y-1">
                  {edges
                    .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
                    .map((edge) => {
                      const isOutgoing = edge.source === selectedNode.id
                      return (
                        <div key={edge.id} className="flex items-center justify-between gap-2 rounded bg-gray-50 px-2 py-1 text-xs text-gray-600">
                          <span className="min-w-0 flex-1 truncate">
                            {isOutgoing ? `下游：${nodeLabel(edge.target)}` : `上游：${nodeLabel(edge.source)}`}
                          </span>
                          <button type="button" onClick={() => removeRelation(edge.id)} className="text-red-500 hover:text-red-600">
                            删除
                          </button>
                        </div>
                      )
                    })}
                </div>
                <p className="mt-2 text-xs text-gray-400">
                  拖动节点只调整视觉位置；增删上下游关系才会改变内容结构和同步到 PPT 的顺序。
                </p>
                <button
                  type="button"
                  onClick={deleteSelectedNode}
                  disabled={nodes.length <= 1}
                  className="mt-2 w-full rounded border border-red-200 px-3 py-2 text-xs text-red-500 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  删除当前节点
                </button>
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
