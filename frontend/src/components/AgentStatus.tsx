import { useSessionStore } from '../store/useSessionStore'
import clsx from 'clsx'

interface AgentStatusProps {
  className?: string
}

const agentNames: Record<string, string> = {
  pilot_agent: 'Pilot Agent',
  planner_agent: 'Planner Agent',
  im_context_agent: 'IM Context Agent',
  doc_agent: 'Doc Agent',
  canvas_agent: 'Canvas Agent',
  deck_agent: 'Deck Agent',
  ppt_agent: 'PPT Agent',
  rehearsal_agent: 'Rehearsal Agent',
  delivery_agent: 'Delivery Agent',
}

const stepNames: Record<string, { agent: string; action: string; icon: string }> = {
  receive_input: { agent: 'pilot_agent', action: '已接收 IM 指令', icon: 'PI' },
  parse_intent: { agent: 'pilot_agent', action: '正在理解用户意图', icon: 'PI' },
  plan_workflow: { agent: 'planner_agent', action: '正在拆解任务并编排流程', icon: 'PL' },
  extract_tasks: { agent: 'planner_agent', action: '正在生成可执行任务清单', icon: 'PL' },
  generate_doc: { agent: 'doc_agent', action: '正在生成发布评审文档', icon: 'DOC' },
  generate_canvas: { agent: 'canvas_agent', action: '正在生成流程图画布', icon: 'MAP' },
  generate_slides: { agent: 'deck_agent', action: '正在生成管理层汇报 PPT', icon: 'PPT' },
  generate_rehearsal: { agent: 'rehearsal_agent', action: '正在准备讲稿与 Q&A', icon: 'QA' },
  prepare_delivery: { agent: 'delivery_agent', action: '正在归档并准备回传飞书', icon: 'DL' },
  confirm_or_modify: { agent: 'pilot_agent', action: '等待确认或修改意见', icon: 'OK' },
  deliver_result: { agent: 'delivery_agent', action: '正在交付结果', icon: 'END' },
}

export default function AgentStatus({ className = '' }: AgentStatusProps) {
  const { currentStep, activeAgent, progressMessage, progress, status, wsConnected } = useSessionStore()

  const getStatusColor = () => {
    switch (status) {
      case 'running':
        return 'text-blue-500'
      case 'completed':
        return 'text-green-500'
      case 'failed':
      case 'error':
        return 'text-red-500'
      case 'awaiting_clarification':
        return 'text-amber-500'
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
      case 'awaiting_clarification':
        return '等待澄清'
      default:
        return '未知'
    }
  }

  const currentStepInfo = currentStep ? stepNames[currentStep] : null
  const agentKey = activeAgent || currentStepInfo?.agent || ''
  const agentLabel = agentNames[agentKey] || agentKey || 'Agent'
  const actionLabel = progressMessage || currentStepInfo?.action || ''

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
            <div className="min-w-0">
              <div className="font-semibold text-gray-800">{agentLabel}</div>
              <div className="truncate text-sm text-gray-500">{actionLabel}</div>
            </div>
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
