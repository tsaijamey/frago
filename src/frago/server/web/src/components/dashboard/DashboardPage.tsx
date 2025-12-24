/**
 * DashboardPage Component
 *
 * Admin panel dashboard with:
 * - Server status and uptime
 * - Recent task activity
 * - Resource statistics (tasks, recipes, skills)
 * - Quick action shortcuts
 */

import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getDashboard } from '@/api';
import {
  Server,
  Clock,
  ListTodo,
  BookOpen,
  Zap,
  Activity,
  ChevronRight,
  Plus,
  Settings,
} from 'lucide-react';

interface DashboardData {
  server: {
    running: boolean;
    uptime_seconds: number;
    started_at: string | null;
  };
  recent_activity: Array<{
    id: string;
    type: string;
    title: string;
    status: string;
    timestamp: string;
  }>;
  resource_counts: {
    tasks: number;
    recipes: number;
    skills: number;
  };
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

function formatRelativeTime(isoString: string): string {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  if (diff < 60000) return 'just now';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function getStatusDotClass(status: string): string {
  switch (status) {
    case 'completed': return 'dashboard-activity-dot completed';
    case 'running': return 'dashboard-activity-dot running';
    case 'error': return 'dashboard-activity-dot error';
    default: return 'dashboard-activity-dot default';
  }
}

export default function DashboardPage() {
  const { switchPage } = useAppStore();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const result = await getDashboard();
        setData(result);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
    // Refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="page-scroll dashboard-loading">
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div className="page-scroll dashboard-container">
      {/* Header */}
      <div className="dashboard-header">
        <h1>Dashboard</h1>
        <p>System overview and quick access to your resources</p>
      </div>

      {/* Stats Cards */}
      <div className="dashboard-stats-grid">
        {/* Server Status */}
        <div className="dashboard-card">
          <div className="dashboard-card-icon-wrapper">
            <div className={`dashboard-card-icon ${data?.server.running ? 'success' : 'error'}`}>
              <Server size={20} className={data?.server.running ? 'text-success' : 'text-error'} />
            </div>
          </div>
          <div className="dashboard-card-value">
            {data?.server.running ? 'Online' : 'Offline'}
          </div>
          <div className="dashboard-card-label">
            <Clock size={12} />
            {data?.server.uptime_seconds ? formatUptime(data.server.uptime_seconds) : '--'}
          </div>
        </div>

        {/* Tasks Count */}
        <div className="dashboard-card clickable" onClick={() => switchPage('tasks')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon info">
              <ListTodo size={20} className="text-info" />
            </div>
          </div>
          <div className="dashboard-card-value">
            {data?.resource_counts.tasks ?? 0}
          </div>
          <div className="dashboard-card-label">Tasks</div>
        </div>

        {/* Recipes Count */}
        <div className="dashboard-card clickable" onClick={() => switchPage('recipes')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon warning">
              <BookOpen size={20} className="text-warning" />
            </div>
          </div>
          <div className="dashboard-card-value">
            {data?.resource_counts.recipes ?? 0}
          </div>
          <div className="dashboard-card-label">Recipes</div>
        </div>

        {/* Skills Count */}
        <div className="dashboard-card clickable" onClick={() => switchPage('skills')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon purple">
              <Zap size={20} className="text-purple" />
            </div>
          </div>
          <div className="dashboard-card-value">
            {data?.resource_counts.skills ?? 0}
          </div>
          <div className="dashboard-card-label">Skills</div>
        </div>
      </div>

      {/* Recent Activity & Quick Actions Row */}
      <div className="dashboard-row">
        {/* Recent Activity */}
        <div className="dashboard-card">
          <div className="dashboard-section-header">
            <h2 className="dashboard-section-title">
              <Activity size={18} />
              Recent Activity
            </h2>
            <button
              type="button"
              onClick={() => switchPage('tasks')}
              className="dashboard-view-all-btn"
            >
              View all <ChevronRight size={14} />
            </button>
          </div>

          {data?.recent_activity && data.recent_activity.length > 0 ? (
            <div className="dashboard-activity-list">
              {data.recent_activity.map((activity) => (
                <div
                  key={activity.id}
                  onClick={() => switchPage('task_detail', activity.id)}
                  className="dashboard-activity-item"
                >
                  <div className={getStatusDotClass(activity.status)} />
                  <div className="dashboard-activity-content">
                    <div className="dashboard-activity-title">
                      {activity.title}
                    </div>
                    <div className="dashboard-activity-time">
                      {formatRelativeTime(activity.timestamp)}
                    </div>
                  </div>
                  <ChevronRight size={16} className="text-muted" />
                </div>
              ))}
            </div>
          ) : (
            <div className="dashboard-empty">
              No recent activity
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div className="dashboard-card">
          <h2 className="dashboard-section-title-only">Quick Actions</h2>
          <div className="dashboard-actions-list">
            <button
              type="button"
              onClick={() => switchPage('tasks')}
              className="dashboard-action-btn"
            >
              <Plus size={18} className="text-accent" />
              <span className="dashboard-action-label">New Task</span>
            </button>
            <button
              type="button"
              onClick={() => switchPage('recipes')}
              className="dashboard-action-btn"
            >
              <BookOpen size={18} className="text-warning" />
              <span className="dashboard-action-label">Browse Recipes</span>
            </button>
            <button
              type="button"
              onClick={() => switchPage('skills')}
              className="dashboard-action-btn"
            >
              <Zap size={18} className="text-purple" />
              <span className="dashboard-action-label">View Skills</span>
            </button>
            <button
              type="button"
              onClick={() => switchPage('settings')}
              className="dashboard-action-btn"
            >
              <Settings size={18} className="text-muted" />
              <span className="dashboard-action-label">Settings</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
