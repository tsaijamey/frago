/**
 * StatusBar — system status footer for dashboard.
 *
 * Shows: Chrome status, tab count, error count, last synced time.
 */

import { useTranslation } from 'react-i18next';
import { Chrome, Layers, AlertTriangle, RefreshCw } from 'lucide-react';
import type { DashboardStatus } from '@/api/client';

function formatTimeAgo(isoString: string | null): string {
  if (!isoString) return '--';
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
  status: DashboardStatus;
}

export default function StatusBar({ status }: Props) {
  const { t } = useTranslation();

  return (
    <div className="dashboard-status-bar">
      <div className="dashboard-status-item">
        <Chrome size={14} />
        <span className={status.chrome_connected ? 'text-success' : 'text-muted'}>
          {status.chrome_connected ? t('dashboard.chromeConnected') : t('dashboard.chromeDisconnected')}
        </span>
      </div>
      {status.tab_count > 0 && (
        <div className="dashboard-status-item">
          <Layers size={14} />
          <span>{status.tab_count} {t('dashboard.tabs')}</span>
        </div>
      )}
      {status.error_count > 0 && (
        <div className="dashboard-status-item text-error">
          <AlertTriangle size={14} />
          <span>{status.error_count} {t('dashboard.errorsRecent')}</span>
        </div>
      )}
      <div className="dashboard-status-item">
        <RefreshCw size={14} />
        <span>{t('dashboard.lastSynced')}: {formatTimeAgo(status.last_synced_at)}</span>
      </div>
    </div>
  );
}
