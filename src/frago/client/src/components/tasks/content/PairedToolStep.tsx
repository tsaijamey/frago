import type { TaskStep } from '@/types/pywebview';
import { Wrench, ArrowRight } from 'lucide-react';
import { StepContent } from './index';

interface PairedToolStepProps {
  call: TaskStep;
  result: TaskStep;
}

/**
 * Renders a paired tool call and its result in a connected visual block.
 */
export default function PairedToolStep({ call, result }: PairedToolStepProps) {
  return (
    <div className="paired-tool-step">
      {/* Tool Call Section */}
      <div className="paired-step-call">
        <div className="paired-step-header">
          <Wrench className="icon-scaled-sm text-[var(--accent-warning)]" />
          <span className="paired-step-label">Tool</span>
          {call.tool_name && (
            <code className="paired-step-tool-name">{call.tool_name}</code>
          )}
        </div>
        <div className="paired-step-content">
          <StepContent step={call} />
        </div>
      </div>

      {/* Tool Result Section */}
      <div className="paired-step-result">
        <div className="paired-step-header">
          <ArrowRight className="icon-scaled-sm text-[var(--accent-success)]" />
          <span className="paired-step-label">Result</span>
        </div>
        <div className="paired-step-content">
          <StepContent step={result} />
        </div>
      </div>
    </div>
  );
}
