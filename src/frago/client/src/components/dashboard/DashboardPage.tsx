/**
 * DashboardPage Component — Workbench Dashboard
 *
 * Redesigned from DevOps monitoring to user-facing workbench:
 * - Quick action bar (New Task, Run Recipe, Sync)
 * - Running tasks (real-time)
 * - Recent tasks
 * - Quick recipes (sorted by recent usage)
 * - Resource counts
 * - System status bar
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getDashboard } from '@/api';
import { ListTodo, BookOpen, Zap } from 'lucide-react';
import QuickActionBar from './QuickActionBar';
import RunningTasks from './RunningTasks';
import RecentTasks from './RecentTasks';
import QuickRecipes from './QuickRecipes';
import StatusBar from './StatusBar';

export default function DashboardPage() {
  const { t } = useTranslation();
  const { switchPage, dashboard, setDashboard } = useAppStore();

  useEffect(() => {
    // Initial fetch (WebSocket pushes handle subsequent updates)
    const fetchData = async () => {
      try {
        const result = await getDashboard();
        setDashboard(result);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      }
    };

    if (!dashboard) {
      fetchData();
    }

    // Refresh every 60s as fallback
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [dashboard, setDashboard]);

  return (
    <div className="page-scroll dashboard-container">
      {/* Header */}
      <div className="dashboard-header">
        <h1>{t('dashboard.title')}</h1>
        <p>{t('dashboard.pageDesc')}</p>
      </div>

      {/* Quick Action Bar */}
      <QuickActionBar />

      {/* Running Tasks */}
      <RunningTasks tasks={dashboard?.running_tasks ?? []} />

      {/* Two-column layout: Recent Tasks + Quick Recipes */}
      <div className="dashboard-two-col">
        <RecentTasks tasks={dashboard?.recent_tasks ?? []} />
        <QuickRecipes recipes={dashboard?.quick_recipes ?? []} />
      </div>

      {/* Resource Counts */}
      <div className="dashboard-stats-grid">
        <div className="dashboard-card clickable" onClick={() => switchPage('tasks')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon info">
              <ListTodo size={20} className="text-info" />
            </div>
            <span className="dashboard-card-icon-label">{t('dashboard.tasks')}</span>
          </div>
          <div className="dashboard-card-value">
            {dashboard?.resource_counts.tasks ?? 0}
          </div>
        </div>

        <div className="dashboard-card clickable" onClick={() => switchPage('recipes')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon warning">
              <BookOpen size={20} className="text-warning" />
            </div>
            <span className="dashboard-card-icon-label">{t('dashboard.recipes')}</span>
          </div>
          <div className="dashboard-card-value">
            {dashboard?.resource_counts.recipes ?? 0}
          </div>
        </div>

        <div className="dashboard-card clickable" onClick={() => switchPage('skills')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon purple">
              <Zap size={20} className="text-purple" />
            </div>
            <span className="dashboard-card-icon-label">{t('dashboard.skills')}</span>
          </div>
          <div className="dashboard-card-value">
            {dashboard?.resource_counts.skills ?? 0}
          </div>
        </div>
      </div>

      {/* Status Bar */}
      {dashboard?.system_status && (
        <StatusBar status={dashboard.system_status} />
      )}
    </div>
  );
}
