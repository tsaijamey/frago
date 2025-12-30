/**
 * DashboardPage Component
 *
 * Admin panel dashboard with:
 * - Server status and uptime
 * - Activity overview (6-hour line chart and stats)
 * - Resource statistics (tasks, recipes, skills)
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getDashboard, DashboardData, HourlyActivity } from '@/api';
import {
  Server,
  Clock,
  ListTodo,
  BookOpen,
  Zap,
  Activity,
  ChevronRight,
  CheckCircle,
  AlertCircle,
  Wrench,
} from 'lucide-react';

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

function formatHourLabel(isoString: string): string {
  const date = new Date(isoString);
  return date.getHours().toString().padStart(2, '0') + ':00';
}

interface LineChartProps {
  data: HourlyActivity[];
  height?: number;
}

function ActivityLineChart({ data, height = 200 }: LineChartProps) {
  const padding = { top: 20, right: 20, bottom: 40, left: 45 };
  const width = 900;
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const maxValue = Math.max(1, ...data.map(d => d.session_count));
  const yTicks = [0, Math.ceil(maxValue / 2), maxValue];

  // Calculate points for session_count line
  const points = data.map((d, i) => {
    const x = padding.left + (i / (data.length - 1)) * chartWidth;
    const y = padding.top + chartHeight - (d.session_count / maxValue) * chartHeight;
    return { x, y, data: d };
  });

  // Create SVG path for the line
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');

  // Create area path (fill below line)
  const areaPath = `${linePath} L ${points[points.length - 1].x} ${padding.top + chartHeight} L ${points[0].x} ${padding.top + chartHeight} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="activity-line-chart"
      preserveAspectRatio="none"
    >
      {/* Grid lines */}
      {yTicks.map((tick) => {
        const y = padding.top + chartHeight - (tick / maxValue) * chartHeight;
        return (
          <g key={tick}>
            <line
              x1={padding.left}
              y1={y}
              x2={width - padding.right}
              y2={y}
              className="chart-grid-line"
            />
            <text
              x={padding.left - 10}
              y={y + 4}
              className="chart-axis-label"
              textAnchor="end"
            >
              {tick}
            </text>
          </g>
        );
      })}

      {/* X axis line */}
      <line
        x1={padding.left}
        y1={padding.top + chartHeight}
        x2={width - padding.right}
        y2={padding.top + chartHeight}
        className="chart-axis-line"
      />

      {/* Y axis line */}
      <line
        x1={padding.left}
        y1={padding.top}
        x2={padding.left}
        y2={padding.top + chartHeight}
        className="chart-axis-line"
      />

      {/* Area fill */}
      <path d={areaPath} className="chart-area" />

      {/* Line */}
      <path d={linePath} className="chart-line" fill="none" />

      {/* Data points and X labels */}
      {points.map((p, i) => (
        <g key={i}>
          {/* X axis label */}
          <text
            x={p.x}
            y={padding.top + chartHeight + 25}
            className="chart-axis-label"
            textAnchor="middle"
          >
            {formatHourLabel(p.data.hour)}
          </text>
          {/* Data point */}
          <circle
            cx={p.x}
            cy={p.y}
            r={4}
            className="chart-point"
          />
          {/* Hover area for tooltip */}
          <title>{`${formatHourLabel(p.data.hour)}: ${p.data.session_count} sessions, ${p.data.tool_call_count} tool calls`}</title>
        </g>
      ))}

      {/* Y axis title */}
      <text
        x={15}
        y={padding.top + chartHeight / 2}
        className="chart-axis-title"
        textAnchor="middle"
        transform={`rotate(-90, 15, ${padding.top + chartHeight / 2})`}
      >
        Sessions
      </text>
    </svg>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
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
        <h1>{t('dashboard.title')}</h1>
        <p>{t('dashboard.pageDesc')}</p>
      </div>

      {/* Stats Cards */}
      <div className="dashboard-stats-grid">
        {/* Server Status */}
        <div className="dashboard-card">
          <div className="dashboard-card-icon-wrapper">
            <div className={`dashboard-card-icon ${data?.server.running ? 'success' : 'error'}`}>
              <Server size={20} className={data?.server.running ? 'text-success' : 'text-error'} />
            </div>
            <span className="dashboard-card-icon-label">{t('dashboard.server')}</span>
          </div>
          <div className="dashboard-card-value">
            {data?.server.running ? t('dashboard.online') : t('dashboard.offline')}
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
            <span className="dashboard-card-icon-label">{t('dashboard.tasks')}</span>
          </div>
          <div className="dashboard-card-value">
            {data?.resource_counts.tasks ?? 0}
          </div>
        </div>

        {/* Recipes Count */}
        <div className="dashboard-card clickable" onClick={() => switchPage('recipes')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon warning">
              <BookOpen size={20} className="text-warning" />
            </div>
            <span className="dashboard-card-icon-label">{t('dashboard.recipes')}</span>
          </div>
          <div className="dashboard-card-value">
            {data?.resource_counts.recipes ?? 0}
          </div>
        </div>

        {/* Skills Count */}
        <div className="dashboard-card clickable" onClick={() => switchPage('skills')}>
          <div className="dashboard-card-icon-wrapper">
            <div className="dashboard-card-icon purple">
              <Zap size={20} className="text-purple" />
            </div>
            <span className="dashboard-card-icon-label">{t('dashboard.skills')}</span>
          </div>
          <div className="dashboard-card-value">
            {data?.resource_counts.skills ?? 0}
          </div>
        </div>
      </div>

      {/* Activity Overview - Full Width */}
      <div className="dashboard-card dashboard-card-full">
        <div className="dashboard-section-header">
          <h2 className="dashboard-section-title">
            <Activity size={18} />
            {t('dashboard.activityOverview')}
          </h2>
          <button
            type="button"
            onClick={() => switchPage('tasks')}
            className="dashboard-view-all-btn"
          >
            {t('dashboard.viewAll')} <ChevronRight size={14} />
          </button>
        </div>

        {data?.activity_overview && data.activity_overview.hourly_distribution.length > 0 ? (
          <>
            {/* Line Chart */}
            <div className="activity-chart-container">
              <ActivityLineChart
                data={data.activity_overview.hourly_distribution}
                height={220}
              />
            </div>

            {/* Stats Grid */}
            <div className="activity-stats-grid">
              <div className="activity-stat">
                <Clock size={16} className="text-info" />
                <span className="activity-stat-value">{data.activity_overview.stats.total_sessions}</span>
                <span className="activity-stat-label">{t('dashboard.sessions')}</span>
              </div>
              <div className="activity-stat">
                <Wrench size={16} className="text-warning" />
                <span className="activity-stat-value">{data.activity_overview.stats.total_tool_calls}</span>
                <span className="activity-stat-label">{t('dashboard.toolCalls')}</span>
              </div>
              <div className="activity-stat">
                <CheckCircle size={16} className="text-success" />
                <span className="activity-stat-value">{data.activity_overview.stats.completed_sessions}</span>
                <span className="activity-stat-label">{t('dashboard.completed')}</span>
              </div>
              {data.activity_overview.stats.running_sessions > 0 && (
                <div className="activity-stat">
                  <Activity size={16} className="text-warning" />
                  <span className="activity-stat-value">{data.activity_overview.stats.running_sessions}</span>
                  <span className="activity-stat-label">{t('dashboard.running')}</span>
                </div>
              )}
              {data.activity_overview.stats.error_sessions > 0 && (
                <div className="activity-stat">
                  <AlertCircle size={16} className="text-error" />
                  <span className="activity-stat-value">{data.activity_overview.stats.error_sessions}</span>
                  <span className="activity-stat-label">{t('dashboard.errors')}</span>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="dashboard-empty">
            {t('dashboard.noActivityData')}
          </div>
        )}
      </div>
    </div>
  );
}
