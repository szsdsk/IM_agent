import { useSessionStore } from '../store/useSessionStore'
import ReactMarkdown from 'react-markdown'

interface DocViewerProps {
  className?: string
}

export default function DocViewer({ className = '' }: DocViewerProps) {
  const { doc } = useSessionStore()

  if (!doc) {
    return (
      <div className={`bg-white border rounded-lg p-6 shadow-sm ${className}`}>
        <h3 className="font-medium text-gray-800 mb-4">文档预览</h3>
        <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
          暂无文档内容
        </div>
      </div>
    )
  }

  // Check for Feishu doc URL
  const feishuUrl = (doc as any)?.doc_url as string | undefined

  return (
    <div className={`bg-white border rounded-lg shadow-sm overflow-hidden ${className}`}>
      <div className="px-4 py-3 border-b bg-gray-50 flex justify-between items-center">
        <div>
          <h3 className="font-medium text-gray-800">文档预览</h3>
          <p className="text-xs text-gray-500 mt-1">版本: {doc.version}</p>
        </div>
        {feishuUrl && (
          <a
            href={feishuUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1 text-sm bg-blue-500 text-white rounded hover:bg-blue-600 transition-colors"
          >
            在飞书中编辑
          </a>
        )}
      </div>

      <div className="p-6 overflow-y-auto max-h-[600px] prose prose-sm max-w-none">
        {doc.content ? (
          <ReactMarkdown>{doc.content}</ReactMarkdown>
        ) : (
          <div className="text-center text-gray-400 py-12">文档正在生成中...</div>
        )}
      </div>
    </div>
  )
}
