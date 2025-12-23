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
      <div className="page-scroll" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner" />
      </div>
    );
  }

  return (
    <div className="page-scroll" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Header */}
      <div>
        <h1 style={{ fontSize: '24px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
          Dashboard
        </h1>
        <p style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>
          System overview and quick access to your resources
        </p>
      </div>

      {/* Stats Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '16px' }}>
        {/* Server Status */}
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                background: data?.server.running ? 'rgba(63, 185, 80, 0.15)' : 'rgba(248, 81, 73, 0.15)',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Server size={20} style={{ color: data?.server.running ? 'var(--accent-success)' : 'var(--accent-error)' }} />
            </div>
          </div>
          <div style={{ fontSize: '24px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            {data?.server.running ? 'Online' : 'Offline'}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <Clock size={12} />
            {data?.server.uptime_seconds ? formatUptime(data.server.uptime_seconds) : '--'}
          </div>
        </div>

        {/* Tasks Count */}
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
            cursor: 'pointer',
          }}
          onClick={() => switchPage('tasks')}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                background: 'rgba(88, 166, 255, 0.15)',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <ListTodo size={20} style={{ color: '#58a6ff' }} />
            </div>
          </div>
          <div style={{ fontSize: '24px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            {data?.resource_counts.tasks ?? 0}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Tasks</div>
        </div>

        {/* Recipes Count */}
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
            cursor: 'pointer',
          }}
          onClick={() => switchPage('recipes')}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                background: 'rgba(210, 153, 34, 0.15)',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <BookOpen size={20} style={{ color: 'var(--accent-warning)' }} />
            </div>
          </div>
          <div style={{ fontSize: '24px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            {data?.resource_counts.recipes ?? 0}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Recipes</div>
        </div>

        {/* Skills Count */}
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
            cursor: 'pointer',
          }}
          onClick={() => switchPage('skills')}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                background: 'rgba(139, 92, 246, 0.15)',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Zap size={20} style={{ color: '#8b5cf6' }} />
            </div>
          </div>
          <div style={{ fontSize: '24px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            {data?.resource_counts.skills ?? 0}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Skills</div>
        </div>
      </div>

      {/* Recent Activity & Quick Actions Row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: '16px' }}>
        {/* Recent Activity */}
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity size={18} />
              Recent Activity
            </h2>
            <button
              onClick={() => switchPage('tasks')}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: '13px',
              }}
            >
              View all <ChevronRight size={14} />
            </button>
          </div>

          {data?.recent_activity && data.recent_activity.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {data.recent_activity.map((activity) => (
                <div
                  key={activity.id}
                  onClick={() => switchPage('task_detail', activity.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '12px',
                    background: 'var(--bg-tertiary)',
                    borderRadius: '8px',
                    cursor: 'pointer',
                  }}
                >
                  <div
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background:
                        activity.status === 'completed' ? 'var(--accent-success)' :
                        activity.status === 'running' ? 'var(--accent-warning)' :
                        activity.status === 'error' ? 'var(--accent-error)' :
                        'var(--text-muted)',
                    }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: '13px',
                        color: 'var(--text-primary)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {activity.title}
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {formatRelativeTime(activity.timestamp)}
                    </div>
                  </div>
                  <ChevronRight size={16} style={{ color: 'var(--text-muted)' }} />
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
              No recent activity
            </div>
          )}
        </div>

        {/* Quick Actions */}
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-color)',
            borderRadius: '12px',
            padding: '20px',
          }}
        >
          <h2 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '16px' }}>
            Quick Actions
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button
              onClick={() => switchPage('tasks')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '12px 16px',
                background: 'var(--bg-tertiary)',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                textAlign: 'left',
              }}
            >
              <Plus size={18} style={{ color: 'var(--accent-primary)' }} />
              <span style={{ fontSize: '14px' }}>New Task</span>
            </button>
            <button
              onClick={() => switchPage('recipes')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '12px 16px',
                background: 'var(--bg-tertiary)',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                textAlign: 'left',
              }}
            >
              <BookOpen size={18} style={{ color: 'var(--accent-warning)' }} />
              <span style={{ fontSize: '14px' }}>Browse Recipes</span>
            </button>
            <button
              onClick={() => switchPage('skills')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '12px 16px',
                background: 'var(--bg-tertiary)',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                textAlign: 'left',
              }}
            >
              <Zap size={18} style={{ color: '#8b5cf6' }} />
              <span style={{ fontSize: '14px' }}>View Skills</span>
            </button>
            <button
              onClick={() => switchPage('settings')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '12px 16px',
                background: 'var(--bg-tertiary)',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                color: 'var(--text-primary)',
                textAlign: 'left',
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
              </svg>
              <span style={{ fontSize: '14px' }}>Settings</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
