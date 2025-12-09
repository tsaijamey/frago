import type { TaskItem, TaskStatus } from '@/types/pywebview.d';

interface TaskCardProps {
  task: TaskItem;
  onClick: () => void;
}

// 格式化时间
function formatTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  // 小于 1 分钟
  if (diff < 60000) {
    return '刚刚';
  }

  // 小于 1 小时
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000);
    return `${minutes} 分钟前`;
  }

  // 小于 24 小时
  if (diff < 86400000) {
    const hours = Math.floor(diff / 3600000);
    return `${hours} 小时前`;
  }

  // 显示日期
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// 格式化持续时间
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

// 状态标签
function getStatusLabel(status: TaskStatus): string {
  switch (status) {
    case 'running':
      return '进行中';
    case 'completed':
      return '已完成';
    case 'error':
      return '出错';
    case 'cancelled':
      return '已取消';
    default:
      return status;
  }
}

export default function TaskCard({ task, onClick }: TaskCardProps) {
  return (
    <div className="task-card" onClick={onClick}>
      <div className={`task-status-indicator ${task.status}`} />
      <div className="task-info">
        <div className="task-name">{task.name}</div>
        <div className="task-meta">
          <span className={`status-${task.status}`}>
            {getStatusLabel(task.status)}
          </span>
          <span>{formatTime(task.started_at)}</span>
          <span>{formatDuration(task.duration_ms)}</span>
          <span>{task.step_count} 步骤</span>
        </div>
      </div>
    </div>
  );
}
