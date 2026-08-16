/**
 * Appearance Settings Component
 *
 * Interface language. The "behavior" card that used to sit below it held three
 * switches — show system status, confirm on exit, auto-scroll output — carried
 * over from when frago ran as a desktop app. Every one of them saved and read
 * back correctly and changed nothing: their twenty-seven references across the
 * server were all schema and request mapping, with no consumer anywhere. There
 * is no status bar to show CPU in and no window to confirm closing, so they were
 * three levers wired to nothing, and the whole card is gone.
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import type { Language } from '@/types/pywebview';

export default function AppearanceSettings() {
  const { t } = useTranslation();
  const { config, setLanguage } = useAppStore();

  if (!config) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        {t('common.loadingConfiguration')}
      </div>
    );
  }

  const handleLanguageChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setLanguage(e.target.value as Language);
  };

  return (
    <div className="space-y-4">
      {/* Language settings */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          {t('settings.appearance.language')}
        </h2>

        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">{t('settings.appearance.language')}</div>
            <div className="text-sm text-[var(--text-muted)]">
              {t('settings.appearance.languageDesc')}
            </div>
          </div>
          <select
            id="language-select"
            value={config.language || 'en'}
            onChange={handleLanguageChange}
            className="px-3 py-1.5 rounded-md bg-[var(--bg-subtle)] border border-[var(--border-color)] text-[var(--text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
            aria-label={t('settings.appearance.language')}
          >
            <option value="en">{t('settings.appearance.english')}</option>
            <option value="zh">{t('settings.appearance.chinese')}</option>
          </select>
        </div>
      </div>

    </div>
  );
}
