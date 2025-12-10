import type { TaskStep, StepType } from '@/types/pywebview.d';

interface StepListProps {
  steps: TaskStep[];
}

// 获取步骤图标（使用简洁字母，在小尺寸下更清晰）
function getStepIcon(type: StepType): string {
  switch (type) {
    case 'user_message':
      return 'U';
    case 'assistant_message':
      return 'A';
    case 'tool_use':
      return 'T';
    case 'tool_result':
      return 'R';
    case 'system':
      return 'S';
    default:
      return '•';
  }
}

// 获取步骤类型样式类
function getStepIconClass(type: StepType): string {
  switch (type) {
    case 'user_message':
      return 'user';
    case 'assistant_message':
      return 'assistant';
    case 'tool_use':
    case 'tool_result':
      return 'tool';
    default:
      return '';
  }
}

export default function StepList({ steps }: StepListProps) {
  if (steps.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-center py-4">
        暂无步骤
      </div>
    );
  }

  return (
    <div className="step-list">
      {steps.map((step) => (
        <div key={step.step_id} className="step-item">
          <div className={`step-icon ${getStepIconClass(step.type)}`}>
            {getStepIcon(step.type)}
          </div>
          <div className="step-content">
            {step.tool_name && (
              <code className="step-tool-name">{step.tool_name}</code>
            )}
            <span>{step.content}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
