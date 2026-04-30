import { useSessionStore } from '../store/useSessionStore'
import clsx from 'clsx'

interface ProgressTimelineProps {
  className?: string
}

const steps = [
  { key: 'receive_input', name: '接收输入', icon: '1' },
  { key: 'parse_intent', name: '分析需求', icon: '2' },
  { key: 'plan_workflow', name: '规划流程', icon: '3' },
  { key: 'extract_tasks', name: '提取任务', icon: '4' },
  { key: 'generate_doc', name: '生成文档', icon: '5' },
  // 后端会在需要结构图时推送 generate_canvas，前端要把它纳入时间线。
  { key: 'generate_canvas', name: '生成画布', icon: '6' },
  { key: 'generate_slides', name: '生成 PPT', icon: '7' },
  { key: 'generate_rehearsal', name: '生成讲稿', icon: '8' },
  { key: 'prepare_delivery', name: '准备交付', icon: '9' },
  { key: 'confirm_or_modify', name: '确认修改', icon: '10' },
  { key: 'deliver_result', name: '交付结果', icon: '11' },
]

type StepStatus = 'completed' | 'active' | 'pending' | 'failed'

export default function ProgressTimeline({ className = '' }: ProgressTimelineProps) {
  const { currentStep, status } = useSessionStore()

  const currentStepIndex = steps.findIndex((step) => step.key === currentStep)

  const getStepStatus = (index: number): StepStatus => {
    if (status === 'completed') return 'completed'
    if (status === 'failed' || status === 'error') {
      return index <= currentStepIndex ? 'failed' : 'pending'
    }
    if (currentStepIndex === -1) return 'pending'
    if (index < currentStepIndex) return 'completed'
    if (index === currentStepIndex) return 'active'
    return 'pending'
  }

  return (
    <div className={`bg-white border rounded-lg p-4 shadow-sm ${className}`}>
      <h3 className="font-medium text-gray-800 mb-4">执行进度</h3>
      <div className="space-y-4">
        {steps.map((step, index) => {
          const stepStatus = getStepStatus(index)

          return (
            <div key={step.key} className="flex items-start gap-3">
              <div className="relative flex-shrink-0">
                <div
                  className={clsx(
                    'w-10 h-10 rounded-full flex items-center justify-center text-sm font-semibold transition-all duration-300',
                    stepStatus === 'completed' && 'bg-green-100 text-green-600',
                    stepStatus === 'active' && 'bg-blue-100 text-blue-600 scale-110',
                    stepStatus === 'pending' && 'bg-gray-100 text-gray-400',
                    stepStatus === 'failed' && 'bg-red-100 text-red-600'
                  )}
                >
                  {stepStatus === 'completed' ? 'OK' : step.icon}
                </div>
                {index < steps.length - 1 && (
                  <div
                    className={clsx(
                      'absolute top-10 left-1/2 -translate-x-1/2 w-0.5 h-4 transition-all duration-300',
                      stepStatus === 'completed' ? 'bg-green-400' : 'bg-gray-200'
                    )}
                  />
                )}
              </div>
              <div className="flex-1 pt-2">
                <div
                  className={clsx(
                    'font-medium',
                    stepStatus === 'completed' && 'text-green-600 line-through',
                    stepStatus === 'active' && 'text-blue-600 font-semibold',
                    stepStatus === 'pending' && 'text-gray-500',
                    stepStatus === 'failed' && 'text-red-600'
                  )}
                >
                  {step.name}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
