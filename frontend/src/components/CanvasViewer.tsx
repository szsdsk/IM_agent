import { useSessionStore } from '../store/useSessionStore'

interface CanvasViewerProps {
  className?: string
}

export default function CanvasViewer({ className = '' }: CanvasViewerProps) {
  const canvas = useSessionStore((state) => state.canvas)

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
                <div key={node.id || index} className="rounded-lg border border-blue-100 bg-blue-50 p-3">
                  <p className="text-xs text-blue-500">{node.type || 'node'}</p>
                  <p className="font-medium text-gray-800">{node.text || node.id}</p>
                </div>
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
