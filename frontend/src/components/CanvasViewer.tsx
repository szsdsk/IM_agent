import { useSessionStore } from '../store/useSessionStore'

type ArtifactKind = 'doc' | 'slides' | 'canvas'

interface CanvasViewerProps {
  className?: string
  onOpenArtifact?: (artifact: ArtifactKind) => void
}

function normalizeText(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function detectArtifactKind(node: Record<string, any>): ArtifactKind | null {
  const haystack = [
    node.type,
    node.text,
    node.label,
    node.name,
    node.title,
    node.id,
  ]
    .map(normalizeText)
    .join(' ')

  if (/(文稿|文档|doc|document|prd|report)/.test(haystack)) return 'doc'
  if (/(ppt|slides|slide|deck|演示|幻灯片)/.test(haystack)) return 'slides'
  if (/(画布|canvas|whiteboard|白板)/.test(haystack)) return 'canvas'
  return null
}

function artifactLabel(kind: ArtifactKind): string {
  if (kind === 'doc') return '文稿产物'
  if (kind === 'slides') return 'PPT 产物'
  return '画布产物'
}

export default function CanvasViewer({ className = '', onOpenArtifact }: CanvasViewerProps) {
  const canvas = useSessionStore((state) => state.canvas)
  const doc = useSessionStore((state) => state.doc)
  const slides = useSessionStore((state) => state.slides)

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

  const nodes = canvas.nodes || []
  const edges = canvas.edges || []
  const layers = canvas.layers || []

  return (
    <div className={`overflow-hidden rounded-lg border bg-white shadow-sm ${className}`}>
      <div className="flex items-center justify-between border-b bg-gray-50 px-4 py-3">
        <div>
          <h3 className="font-medium text-gray-800">画布预览</h3>
          <p className="mt-1 text-xs text-gray-500">
            {canvas.provider === 'affine' ? 'AFFiNE 画布' : '本地 Mock 画布'}
            {canvas.diagram_type ? ` · ${canvas.diagram_type}` : ''}
          </p>
        </div>
        {canvas.url && (
          <a
            href={canvas.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700"
          >
            打开画布
          </a>
        )}
      </div>

      <div className="p-4">
        {nodes.length > 0 ? (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              {nodes.map((node, index) => (
                (() => {
                  const artifactKind = detectArtifactKind(node)
                  const isAvailable =
                    artifactKind === 'doc'
                      ? Boolean(doc)
                      : artifactKind === 'slides'
                        ? Boolean(slides)
                        : artifactKind === 'canvas'
                          ? Boolean(canvas)
                          : false

                  if (artifactKind) {
                    return (
                      <button
                        key={node.id || index}
                        type="button"
                        onClick={() => onOpenArtifact?.(artifactKind)}
                        disabled={!isAvailable}
                        className={`rounded-lg border p-3 text-left transition ${
                          isAvailable
                            ? 'border-emerald-200 bg-emerald-50 hover:border-emerald-300 hover:shadow-sm'
                            : 'cursor-not-allowed border-gray-200 bg-gray-50 opacity-70'
                        }`}
                      >
                        <p className="text-xs text-emerald-600">{artifactLabel(artifactKind)}</p>
                        <p className="font-medium text-gray-800">{node.text || node.id}</p>
                        <p className="mt-2 text-xs text-gray-500">
                          {isAvailable ? '点击打开真实产物预览' : '产物尚未生成'}
                        </p>
                      </button>
                    )
                  }

                  return (
                    <div key={node.id || index} className="rounded-lg border border-blue-100 bg-blue-50 p-3">
                      <p className="text-xs text-blue-500">{node.type || 'node'}</p>
                      <p className="font-medium text-gray-800">{node.text || node.id}</p>
                    </div>
                  )
                })()
              ))}
            </div>
            {edges.length > 0 && (
              <div className="rounded-md bg-gray-50 p-3 text-xs text-gray-600">
                {edges.map((edge, index) => (
                  <p key={`${edge.source || edge.from}-${edge.target || edge.to}-${index}`}>
                    {edge.source || edge.from} → {edge.target || edge.to}
                    {edge.label ? `：${edge.label}` : ''}
                  </p>
                ))}
              </div>
            )}
          </div>
        ) : layers.length > 0 ? (
          <div className="space-y-3">
            {layers.map((layer, index) => (
              <div key={index} className="rounded-lg border bg-gray-50 p-3">
                <p className="mb-2 text-xs text-gray-500">Layer {index + 1}</p>
                <div className="flex flex-wrap gap-2">
                  {layer.map((item) => (
                    <span key={item} className="rounded bg-white px-3 py-1 text-sm text-gray-700 shadow-sm">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="py-8 text-center text-sm text-gray-400">画布结构正在生成中...</div>
        )}
      </div>
    </div>
  )
}
