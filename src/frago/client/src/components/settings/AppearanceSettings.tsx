/**
 * Appearance Settings Component
 *
 * Interface language, and the language agents reply in. The "behavior" card that used to sit below it held three
 * switches — show system status, confirm on exit, auto-scroll output — carried
 * over from when frago ran as a desktop app. Every one of them saved and read
 * back correctly and changed nothing: their twenty-seven references across the
 * server were all schema and request mapping, with no consumer anywhere. There
 * is no status bar to show CPU in and no window to confirm closing, so they were
 * three levers wired to nothing, and the whole card is gone.
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import type { AgentLanguage, Language } from '@/types/pywebview';

// Each language is named in itself, so whoever reads it can find their own.
const AGENT_LANGUAGES: { value: Exclude<AgentLanguage, ''>; name: string }[] = [
  { value: 'en', name: 'English' },
  { value: 'zh-Hans', name: '简体中文' },
  { value: 'zh-Hant', name: '繁體中文' },
  { value: 'de', name: 'Deutsch' },
  { value: 'fr', name: 'Français' },
  { value: 'es', name: 'Español' },
  { value: 'ja', name: '日本語' },
];

// Left unchosen, agents follow the interface language (see agent_language.py).
const FOLLOW_INTERFACE: Record<Language, Exclude<AgentLanguage, ''>> = {
  en: 'en',
  zh: 'zh-Hans',
};

export default function AppearanceSettings() {
  const { t } = useTranslation();
  const { config, setLanguage, updateConfig } = useAppStore();

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

  const handleAgentLanguageChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    updateConfig({ agent_language: e.target.value as AgentLanguage });
  };

  const followed = FOLLOW_INTERFACE[config.language || 'en'];
  const followedName = AGENT_LANGUAGES.find((l) => l.value === followed)?.name ?? 'English';
  const selectClass =
    'px-3 py-1.5 rounded-md bg-[var(--bg-subtle)] border border-[var(--border-color)] text-[var(--text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]';

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
            className={selectClass}
            aria-label={t('settings.appearance.language')}
          >
            <option value="en">{t('settings.appearance.english')}</option>
            <option value="zh">{t('settings.appearance.chinese')}</option>
          </select>
        </div>

        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">{t('settings.appearance.agentLanguage')}</div>
            <div className="text-sm text-[var(--text-muted)]">
              {t('settings.appearance.agentLanguageDesc')}
            </div>
          </div>
          <select
            id="agent-language-select"
            value={config.agent_language || ''}
            onChange={handleAgentLanguageChange}
            className={selectClass}
            aria-label={t('settings.appearance.agentLanguage')}
          >
            <option value="">
              {t('settings.appearance.agentLanguageFollow', { name: followedName })}
            </option>
            {AGENT_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.name}
              </option>
            ))}
          </select>
        </div>
      </div>

    </div>
  );
}
