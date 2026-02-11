/**
 * RecentTasks — shows recently completed/failed tasks.
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { Clock, ChevronRight, AlertCircle } from 'lucide-react';
import type { RecentTaskSummary } from '@/api/client';

function formatDuration(ms: number | null): string {
  if (ms == null) return '--';
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${minutes}m ${secs}s`;
}

function formatTimeAgo(isoString: string | null): string {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

interface Props {
  tasks: RecentTaskSummary[];
}

export default function RecentTasks({ tasks }: Props) {
  const { t } = useTranslation();
  const { switchPage, openTaskDetail } = useAppStore();

  if (tasks.length === 0) {
    return (
      <div className="dashboard-card">
        <h2 className="dashboard-section-title-only">
          {t('dashboard.recentTasks')}
        </h2>
        <div className="dashboard-empty">{t('dashboard.noRecentTasks')}</div>
      </div>
    );
  }

  return (
    <div className="dashboard-card">
      <div className="dashboard-section-header">
        <h2 className="dashboard-section-title">
          <Clock size={16} />
          {t('dashboard.recentTasks')}
        </h2>
        <button
          type="button"
          onClick={() => switchPage('tasks')}
          className="dashboard-view-all-btn"
        >
          {t('dashboard.viewAll')} <ChevronRight size={14} />
        </button>
      </div>
      <div className="dashboard-activity-list">
        {tasks.map((task) => {
          const dotClass =
            task.status === 'completed'
              ? 'completed'
              : task.status === 'error'
                ? 'error'
                : 'default';
          return (
            <div
              key={task.id}
              className="dashboard-activity-item"
              onClick={() => openTaskDetail(task.id)}
            >
              <div className={`dashboard-activity-dot ${dotClass}`} />
              <div className="dashboard-activity-content">
                <div className="dashboard-activity-title">
                  {task.name || t('dashboard.untitledTask')}
                </div>
                <div className="dashboard-activity-time">
                  {formatTimeAgo(task.ended_at)}
                  {task.duration_ms != null && ` · ${formatDuration(task.duration_ms)}`}
                </div>
              </div>
              {task.error_summary && (
                <span title={task.error_summary}>
                  <AlertCircle size={14} className="text-error" />
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
