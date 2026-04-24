import { useSessionStore } from '../store/useSessionStore'

interface SlideViewerProps {
  className?: string
}

interface SlideItem {
  title?: string
  content?: string
}

export default function SlideViewer({ className = '' }: SlideViewerProps) {
  const { slides } = useSessionStore()

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
          <a
            href={slides.file_path}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1 text-sm bg-primary-500 text-white rounded hover:bg-primary-600 transition-colors"
          >
            下载
          </a>
        )}
      </div>

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
                {slide.content && (
                  <p className="text-sm text-gray-600 whitespace-pre-wrap">{slide.content}</p>
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
