/**
 * RunningTasks — shows currently running tasks with live elapsed time.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { Loader, ChevronRight } from 'lucide-react';
import type { RunningTaskSummary } from '@/api/client';

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

interface Props {
  tasks: RunningTaskSummary[];
}

export default function RunningTasks({ tasks }: Props) {
  const { t } = useTranslation();
  const { switchPage, openTaskDetail } = useAppStore();
  const [tick, setTick] = useState(0);

  // Tick every second to update elapsed times
  useEffect(() => {
    if (tasks.length === 0) return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [tasks.length]);

  if (tasks.length === 0) return null;

  return (
    <div className="dashboard-card">
      <div className="dashboard-section-header">
        <h2 className="dashboard-section-title">
          <Loader size={16} className="spinning" />
          {t('dashboard.runningTasks')} ({tasks.length})
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
        {tasks.map((task) => (
          <div
            key={task.id}
            className="dashboard-activity-item"
            onClick={() => openTaskDetail(task.id)}
          >
            <div className="dashboard-activity-dot running" />
            <div className="dashboard-activity-content">
              <div className="dashboard-activity-title">
                {task.name || t('dashboard.untitledTask')}
              </div>
              <div className="dashboard-activity-time">
                {formatElapsed(task.elapsed_seconds + tick)}
                {task.current_step && ` · ${task.current_step}`}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
