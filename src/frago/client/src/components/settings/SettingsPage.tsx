/**
 * SettingsPage — category-tab layout.
 *
 * The old layout stacked every settings section in one tall column, forcing a
 * huge top-to-bottom scroll. Here a left category rail switches the right panel
 * so only one section renders at a time, bounding the vertical span by the
 * tallest single category. Styling matches the Claude Sessions page tokens.
 */

import { useEffect, useState } from 'react';
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
import PageHeader from '@/components/layout/PageHeader';
import { getInitStatus } from '../../api/client';

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

  // 页头的计数写正在跑的 frago 版本。取的是 About 面板已在用的初始化状态接口，
  // 不另开接口；取不到就不写，页头只剩标题。
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    getInitStatus()
      .then((status) => {
        if (alive) setVersion(status.current_frago_version || null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return (
    /* 页头补回来了，跟其余几页同一条 52px 的统一页头：标题「Settings」加版本号，只有一行。
       从前去掉它，是因为那一版页头是大标题压一句「配置 frago 功能」，占掉七十多像素又没说
       什么；统一页头没有第二行，这个理由不在了，而少了它，这一页是全站唯一顶上没有名字的。 */
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title={t('settings.title')}
        meta={version ? t('settings.headerMeta', { version }) : undefined}
      />
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
    </div>
  );
}
