import type { TaskItem, TaskStatus } from '@/types/pywebview.d';
import { Zap, Check, X, Circle, Clock, FileText, Wrench, ChevronRight, type LucideIcon } from 'lucide-react';

interface TaskCardProps {
  task: TaskItem;
  onClick: () => void;
}

// Format relative time
function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)} min ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} hr ago`;

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });
}

// Format duration
function formatDuration(ms: number): string {
  if (ms < 1000) return '<1s';
  if (ms < 60000) return `${Math.floor(ms / 1000)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

// Status configuration
const statusConfig: Record<TaskStatus, { label: string; Icon: LucideIcon }> = {
  running: { label: 'Running', Icon: Zap },
  completed: { label: 'Completed', Icon: Check },
  error: { label: 'Error', Icon: X },
  cancelled: { label: 'Cancelled', Icon: Circle },
};

export default function TaskCard({ task, onClick }: TaskCardProps) {
  const { label: statusLabel, Icon: StatusIcon } = statusConfig[task.status] || statusConfig.completed;
  const isRunning = task.status === 'running';

  return (
    <div className="task-card-v2" onClick={onClick}>
      {/* Left: Status indicator */}
      <div className={`task-status-badge ${task.status}`}>
        <StatusIcon size={14} />
      </div>

      {/* Center: Main information */}
      <div className="task-main">
        <div className="task-header">
          <span className="task-title" title={task.name}>{task.name}</span>
          <span className="task-time">{formatRelativeTime(task.started_at)}</span>
        </div>

        {/* Progress bar (only shown when running) */}
        {isRunning && (
          <div className="task-progress">
            <div className="task-progress-bar">
              <div className="task-progress-fill" />
            </div>
          </div>
        )}

        {/* Metadata */}
        <div className="task-footer">
          <span className={`task-status-label status-${task.status}`}>
            {statusLabel}
          </span>
          <span className="task-stat">
            <Clock size={11} />
            {formatDuration(task.duration_ms)}
          </span>
          <span className="task-stat">
            <FileText size={11} />
            {task.step_count} steps
          </span>
          {task.tool_call_count > 0 && (
            <span className="task-stat">
              <Wrench size={11} />
              {task.tool_call_count} calls
            </span>
          )}
        </div>
      </div>

      {/* Right: Arrow */}
      <div className="task-arrow">
        <ChevronRight size={20} />
      </div>
    </div>
  );
}
