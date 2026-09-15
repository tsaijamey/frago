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
 * **底部装的是「我还剩多少」，不是设置。** 从前这里挂着一颗叫「外观与状态」的按钮，
 * 点开是一个浮层，里面两行：深浅色切换，和一行写着「引擎 · 空闲」的状态。后者说的是
 * 服务端有没有报出 CPU 数字——这件事对着屏幕的人既看不懂也用不上，去掉了。深浅色不再
 * 藏在浮层里：两颗图标直接平铺在栏底，点哪颗就是哪档，少一次点击。
 *
 * 腾出来的位置给了额度：三根细条子报本机 Claude Code 的订阅用量，旁边一颗日历图标
 * 开用量月历——两件事都是「我还剩多少」，放在一起，与顶上的 logo 分居这根栏的两头。
 */

import { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import {
  MessageSquare,
  LayoutGrid,
  Database,
  ListChecks,
  Settings,
  PanelLeft,
  CalendarDays,
  Clock,
  Gauge,
  Loader2,
  Moon,
  Sun,
  Terminal,
} from 'lucide-react';
import { useAppStore, type PageType } from '@/stores/appStore';
import { useClaudeUsage } from '@/hooks/useClaudeUsage';
import { useTmuxSessionCount } from '@/hooks/useTmuxSessions';
import { countAttention, useEnvironment, useEnvironmentUpgrade } from '@/hooks/useEnvironment';
import TokenCalendarModal from '@/components/sessionWorkbench/TokenCalendarModal';
import TmuxSessionsModal from './TmuxSessionsModal';
import EnvironmentModal from './EnvironmentModal';
import type { ClaudeUsageBucket } from '@/types/api';

export interface RailItem {
  id: PageType;
  label: string;
  icon: React.ReactNode;
}

/** 图标尺寸与线宽全局只有这一处。16px / 1.5 是整套界面的默认。 */
const ICON = { size: 16, strokeWidth: 1.5 } as const;

/* settings 这一项显示的字从前是 config。旁边四项（sessions / recipes / todos / data）
   写的都是那件东西的正常叫法，只有它写的是「配置文件」的意思，跟同一栏里的其余四个
   不在一个语域；而这一页从内到外——页面标识、地址栏那一段、页面自己的标题——一直都叫
   settings。收起时这颗按钮只剩一个图标，tooltip 就是它唯一的名字，所以那里跟着一起改。

   它现在跟在 data 后面，跟其余四项排在同一串里。从前它被一根 flex 撑杆推到栏底，
   独自占着底部那一档；底部现在装的是额度，那是另一件事，设置回到它本来的位置上。 */
export const NAV_ITEMS: RailItem[] = [
  // 会话只有一个入口。`session_workbench` 是内部页面代号，导航上一律叫 sessions。
  { id: 'session_workbench', label: 'sessions', icon: <MessageSquare {...ICON} /> },
  { id: 'recipes', label: 'recipes', icon: <LayoutGrid {...ICON} /> },
  // 事务清单：`frago todo` 的待办不走配方，只能自己开一页，所以它在导航上自成一项。
  { id: 'todos', label: 'todos', icon: <ListChecks {...ICON} /> },
  // 定时任务：`frago schedule` 由服务端的调度器执行，跟事务一样不走配方，自成一项。
  { id: 'schedules', label: 'schedules', icon: <Clock {...ICON} /> },
  // 数据仓库：~/.frago 备份到用户自己的私有仓库，紧跟在 recipes 后面。
  { id: 'data_repo', label: 'data', icon: <Database {...ICON} /> },
  { id: 'settings', label: 'settings', icon: <Settings {...ICON} /> },
];

export function isNavItemActive(id: PageType, currentPage: PageType): boolean {
  if (id === 'session_workbench') return currentPage === 'session_workbench';
  if (id === 'recipes') return currentPage === 'recipes' || currentPage === 'recipe_detail';
  if (id === 'todos') return currentPage === 'todos' || currentPage === 'todo_detail';
  if (id === 'schedules') return currentPage === 'schedules' || currentPage === 'schedule_detail';
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
 * 三档额度，三根细条子。
 *
 * 三档说的是三件事，谁也替代不了谁：本周某个型号（额度最紧的那一档，深绿）、本周全模型
 * （logo 绿）、当前五小时窗口（浅绿）。同一色系分三个深浅，是因为它们是同一件事的三个
 * 尺度；换三种色相会读成三件互不相干的事。
 *
 * 条子只报「到哪了」，具体数字与重置时间挂在 tooltip 上——栏收起时只有 40px 宽，写不下
 * 也不该写；人要看细账，旁边就是用量月历。
 */
function UsageBars({ expanded }: { expanded: boolean }) {
  const { t } = useTranslation();
  const usage = useClaudeUsage();

  if (!usage?.available) return null;

  /* 每一档有两个名字。栏里那行字只有一百来像素宽，长名一定被切掉，所以图例用短名；
     鼠标停下来时空间不要钱，tooltip 用把话说全的那个。 */
  const rows: Array<{ key: string; name: string; longName: string; bucket: ClaudeUsageBucket }> =
    [];
  if (usage.week_model) {
    // 型号的名字跟着账号走（Fable / Opus / …），照 Claude Code 报的原话显示。
    const model = usage.week_model.label ?? t('sidebar.usage.weekModel');
    rows.push({ key: 'model', name: model, longName: model, bucket: usage.week_model });
  }
  if (usage.week_all) {
    rows.push({
      key: 'all',
      name: t('sidebar.usage.weekAll'),
      longName: t('sidebar.usage.weekAllLong'),
      bucket: usage.week_all,
    });
  }
  if (usage.session) {
    rows.push({
      key: 'session',
      name: t('sidebar.usage.session'),
      longName: t('sidebar.usage.sessionLong'),
      bucket: usage.session,
    });
  }
  if (rows.length === 0) return null;

  return (
    <div
      className="rail-usage"
      role="group"
      aria-label={t('sidebar.usage.label')}
      title={rows
        .map(({ longName, bucket }) =>
          bucket.resets_at
            ? t('sidebar.usage.tooltipReset', {
                name: longName,
                percent: bucket.percent,
                reset: bucket.resets_at,
              })
            : t('sidebar.usage.tooltip', { name: longName, percent: bucket.percent })
        )
        .join('\n')}
    >
      {rows.map(({ key, longName, bucket }) => (
        <div
          key={key}
          className={`rail-usage-track rail-usage-track--${key}`}
          role="img"
          aria-label={t('sidebar.usage.tooltip', { name: longName, percent: bucket.percent })}
        >
          <span
            className="rail-usage-fill"
            style={{ width: `${Math.min(100, Math.max(0, bucket.percent))}%` }}
          />
        </div>
      ))}
      {expanded ? (
        <div className="rail-usage-legend">
          {rows.map(({ key, name, bucket }) => (
            <span key={key} className="rail-usage-legend-item">
              <i className={`rail-usage-chip rail-usage-chip--${key}`} />
              {/* 名字挤不下就自己截断，百分比永远留在行尾——那是这行字唯一非有不可的东西。 */}
              <span className="rail-usage-legend-name">{name}</span>
              <span className="rail-usage-legend-value">{bucket.percent}%</span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/**
 * 环境检查的入口，夹在额度条和深浅色那一排之间。
 *
 * 上面是「我还剩多少」，下面是「界面怎么显示」，这一颗管的是「我这台机器齐不齐」，
 * 三件事同属栏底那一档。
 *
 * 角上那个数字是「缺了的必装项 + 能升的那些」加起来的个数，没有就不显示——常年挂着
 * 一个 0 等于常年占着一块地方说「没事」。
 *
 * **升级的状态住在这里，不住在浮窗里。** 升级是关了窗还在继续的事——它跑在服务端，
 * 界面开着没开着都不影响。状态如果跟着浮窗一起销毁，人关掉窗再打开看到的是一张干净
 * 的表，只能猜刚才那下是不是断了。这根栏从进页面到离开一直在，把状态放在它手上，
 * 浮窗随时关、随时开，接回来的都是同一轮升级。
 *
 * 正在升级时图标上转起来，人不用打开浮窗也知道机器上还在装东西。
 */
function RailEnvironment({ expanded }: { expanded: boolean }) {
  const { t } = useTranslation();
  const environment = useEnvironment();
  const [open, setOpen] = useState(false);

  // 升完立刻重新问一次版本号：表上那个数字变掉，才算这次升级交付了。
  const refreshAfterUpgrade = useCallback(() => {
    void environment.reload(false);
  }, [environment]);
  const upgrade = useEnvironmentUpgrade(refreshAfterUpgrade);

  const attention = countAttention(environment.data);
  const tooltip = upgrade.busy
    ? t('envCheck.railUpgrading')
    : t('envCheck.railTooltip', { n: attention });

  return (
    <>
      <button
        type="button"
        className="rail-env"
        onClick={() => setOpen(true)}
        title={tooltip}
        aria-label={tooltip}
      >
        <span className="rail-env-icon">
          {upgrade.busy ? <Loader2 {...ICON} className="cs-spin" /> : <Gauge {...ICON} />}
          {!upgrade.busy && attention > 0 ? (
            <span className="rail-env-count">{attention}</span>
          ) : null}
        </span>
        {expanded ? (
          <span className="rail-env-label">
            {upgrade.busy ? t('envCheck.railUpgradingShort') : t('envCheck.railLabel')}
          </span>
        ) : null}
      </button>

      {/* 挂到 body 上，理由和月历那一处相同：左栏自己是一层堆叠上下文。 */}
      {open
        ? createPortal(
            <EnvironmentModal
              environment={environment}
              upgrade={upgrade}
              onClose={() => setOpen(false)}
            />,
            document.body
          )
        : null}
    </>
  );
}

/**
 * 栏底那一排图标：用量月历、浅色、深色。
 *
 * 深浅色是两颗并排的按钮而不是一颗会变形的按钮：变形按钮上写的是「点了会变成什么」，
 * 人得先想一步才知道现在是哪一档；两颗并排写的是「现在是哪一档」，一眼就够。
 */
function RailTools() {
  const { t } = useTranslation();
  const { config, setTheme } = useAppStore();
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [tmuxOpen, setTmuxOpen] = useState(false);
  const { total: tmuxTotal, totalMemoryMb } = useTmuxSessionCount();
  const theme = config?.theme === 'light' ? 'light' : 'dark';

  // Esc 关月历。它是个盖住半屏的浮层，不该只有一个关闭按钮能收。
  useEffect(() => {
    if (!calendarOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setCalendarOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [calendarOpen]);

  return (
    <div className="rail-tools">
      {/* 会话数就写在图标旁边，不做成小红点：这个数字本身要能读出来，人是照着它
          决定该不该去清理的，一个点只说「有」，说不出「几个」。 */}
      <button
        type="button"
        className="rail-tool rail-tool--count"
        onClick={() => setTmuxOpen(true)}
        title={t('tmuxSessions.railTooltip', { n: tmuxTotal, memory: totalMemoryMb })}
        aria-label={t('tmuxSessions.railTooltip', { n: tmuxTotal, memory: totalMemoryMb })}
      >
        <Terminal {...ICON} />
        <span className="rail-tool-count">{tmuxTotal}</span>
      </button>

      <button
        type="button"
        className="rail-tool"
        onClick={() => setCalendarOpen(true)}
        title={t('tokenCalendar.open')}
        aria-label={t('tokenCalendar.open')}
      >
        <CalendarDays {...ICON} />
      </button>

      <button
        type="button"
        className={`rail-tool ${theme === 'light' ? 'rail-tool--on' : ''}`}
        onClick={() => setTheme('light')}
        title={t('sidebar.appearance.light')}
        aria-label={t('sidebar.appearance.light')}
        aria-pressed={theme === 'light'}
      >
        <Sun {...ICON} />
      </button>

      <button
        type="button"
        className={`rail-tool ${theme === 'dark' ? 'rail-tool--on' : ''}`}
        onClick={() => setTheme('dark')}
        title={t('sidebar.appearance.dark')}
        aria-label={t('sidebar.appearance.dark')}
        aria-pressed={theme === 'dark'}
      >
        <Moon {...ICON} />
      </button>

      {/* 月历挂到 body 上，不留在这根栏里面。左栏是 flex 子项且带 z-index，自己就是一层
          堆叠上下文——浮层写多高的 z-index 都只在这一层里比，会被栏外的东西压住。 */}
      {calendarOpen
        ? createPortal(
            <TokenCalendarModal t={t} onClose={() => setCalendarOpen(false)} />,
            document.body
          )
        : null}

      {tmuxOpen
        ? createPortal(<TmuxSessionsModal onClose={() => setTmuxOpen(false)} />, document.body)
        : null}
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

      <div className="rail-foot">
        <UsageBars expanded={expanded} />
        <RailEnvironment expanded={expanded} />
        <RailTools />
      </div>
    </nav>
  );
}
