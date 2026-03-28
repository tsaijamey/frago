/**
 * SubAgentModal — Full-screen expanded view of a sub-agent's execution.
 *
 * 85% screen size, frosted glass overlay, scrollable step list.
 * ESC or click overlay to close.
 */

import { useEffect, useCallback } from 'react';
import { formatElapsed } from './constants';
import SubAgentStep from './SubAgentStep';
import type { StepData } from './SubAgentBlock';

interface SubAgentModalProps {
  task: {
    id: string;
    name: string | null;
    started_at: string;
    elapsed_seconds: number;
    step_count: number;
    steps?: StepData[];
  };
  isRunning: boolean;
  onClose: () => void;
}

export default function SubAgentModal({ task, isRunning, onClose }: SubAgentModalProps) {
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const steps = task.steps || [];
  const statusText = isRunning ? 'RUNNING' : 'COMPLETED';
  const statusClass = isRunning ? 'sa-modal-status--running' : 'sa-modal-status--completed';

  return (
    <div className="sa-modal-overlay" onClick={onClose}>
      <div className="sa-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sa-modal-header">
          <div className="sa-modal-header-left">
            <span className="sa-modal-icon">▸</span>
            <span className="sa-modal-title">
              sub-agent #{task.id.slice(-4)}
            </span>
            <span className="tl-badge">{task.name || 'task'}</span>
            <span className={`sa-modal-status ${statusClass}`}>{statusText}</span>
          </div>
          <div className="sa-modal-header-right">
            <span className="sa-modal-meta">
              {task.step_count} steps
            </span>
            <span className="sa-modal-meta">
              {formatElapsed(task.elapsed_seconds)}
            </span>
            <button className="sa-modal-close" onClick={onClose}>×</button>
          </div>
        </div>

        {/* Body — scrollable step list */}
        <div className="sa-modal-body">
          {steps.length > 0 ? (
            steps.map((step, i) => (
              <SubAgentStep
                key={step.step_id || i}
                step={step}
                baseTimestamp={task.started_at}
                expanded
              />
            ))
          ) : (
            <div className="sa-modal-empty">
              {isRunning ? '执行中...' : '无步骤数据'}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="sa-modal-footer">
          <button className="tl-link" onClick={onClose}>
            show less ↑
          </button>
        </div>
      </div>
    </div>
  );
}
