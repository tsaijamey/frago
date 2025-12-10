import type { TaskItem, TaskStatus } from '@/types/pywebview.d';

interface TaskCardProps {
  task: TaskItem;
  onClick: () => void;
}

// 格式化相对时间
function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  if (diff < 60000) return '刚刚';
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;

  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
  });
}

// 格式化持续时间
function formatDuration(ms: number): string {
  if (ms < 1000) return '<1s';
  if (ms < 60000) return `${Math.floor(ms / 1000)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

// 状态配置
const statusConfig: Record<TaskStatus, { label: string; icon: string }> = {
  running: { label: '运行中', icon: '⚡' },
  completed: { label: '已完成', icon: '✓' },
  error: { label: '出错', icon: '✕' },
  cancelled: { label: '已取消', icon: '○' },
};

export default function TaskCard({ task, onClick }: TaskCardProps) {
  const { label: statusLabel, icon: statusIcon } = statusConfig[task.status] || statusConfig.completed;
  const isRunning = task.status === 'running';

  return (
    <div className="task-card-v2" onClick={onClick}>
      {/* 左侧：状态指示器 */}
      <div className={`task-status-badge ${task.status}`}>
        <span className="task-status-icon">{statusIcon}</span>
      </div>

      {/* 中间：主要信息 */}
      <div className="task-main">
        <div className="task-header">
          <span className="task-title">{task.name}</span>
          <span className="task-time">{formatRelativeTime(task.started_at)}</span>
        </div>

        {/* 进度条（仅运行中显示） */}
        {isRunning && (
          <div className="task-progress">
            <div className="task-progress-bar">
              <div className="task-progress-fill" />
            </div>
          </div>
        )}

        {/* 元信息 */}
        <div className="task-footer">
          <span className={`task-status-label status-${task.status}`}>
            {statusLabel}
          </span>
          <span className="task-stat">
            <span className="task-stat-icon">⏱</span>
            {formatDuration(task.duration_ms)}
          </span>
          <span className="task-stat">
            <span className="task-stat-icon">📝</span>
            {task.step_count} 步
          </span>
          {task.tool_call_count > 0 && (
            <span className="task-stat">
              <span className="task-stat-icon">🔧</span>
              {task.tool_call_count} 调用
            </span>
          )}
        </div>
      </div>

      {/* 右侧：箭头 */}
      <div className="task-arrow">›</div>
    </div>
  );
}
