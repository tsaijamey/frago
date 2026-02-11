/**
 * QuickActionBar — top action buttons for dashboard.
 *
 * Provides quick access to: New Task, Run Recipe, Sync.
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { Plus, Play, RefreshCw } from 'lucide-react';

export default function QuickActionBar() {
  const { t } = useTranslation();
  const { switchPage } = useAppStore();

  return (
    <div className="dashboard-quick-actions">
      <button
        type="button"
        className="dashboard-action-btn primary"
        onClick={() => switchPage('newTask')}
      >
        <Plus size={16} />
        {t('dashboard.newTask')}
      </button>
      <button
        type="button"
        className="dashboard-action-btn"
        onClick={() => switchPage('recipes')}
      >
        <Play size={16} />
        {t('dashboard.runRecipe')}
      </button>
      <button
        type="button"
        className="dashboard-action-btn"
        onClick={() => switchPage('sync')}
      >
        <RefreshCw size={16} />
        {t('dashboard.syncNow')}
      </button>
    </div>
  );
}
