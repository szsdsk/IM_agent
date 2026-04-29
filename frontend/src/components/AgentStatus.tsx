import { useSessionStore } from '../store/useSessionStore'
import clsx from 'clsx'

interface AgentStatusProps {
  className?: string
}

const stepNames: Record<string, { name: string; icon: string }> = {
  receive_input: { name: '接收输入', icon: 'IN' },
  parse_intent: { name: '分析需求', icon: 'AI' },
  plan_workflow: { name: '规划流程', icon: 'PL' },
  extract_tasks: { name: '提取任务', icon: 'TK' },
  generate_doc: { name: '生成文档', icon: 'DOC' },
  // 与后端 LangGraph 节点保持一致，避免生成画布时状态卡片空白。
  generate_canvas: { name: '生成画布', icon: 'MAP' },
  generate_slides: { name: '生成 PPT', icon: 'PPT' },
  confirm_or_modify: { name: '等待确认', icon: 'OK' },
  deliver_result: { name: '交付结果', icon: 'END' },
}

export default function AgentStatus({ className = '' }: AgentStatusProps) {
  const { currentStep, progress, status, wsConnected } = useSessionStore()

  const getStatusColor = () => {
    switch (status) {
      case 'running':
        return 'text-blue-500'
      case 'completed':
        return 'text-green-500'
      case 'failed':
      case 'error':
        return 'text-red-500'
      default:
        return 'text-gray-500'
    }
  }

  const getStatusText = () => {
    switch (status) {
      case 'idle':
        return '就绪'
      case 'connecting':
        return '连接中'
      case 'connected':
        return '已连接'
      case 'running':
        return '执行中'
      case 'completed':
        return '已完成'
      case 'failed':
        return '执行失败'
      case 'error':
        return '错误'
      default:
        return '未知'
    }
  }

  const currentStepInfo = currentStep ? stepNames[currentStep] : null

  return (
    <div className={`bg-white border rounded-lg p-4 shadow-sm ${className}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-medium text-gray-800">Agent 状态</h3>
        <div className="flex items-center gap-2">
          <span
            className={clsx(
              'inline-flex items-center gap-1 text-sm',
              wsConnected ? 'text-green-500' : 'text-red-500'
            )}
          >
            <span
              className={clsx(
                'w-2 h-2 rounded-full',
                wsConnected ? 'bg-green-500' : 'bg-red-500'
              )}
            />
            {wsConnected ? '已连接' : '未连接'}
          </span>
          <span className={`text-sm font-medium ${getStatusColor()}`}>{getStatusText()}</span>
        </div>
      </div>

      {currentStepInfo && status === 'running' && (
        <div className="mb-4">
          <div className="flex items-center gap-3 mb-2">
            <span className="inline-flex h-9 min-w-9 items-center justify-center rounded bg-blue-50 px-2 text-xs font-semibold text-blue-600">
              {currentStepInfo.icon}
            </span>
            <span className="font-medium text-gray-700">{currentStepInfo.name}</span>
          </div>

          <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
            <div
              className="bg-primary-500 h-full transition-all duration-300 ease-out"
              style={{ width: `${Math.max(5, progress * 100)}%` }}
            />
          </div>
          <div className="text-right text-xs text-gray-500 mt-1">{Math.round(progress * 100)}%</div>
        </div>
      )}

      {!currentStepInfo && status === 'idle' && (
        <div className="text-center py-6 text-gray-400 text-sm">
          <p>等待用户输入...</p>
        </div>
      )}

      {(status === 'error' || status === 'failed') && (
        <div className="text-center py-6 text-red-400 text-sm">
          <p>发生错误，请重试</p>
        </div>
      )}
    </div>
  )
}
