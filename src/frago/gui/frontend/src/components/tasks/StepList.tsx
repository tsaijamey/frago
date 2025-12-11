import type { TaskStep, StepType } from '@/types/pywebview.d';
import { User, Bot, Wrench, ArrowRight, Settings, type LucideIcon } from 'lucide-react';

interface StepListProps {
  steps: TaskStep[];
}

// 步骤图标配置
const stepIconConfig: Record<StepType, { Icon: LucideIcon; className: string }> = {
  user_message: { Icon: User, className: 'user' },
  assistant_message: { Icon: Bot, className: 'assistant' },
  tool_use: { Icon: Wrench, className: 'tool' },
  tool_result: { Icon: ArrowRight, className: 'tool' },
  system: { Icon: Settings, className: '' },
};

function getStepConfig(type: StepType) {
  return stepIconConfig[type] || { Icon: Settings, className: '' };
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
      {steps.map((step) => {
        const { Icon, className } = getStepConfig(step.type);
        return (
          <div key={step.step_id} className="step-item">
            <div className={`step-icon ${className}`}>
              <Icon size={11} />
            </div>
            <div className="step-content">
              {step.tool_name && (
                <code className="step-tool-name">{step.tool_name}</code>
              )}
              <span>{step.content}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
