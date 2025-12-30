/**
 * Sync Page Component
 * Standalone page for multi-device sync configuration
 */

import { useTranslation } from 'react-i18next';
import SyncSettings from '@/components/settings/SyncSettings';

export default function SyncPage() {
  const { t } = useTranslation();

  return (
    <div className="h-full overflow-auto">
      <div className="page-scroll p-4 max-w-2xl mx-auto space-y-6">
        {/* Page title */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">{t('sync.title')}</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            {t('sync.pageDesc')}
          </p>
        </div>

        {/* Sync settings content */}
        <section>
          <SyncSettings />
        </section>
      </div>
    </div>
  );
}
