/**
 * Sidebar — 左侧常驻导航栏。
 *
 * **它不再是浮层。** 从前这根栏收窄成 52px 浮在内容上方，鼠标一碰就向右膨胀到 204px
 * 盖住正文。那个交互有两个毛病：鼠标只是路过就会展开，以及展开的那一片挡着的正是人
 * 正在读的东西。现在它是一根实体栏，占自己的位置，宽窄由人自己说了算，并且记住选择。
 *
 * **收起时靠 title 属性给名字，不靠悬停展开整根栏。** 认图标的成本由 tooltip 承担，
 * 不该由整块版面的位移来承担。
 *
 * **选中态是中性填充，不是品牌色。** 品牌绿在整个界面上只出现在四个位置：主动作按钮、
 * 焦点环、「在跑」这一档活跃状态、发送键。拿它标「你在哪一页」的话，一进页面就有一块
 * 绿常亮着，真正需要被看见的东西反而没有地方可去。
 *
 * **底部是这根栏的另一头。** logo 在顶，外观与运行状态在底——深浅色切换的入口就在这里。
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  MessageSquare,
  LayoutGrid,
  Database,
  ListChecks,
  Settings,
  PanelLeft,
  Monitor,
  Moon,
  Sun,
} from 'lucide-react';
import { useAppStore, type PageType } from '@/stores/appStore';

export interface RailItem {
  id: PageType;
  label: string;
  icon: React.ReactNode;
}

/** 图标尺寸与线宽全局只有这一处。16px / 1.5 是整套界面的默认。 */
const ICON = { size: 16, strokeWidth: 1.5 } as const;

export const NAV_ITEMS: RailItem[] = [
  // 会话只有一个入口。`session_workbench` 是内部页面代号，导航上一律叫 sessions。
  { id: 'session_workbench', label: 'sessions', icon: <MessageSquare {...ICON} /> },
  { id: 'recipes', label: 'recipes', icon: <LayoutGrid {...ICON} /> },
  // 事务清单：`frago todo` 的待办不走配方，只能自己开一页，所以它在导航上自成一项。
  { id: 'todos', label: 'todos', icon: <ListChecks {...ICON} /> },
  // 数据仓库：~/.frago 备份到用户自己的私有仓库，紧跟在 recipes 后面。
  { id: 'data_repo', label: 'data', icon: <Database {...ICON} /> },
];

/* 这一项显示的字从前是 config。旁边四项（sessions / recipes / todos / data）
   写的都是那件东西的正常叫法，只有它写的是「配置文件」的意思，跟同一栏里的其余四个
   不在一个语域；而这一页从内到外——页面标识、地址栏那一段、页面自己的标题——一直都叫
   settings。收起时这颗按钮只剩一个图标，tooltip 就是它唯一的名字，所以那里跟着一起改。 */
export const CONFIG_ITEM: RailItem = {
  id: 'settings',
  label: 'settings',
  icon: <Settings {...ICON} />,
};

export function isNavItemActive(id: PageType, currentPage: PageType): boolean {
  if (id === 'session_workbench') return currentPage === 'session_workbench';
  if (id === 'recipes') return currentPage === 'recipes' || currentPage === 'recipe_detail';
  if (id === 'todos') return currentPage === 'todos' || currentPage === 'todo_detail';
  if (id === 'data_repo') return currentPage === 'data_repo';
  if (id === 'settings') return currentPage === 'settings';
  return false;
}

const EXPANDED_KEY = 'sidebar-expanded';

/** 展开与否是人的选择，跨会话记住。读不到就按收起算——窄的那一档不会挡住任何东西。 */
function readExpanded(): boolean {
  try {
    return localStorage.getItem(EXPANDED_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * 外观与状态。深浅色切换的入口在这里——左下角，与 logo 分居这根栏的两头。
 *
 * 切换本身是一个两档的分段控件，而不是一颗会变形的按钮：变形按钮上写的是「点了会变成
 * 什么」，人得先想一步才知道现在是哪一档；分段控件上写的是「现在是哪一档」，一眼就够。
 */
function AppearanceMenu({ expanded }: { expanded: boolean }) {
  const { t } = useTranslation();
  const { config, setTheme, systemStatus } = useAppStore();
  const [open, setOpen] = useState(false);
  const theme = config?.theme === 'light' ? 'light' : 'dark';
  const isRunning = systemStatus?.cpu_percent !== undefined;

  // 点到别处就收起来。浮层自己不该赖着不走。
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest('.rail-foot')) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <div className="rail-foot">
      {open ? (
        <div className="rail-popover" role="dialog" aria-label={t('sidebar.appearance.label')}>
          <div className="rail-popover-row">
            <span className="rail-popover-label">{t('sidebar.appearance.label')}</span>
            <div className="rail-seg" role="group" aria-label={t('sidebar.appearance.group')}>
              <button
                type="button"
                className={`rail-seg-item ${theme === 'light' ? 'is-on' : ''}`}
                aria-pressed={theme === 'light'}
                onClick={() => setTheme('light')}
              >
                <Sun size={13} strokeWidth={1.5} />
                {t('sidebar.appearance.light')}
              </button>
              <button
                type="button"
                className={`rail-seg-item ${theme === 'dark' ? 'is-on' : ''}`}
                aria-pressed={theme === 'dark'}
                onClick={() => setTheme('dark')}
              >
                <Moon size={13} strokeWidth={1.5} />
                {t('sidebar.appearance.dark')}
              </button>
            </div>
          </div>

          <div className="rail-popover-row">
            <span className="rail-popover-label">{t('sidebar.engine.label')}</span>
            <span className="rail-popover-value">
              <span className={`rail-dot ${isRunning ? 'is-on' : ''}`} />
              {isRunning ? t('sidebar.engine.running') : t('sidebar.engine.idle')}
            </span>
          </div>
        </div>
      ) : null}

      <button
        type="button"
        className={`rail-item ${open ? 'rail-item--active' : ''}`}
        onClick={() => setOpen((v) => !v)}
        title={t('sidebar.appearance.trigger')}
        aria-expanded={open}
      >
        <span className="rail-item-icon">
          <Monitor {...ICON} />
        </span>
        {expanded ? <span className="rail-item-label">{t('sidebar.appearance.label')}</span> : null}
        {/* 收起时状态点贴在图标角上——那一档是这根栏底部唯一还需要报的事实。 */}
        <span className={`rail-item-badge ${isRunning ? 'is-on' : ''}`} aria-hidden="true" />
      </button>
    </div>
  );
}

export default function Sidebar() {
  const { t } = useTranslation();
  const { currentPage, switchPage } = useAppStore();
  const [expanded, setExpanded] = useState(readExpanded);

  const toggle = () => {
    setExpanded((v) => {
      const next = !v;
      try {
        localStorage.setItem(EXPANDED_KEY, next ? '1' : '0');
      } catch {
        // 存不下就只影响下次打开时的初始宽度，本次仍然照常展开
      }
      return next;
    });
  };

  const isActive = (id: PageType) => isNavItemActive(id, currentPage);

  const renderItem = (item: RailItem) => (
    <button
      key={item.id}
      type="button"
      className={`rail-item ${isActive(item.id) ? 'rail-item--active' : ''}`}
      onClick={() => switchPage(item.id)}
      title={item.label}
      aria-current={isActive(item.id) ? 'page' : undefined}
    >
      <span className="rail-item-icon">{item.icon}</span>
      {expanded ? <span className="rail-item-label">{item.label}</span> : null}
    </button>
  );

  return (
    <nav className={`rail ${expanded ? 'rail--expanded' : ''}`} aria-label="Primary">
      <div className="rail-head">
        <img src="/icons/logo-64.png" alt="" className="rail-logo" />
        {expanded ? <span className="rail-wordmark">frago</span> : null}
        <button
          type="button"
          className="rail-toggle"
          onClick={toggle}
          title={expanded ? t('sidebar.collapse.collapse') : t('sidebar.collapse.expand')}
          aria-label={expanded ? t('sidebar.collapse.collapse') : t('sidebar.collapse.expand')}
          aria-pressed={expanded}
        >
          <PanelLeft {...ICON} />
        </button>
      </div>

      <div className="rail-nav">{NAV_ITEMS.map(renderItem)}</div>

      <div className="rail-spacer" />

      <div className="rail-nav">{renderItem(CONFIG_ITEM)}</div>

      <AppearanceMenu expanded={expanded} />
    </nav>
  );
}
