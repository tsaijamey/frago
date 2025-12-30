/**
 * Appearance Settings Component
 * Language and behavior settings for the application
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import type { Language } from '@/types/pywebview';

export default function AppearanceSettings() {
  const { t } = useTranslation();
  const { config, updateConfig, setLanguage } = useAppStore();

  if (!config) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        {t('common.loadingConfiguration')}
      </div>
    );
  }

  const handleToggle = (key: keyof typeof config, value: boolean) => {
    updateConfig({ [key]: value });
  };

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

      {/* Behavior settings */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          {t('settings.appearance.behavior')}
        </h2>

        {/* Show system status */}
        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">{t('settings.appearance.showSystemStatus')}</div>
            <div className="text-sm text-[var(--text-muted)]">
              {t('settings.appearance.showSystemStatusDesc')}
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.show_system_status}
              onChange={(e) =>
                handleToggle('show_system_status', e.target.checked)
              }
              className="sr-only peer"
              aria-label={t('settings.appearance.showSystemStatus')}
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>

        {/* Exit confirmation */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">{t('settings.appearance.exitConfirmation')}</div>
            <div className="text-sm text-[var(--text-muted)]">
              {t('settings.appearance.exitConfirmationDesc')}
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.confirm_on_exit}
              onChange={(e) => handleToggle('confirm_on_exit', e.target.checked)}
              className="sr-only peer"
              aria-label={t('settings.appearance.exitConfirmation')}
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>

        {/* Auto scroll */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">{t('settings.appearance.autoScrollOutput')}</div>
            <div className="text-sm text-[var(--text-muted)]">
              {t('settings.appearance.autoScrollOutputDesc')}
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.auto_scroll_output}
              onChange={(e) =>
                handleToggle('auto_scroll_output', e.target.checked)
              }
              className="sr-only peer"
              aria-label={t('settings.appearance.autoScrollOutput')}
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>
      </div>
    </div>
  );
}
