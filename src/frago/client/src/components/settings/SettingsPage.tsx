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
  Sparkles,
  type LucideIcon,
} from 'lucide-react';

import GeneralSettings from './GeneralSettings';
import AppearanceSettings from './AppearanceSettings';
import AboutSettings from './AboutSettings';
import { InitSettings } from './InitSettings';
import TaskIngestionPanel from './TaskIngestionPanel';
import OfficialResourceSettings from './OfficialResourceSettings';
import PromptCapabilitySettings from './PromptCapabilitySettings';

interface SettingsPageProps {
  onOpenInitWizard?: () => void;
}

type TabId = 'capability' | 'general' | 'channels' | 'resources' | 'appearance' | 'init' | 'about';

/** What each panel gets to render with — page props plus the cross-panel wiring. */
interface PanelContext extends SettingsPageProps {
  /** Jump to the model-profile editor, which lives in the general panel. */
  onConfigureProfile: () => void;
  /** Bumped each time that jump happens, so the general panel can open its
   *  profile dialog on arrival instead of leaving the user to find it. */
  profileSignal: number;
}

interface TabDef {
  id: TabId;
  Icon: LucideIcon;
  render: (ctx: PanelContext) => JSX.Element;
}

// Capability leads, and is the default panel: the settings page's first answer
// should be "is frago working right now", not "here is a pile to manage".
const TABS: TabDef[] = [
  {
    id: 'capability',
    Icon: Sparkles,
    render: ({ onConfigureProfile }) => (
      <PromptCapabilitySettings onConfigureProfile={onConfigureProfile} />
    ),
  },
  {
    id: 'general',
    Icon: KeyRound,
    render: ({ profileSignal }) => <GeneralSettings openProfilesSignal={profileSignal} />,
  },
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
  const [active, setActive] = useState<TabId>('capability');
  const [profileSignal, setProfileSignal] = useState(0);

  const handleConfigureProfile = () => {
    setProfileSignal((n) => n + 1);
    setActive('general');
  };

  const activeTab = TABS.find((tab) => tab.id === active) ?? TABS[0];

  return (
    /* 页面自己的标题去掉了。左侧主导航上「config」那一项已经亮着，右侧面板的标题又写着
       分类名——中间再夹一个「设置 / 配置 frago 功能」，是同一件事说第三遍，
       还把真正的内容往下推了七十多像素。 */
    <div className="page-scroll">
      <div className="settings-layout">
        <nav className="settings-nav" aria-label={t('settings.title')}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`settings-nav-item ${tab.id === active ? 'active' : ''}`}
              onClick={() => setActive(tab.id)}
              /* 描述搬到了右侧面板的标题下面。这里留一份 title，
                 鼠标停住时仍然读得到，不必先点进去才知道这一项管什么。 */
              title={t(`settings.tabDesc.${tab.id}`)}
              aria-current={tab.id === active ? 'true' : undefined}
            >
              <tab.Icon size={16} strokeWidth={1.5} className="settings-nav-icon" />
              <span className="settings-nav-label">{t(`settings.tabs.${tab.id}`)}</span>
            </button>
          ))}
        </nav>

        <section className="settings-panel">
          <div className="settings-panel-head">
            <h2 className="settings-panel-title">{t(`settings.tabs.${active}`)}</h2>
            <p className="settings-panel-desc">{t(`settings.tabDesc.${active}`)}</p>
          </div>
          <div className="settings-panel-body">
            {activeTab.render({
              onOpenInitWizard,
              onConfigureProfile: handleConfigureProfile,
              profileSignal,
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
