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

  const feishuUrl = doc.lark_doc_url || doc.doc_url || undefined
  const editedAt = doc.last_edited_at ? new Date(doc.last_edited_at).toLocaleString() : null

  return (
    <div className={`bg-white border rounded-lg shadow-sm overflow-hidden ${className}`}>
      <div className="px-4 py-3 border-b bg-gray-50 flex justify-between items-center">
        <div>
          <h3 className="font-medium text-gray-800">文档预览</h3>
          <div className="text-xs text-gray-500 mt-1 space-y-1">
            <p>版本: {doc.version}</p>
            {doc.last_edited_by && <p>最后编辑: {doc.last_edited_by}{editedAt ? ` · ${editedAt}` : ''}</p>}
            {doc.lark_doc_id && <p>飞书文档 ID: {doc.lark_doc_id}</p>}
          </div>
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

      {doc.diff_summary && (
        <div className="mx-6 mt-4 rounded-md border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
          <div className="font-medium mb-1">
            最近一次飞书编辑同步{doc.changed_lines !== undefined && doc.changed_lines !== null ? ` · 变更 ${doc.changed_lines} 行` : ''}
          </div>
          <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">{doc.diff_summary}</pre>
        </div>
      )}

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
