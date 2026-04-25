import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { useSessionStore } from '../store/useSessionStore'
import type { LarkCliStatus, LarkSyncResponse } from '../types'

interface SlideViewerProps {
  className?: string
}

interface SlideItem {
  title?: string
  content?: unknown
  bullets?: string[]
}

function getSlideText(slide: SlideItem): string {
  // 兼容模型返回的字符串、数组、对象和 bullets，统一转成可预览文本。
  if (typeof slide.content === 'string') return slide.content
  if (Array.isArray(slide.content)) return slide.content.map(String).join('\n')
  if (slide.content && typeof slide.content === 'object') {
    return Object.values(slide.content)
      .flatMap((value) => (Array.isArray(value) ? value : [value]))
      .filter((value) => value !== null && value !== undefined)
      .map(String)
      .join('\n')
  }
  return slide.bullets?.join('\n') || ''
}

function getDownloadHref(filePath: string): string {
  // 后端旧结果可能返回本地磁盘路径，这里转换成浏览器可访问的下载接口。
  if (filePath.includes('\\') || /^[a-zA-Z]:/.test(filePath)) {
    const filename = filePath.split(/[\\/]/).pop()
    return filename ? `/api/files/slides/${encodeURIComponent(filename)}` : filePath
  }
  return filePath
}

export default function SlideViewer({ className = '' }: SlideViewerProps) {
  const { slides, task } = useSessionStore()
  const [larkStatus, setLarkStatus] = useState<LarkCliStatus | null>(null)
  const [syncResult, setSyncResult] = useState<LarkSyncResponse | null>(null)
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    let cancelled = false

    // 组件加载时读取一次后端健康检查，避免每次渲染都请求 CLI 状态。
    api.healthCheck()
      .then((health) => {
        if (!cancelled) setLarkStatus(health.lark_cli ?? null)
      })
      .catch(() => {
        if (!cancelled) setLarkStatus(null)
      })

    return () => {
      cancelled = true
    }
  }, [])

  // 把后端的 CLI 状态转换成按钮禁用原因，用户悬停时能知道缺哪一步配置。
  const syncDisabledReason = !larkStatus?.enabled
    ? '飞书 CLI 同步未开启，请在后端配置 LARK_CLI_ENABLED=true'
    : !larkStatus.available
      ? `未找到 ${larkStatus.bin || 'lark-cli'}，请先安装飞书 CLI`
      : !larkStatus.authenticated
        ? '飞书 CLI 尚未登录，请先执行 lark-cli auth login --recommend'
        : !task?.id
          ? '当前任务信息还未准备好'
          : ''

  const canSyncToLark = Boolean(slides && task?.id && !syncDisabledReason)

  const handleSyncToLark = async () => {
    if (!task?.id || syncing) return

    // 同步动作只影响飞书交付，不改变本地 PPT 预览和下载结果。
    setSyncing(true)
    setSyncResult(null)
    try {
      const result = await api.syncArtifactToLark(task.id)
      setSyncResult(result)
    } catch (error) {
      setSyncResult({
        success: false,
        provider: 'lark_cli',
        artifact_id: task.id,
        error: error instanceof Error ? error.message : '同步到飞书失败',
      })
    } finally {
      setSyncing(false)
    }
  }

  const syncResultText = syncResult
    ? syncResult.success
      ? syncResult.message || '已同步到飞书'
      : syncResult.message || syncResult.error || '同步到飞书失败'
    : ''

  if (!slides) {
    return (
      <div className={`bg-white border rounded-lg p-6 shadow-sm ${className}`}>
        <h3 className="font-medium text-gray-800 mb-4">PPT 预览</h3>
        <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
          暂无 PPT 内容
        </div>
      </div>
    )
  }

  const slidesData = Array.isArray(slides.slides_json) ? (slides.slides_json as SlideItem[]) : []

  return (
    <div className={`bg-white border rounded-lg shadow-sm overflow-hidden ${className}`}>
      <div className="px-4 py-3 border-b bg-gray-50 flex justify-between items-center">
        <div>
          <h3 className="font-medium text-gray-800">PPT 预览</h3>
          <p className="text-xs text-gray-500 mt-1">共 {slidesData.length} 页</p>
        </div>
        {slides.file_path && (
          <div className="flex items-center gap-2">
            {/* 下载仍然走本地后端文件接口，保证即使飞书未配置也能交付 PPT。 */}
            <a
              href={getDownloadHref(slides.file_path)}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 text-sm bg-primary-500 text-white rounded hover:bg-primary-600 transition-colors"
            >
              下载
            </a>
            {/* 飞书按钮根据 health 返回的 CLI 状态启用或置灰。 */}
            <button
              type="button"
              onClick={handleSyncToLark}
              disabled={!canSyncToLark || syncing}
              title={syncDisabledReason || '同步到飞书'}
              className={`px-3 py-1 text-sm rounded transition-colors ${
                canSyncToLark && !syncing
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'bg-gray-200 text-gray-500 cursor-not-allowed'
              }`}
            >
              {syncing ? '同步中...' : '同步到飞书'}
            </button>
          </div>
        )}
      </div>

      {syncResult && (
        <div
          className={`mx-4 mt-3 rounded border px-3 py-2 text-sm ${
            syncResult.success ? 'border-green-200 bg-green-50 text-green-700' : 'border-amber-200 bg-amber-50 text-amber-700'
          }`}
        >
          <span>{syncResultText}</span>
          {syncResult.lark_url && (
            <a
              className="ml-2 underline"
              href={syncResult.lark_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              打开飞书链接
            </a>
          )}
        </div>
      )}

      <div className="p-6 overflow-y-auto max-h-[600px]">
        {slidesData.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {slidesData.map((slide, index) => (
              <div
                key={index}
                className="aspect-[4/3] border rounded-lg p-4 bg-gray-50 hover:shadow-md transition-shadow"
              >
                <div className="text-xs text-gray-500 mb-2">第 {index + 1} 页</div>
                {slide.title && <h4 className="font-medium text-gray-800 mb-2">{slide.title}</h4>}
                {getSlideText(slide) && (
                  <p className="text-sm text-gray-600 whitespace-pre-wrap">{getSlideText(slide)}</p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center text-gray-400 py-12">PPT 正在生成中...</div>
        )}
      </div>
    </div>
  )
}
