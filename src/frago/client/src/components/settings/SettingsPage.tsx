/**
 * SettingsPage — category-tab layout.
 *
 * The old layout stacked every settings section in one tall column, forcing a
 * huge top-to-bottom scroll. Here a left category rail switches the right panel
 * so only one section renders at a time, bounding the vertical span by the
 * tallest single category. Styling matches the Claude Sessions page tokens.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  KeyRound,
  Inbox,
  RefreshCw,
  Palette,
  Rocket,
  Info,
  type LucideIcon,
} from 'lucide-react';

import GeneralSettings from './GeneralSettings';
import AppearanceSettings from './AppearanceSettings';
import AboutSettings from './AboutSettings';
import { InitSettings } from './InitSettings';
import TaskIngestionPanel from './TaskIngestionPanel';
import OfficialResourceSettings from './OfficialResourceSettings';

interface SettingsPageProps {
  onOpenInitWizard?: () => void;
}

type TabId = 'general' | 'channels' | 'resources' | 'appearance' | 'init' | 'about';

interface TabDef {
  id: TabId;
  Icon: LucideIcon;
  render: (props: SettingsPageProps) => JSX.Element;
}

const TABS: TabDef[] = [
  { id: 'general', Icon: KeyRound, render: () => <GeneralSettings /> },
  { id: 'channels', Icon: Inbox, render: () => <TaskIngestionPanel /> },
  { id: 'resources', Icon: RefreshCw, render: () => <OfficialResourceSettings /> },
  { id: 'appearance', Icon: Palette, render: () => <AppearanceSettings /> },
  {
    id: 'init',
    Icon: Rocket,
    render: ({ onOpenInitWizard }) => (
      <InitSettings onOpenWizard={onOpenInitWizard || (() => {})} />
    ),
  },
  { id: 'about', Icon: Info, render: () => <AboutSettings /> },
];

export default function SettingsPage({ onOpenInitWizard }: SettingsPageProps) {
  const { t } = useTranslation();
  const [active, setActive] = useState<TabId>('general');

  const activeTab = TABS.find((tab) => tab.id === active) ?? TABS[0];

  return (
    <div className="page-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-md)' }}>
      {/* Header */}
      <div className="cs-header">
        <div>
          <h1 className="cs-title">{t('settings.title')}</h1>
          <p className="cs-subtitle">{t('settings.description')}</p>
        </div>
      </div>

      {/* Two-column: category rail + active panel */}
      <div className="settings-layout">
        <nav className="settings-nav" aria-label={t('settings.title')}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`settings-nav-item ${tab.id === active ? 'active' : ''}`}
              onClick={() => setActive(tab.id)}
            >
              <tab.Icon size={16} className="settings-nav-icon" />
              <span className="settings-nav-text">
                <span className="settings-nav-label">{t(`settings.tabs.${tab.id}`)}</span>
                <span className="settings-nav-desc">{t(`settings.tabDesc.${tab.id}`)}</span>
              </span>
            </button>
          ))}
        </nav>

        <section className="settings-panel">
          <div className="settings-panel-head">
            <activeTab.Icon size={18} className="text-[var(--accent-primary)]" />
            <div>
              <h2 className="settings-panel-title">{t(`settings.tabs.${active}`)}</h2>
              <p className="settings-panel-desc">{t(`settings.tabDesc.${active}`)}</p>
            </div>
          </div>
          <div className="settings-panel-body">
            {activeTab.render({ onOpenInitWizard })}
          </div>
        </section>
      </div>
    </div>
  );
}
