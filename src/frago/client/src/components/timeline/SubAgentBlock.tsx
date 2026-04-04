/**
 * SubAgentBlock — Collapsed sub-agent view in the timeline.
 *
 * Shows: left green bar + header + last 3 steps + "show more" button.
 * Clicking "show more" opens SubAgentModal.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { formatRelativeTime, formatElapsed } from './constants';
import SubAgentModal from './SubAgentModal';
import SubAgentStep from './SubAgentStep';

interface RunningTask {
  id: string;
  name: string | null;
  project_path: string;
  started_at: string;
  elapsed_seconds: number;
  current_step: string | null;
  step_count: number;
  steps?: StepData[];
}

export interface StepData {
  step_id: string;
  type: string;
  timestamp: string;
  content: string;
  tool_name?: string;
  tool_result?: string;
  success?: boolean;
}

interface SubAgentBlockProps {
  task: RunningTask;
  onViewDetail?: () => void;
}

export default function SubAgentBlock({ task, onViewDetail }: SubAgentBlockProps) {
  const { t } = useTranslation();
  const [showModal, setShowModal] = useState(false);

  const steps = task.steps || [];
  const visibleSteps = steps.slice(-3);
  const hiddenCount = Math.max(0, steps.length - 3);
  const isRunning = true; // This component is used for running tasks

  return (
    <>
      <div className="tl-subagent">
        {/* Header */}
        <div className="tl-subagent-header">
          <div className="tl-row">
            <span className="tl-ts">{formatRelativeTime(task.started_at)}</span>
            <span className="tl-icon tl-icon--accent">▸</span>
            <span className="tl-content">
              <span className="tl-title tl-title--accent">
                {t('timeline.agentRunning')}
              </span>
              <span className="tl-badge">{task.name || 'task'}</span>
              <span className="tl-meta">{formatElapsed(task.elapsed_seconds)}</span>
            </span>
          </div>
        </div>

        {/* Hidden steps count */}
        {hiddenCount > 0 && (
          <div className="tl-row tl-row--sub">
            <span className="tl-ts"></span>
            <span className="tl-icon"></span>
            <span className="tl-text tl-text--dim" style={{ opacity: 0.3 }}>
              {t('timeline.earlierStepsHidden', { count: hiddenCount })}
            </span>
          </div>
        )}

        {/* Visible steps (last 3) */}
        {visibleSteps.map((step, i) => (
          <SubAgentStep key={step.step_id || i} step={step} baseTimestamp={task.started_at} />
        ))}

        {/* Current step preview (if no detailed steps) */}
        {steps.length === 0 && task.current_step && (
          <div className="tl-row tl-row--sub">
            <span className="tl-ts"></span>
            <span className="tl-icon tl-icon--dim">◇</span>
            <span className="tl-text tl-text--secondary">
              {task.current_step.length > 100
                ? task.current_step.slice(0, 100) + '...'
                : task.current_step}
            </span>
          </div>
        )}

        {/* Show more / view detail button */}
        <div className="tl-row tl-row--sub tl-row--action">
          <span className="tl-ts"></span>
          <span className="tl-icon"></span>
          <span className="tl-text">
            {task.step_count > 3 ? (
              <button
                className="tl-link"
                onClick={(e) => { e.stopPropagation(); setShowModal(true); }}
              >
                {t('timeline.showMore')}
              </button>
            ) : (
              <button
                className="tl-link"
                onClick={(e) => { e.stopPropagation(); onViewDetail?.(); }}
              >
                {t('timeline.stepsViewDetail', { count: task.step_count })}
              </button>
            )}
          </span>
        </div>
      </div>

      {/* Expanded Modal */}
      {showModal && (
        <SubAgentModal
          task={task}
          isRunning={isRunning}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  );
}
