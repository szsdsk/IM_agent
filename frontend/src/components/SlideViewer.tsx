import { useState } from 'react'
import { useSessionStore } from '../store/useSessionStore'
import type { FeedbackHistoryItem, QAItem, RehearsalSlide, SlideDeckPayload } from '../types'

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
  const { slides } = useSessionStore()
  const [selectedIndex, setSelectedIndex] = useState(0)

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

  const deckPayload: SlideDeckPayload = Array.isArray(slides.slides_json)
    ? { slides: slides.slides_json as SlideItem[] }
    : ((slides.slides_json || {}) as SlideDeckPayload)
  const slidesData = (deckPayload.slides || []) as SlideItem[]
  const selectedSlide = slidesData[Math.min(selectedIndex, Math.max(slidesData.length - 1, 0))]
  const rehearsalSlides = deckPayload.rehearsal?.slides || []
  const selectedRehearsal = rehearsalSlides.find((item: RehearsalSlide) => item.slide_index === selectedIndex)
  const selectedQa = (deckPayload.qa || []).filter((item: QAItem) => item.slide_index === selectedIndex || item.slide_index == null)
  const feedbackHistory = deckPayload.feedback_history || deckPayload.metadata?.feedback_history || []

  return (
    <div className={`bg-white border rounded-lg shadow-sm overflow-hidden ${className}`}>
      <div className="px-4 py-3 border-b bg-gray-50 flex justify-between items-center">
        <div>
          <h3 className="font-medium text-gray-800">PPT 预览</h3>
          <p className="text-xs text-gray-500 mt-1">共 {slidesData.length} 页</p>
        </div>
        {slides.file_path && (
          <div className="flex items-center gap-2">
            {/* 网页端只负责本地交付，飞书交付统一走 bot 流程。 */}
            <a
              href={getDownloadHref(slides.file_path)}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 text-sm bg-primary-500 text-white rounded hover:bg-primary-600 transition-colors"
            >
              下载
            </a>
          </div>
        )}
      </div>

      <div className="p-6 overflow-y-auto max-h-[600px]">
        {slidesData.length > 0 ? (
          <div className="space-y-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {slidesData.map((slide, index) => (
                <button
                  type="button"
                  key={index}
                  onClick={() => setSelectedIndex(index)}
                  className={`aspect-[4/3] rounded-lg border p-4 text-left transition-shadow hover:shadow-md ${
                    selectedIndex === index ? 'border-blue-500 bg-blue-50' : 'bg-gray-50'
                  }`}
                >
                  <div className="text-xs text-gray-500 mb-2">第 {index + 1} 页</div>
                  {slide.title && <h4 className="font-medium text-gray-800 mb-2">{slide.title}</h4>}
                  {getSlideText(slide) && (
                    <p className="text-sm text-gray-600 whitespace-pre-wrap line-clamp-6">{getSlideText(slide)}</p>
                  )}
                </button>
              ))}
            </div>

            {selectedSlide && (
              <div className="rounded-lg border bg-white p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">单页详情</p>
                    <h4 className="font-semibold text-gray-800">
                      第 {selectedIndex + 1} 页：{selectedSlide.title || '未命名'}
                    </h4>
                  </div>
                  {selectedRehearsal?.duration_seconds && (
                    <span className="rounded-full bg-gray-100 px-2 py-1 text-xs text-gray-600">
                      预计 {selectedRehearsal.duration_seconds}s
                    </span>
                  )}
                </div>

                {selectedRehearsal?.speaker_notes && (
                  <div className="mb-3 rounded-md bg-amber-50 p-3">
                    <p className="mb-1 text-xs font-medium text-amber-700">演练讲稿</p>
                    <p className="whitespace-pre-wrap text-sm text-gray-700">{selectedRehearsal.speaker_notes}</p>
                  </div>
                )}

                {selectedQa.length > 0 && (
                  <div className="mb-3 rounded-md bg-blue-50 p-3">
                    <p className="mb-2 text-xs font-medium text-blue-700">可能 Q&A</p>
                    <div className="space-y-2">
                      {selectedQa.slice(0, 4).map((item, index) => (
                        <div key={`${item.question}-${index}`} className="text-sm text-gray-700">
                          <p className="font-medium">Q：{item.question}</p>
                          <p>A：{item.answer}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {feedbackHistory.length > 0 && (
                  <div className="rounded-md bg-gray-50 p-3">
                    <p className="mb-2 text-xs font-medium text-gray-600">最近修改</p>
                    <div className="space-y-1 text-xs text-gray-600">
                      {(feedbackHistory as FeedbackHistoryItem[]).slice(-3).reverse().map((item, index) => (
                        <p key={`${item.created_at}-${index}`}>
                          {item.target_slide_numbers?.length
                            ? `第 ${item.target_slide_numbers.join('、')} 页`
                            : item.mode === 'global'
                              ? '全局'
                              : '未指定页'}
                          ：{item.feedback}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="text-center text-gray-400 py-12">PPT 正在生成中...</div>
        )}
      </div>
    </div>
  )
}
