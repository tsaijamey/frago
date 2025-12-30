/**
 * Secrets Page Component
 * Standalone page for environment variables configuration
 */

import { useTranslation } from 'react-i18next';
import SecretsSettings from '@/components/settings/SecretsSettings';

// Shield icon for security notice
const ShieldIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

export default function SecretsPage() {
  const { t } = useTranslation();

  return (
    <div className="h-full overflow-auto">
      <div className="page-scroll p-4 max-w-2xl mx-auto space-y-6">
        {/* Page title */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">{t('secrets.title')}</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            {t('secrets.pageDesc')}
          </p>
        </div>

        {/* Security notice */}
        <div className="flex gap-3 p-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)]">
          <div className="text-[var(--accent-primary)] mt-0.5">
            <ShieldIcon />
          </div>
          <div className="text-sm text-[var(--text-secondary)] leading-relaxed">
            <p>
              {t('secrets.securityNotice')}
            </p>
          </div>
        </div>

        {/* Secrets settings content */}
        <section>
          <SecretsSettings />
        </section>
      </div>
    </div>
  );
}
