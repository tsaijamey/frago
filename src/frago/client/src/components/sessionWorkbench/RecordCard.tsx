/**
 * RecordCard — 一条统一记录 = 一张卡片。
 *
 * 十六种形态**不是十六个平行分支**。按 spec 风险表的办法分三组，组内只换内容区：
 *
 * | 组 | 外壳 | 形态 |
 * |---|---|---|
 * | 文本类 | `TextShell` | user.say / agent.say / agent.think / context.inject |
 *
 * 文本类里 `context.inject` 走两条路：**旁路注入**（LightAgent 经 hook 塞进上下文的话，
 * `payload.source === 'hook'`）自成一色、默认摊开；其余注入照旧折叠。判据取数据层给的
 * `source`，NEVER 靠标签名反推——标签是给人看的，改一个字就会把归类改掉。
 * | 工具类 | `ToolShell` | tool.call / tool.result / subagent.dispatch / todo.snapshot / permission.outcome / media.attach |
 * | 系统类 | `SystemShell` | error / interrupt / session.state / context.compact / call.envelope / usage.tick |
 *
 * 三条硬纪律落在这个文件里：
 *
 * 1. **报错卡只显示范围、代码、消息三项，不给「查看原文」入口。** 服务端已经拦了一道
 *    （恒 403），界面这一层也不许给——两道都要有。这是安全约束不是设计选择。
 * 2. **分组编号不显示。** 那是三十几位的机器标识，对人零意义。视觉归组在
 *    `RecordStream` 里做，编号本身一个字不露。
 * 3. **不呈现任何进度。** 百分比、X 比 Y 计数、进度条、预计剩余、还没发生的步骤名，
 *    全域禁止。允许出现的量只有已发生的绝对数。
 *
 * 样式一律 Tailwind 工具类，NEVER 自定义 class name。纸面与墨色走 webUI 现有的主题
 * 变量（跟着 `[data-theme]` 走），强调色与状态色照搬工作台设计稿的色相。
 */

import { memo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Bot,
  Braces,
  ChevronRight,
  Circle,
  Clock,
  Download,
  FileText,
  Gauge,
  Globe,
  Layers,
  ListChecks,
  Lock,
  Minimize2,
  Paperclip,
  PenLine,
  Scissors,
  Search,
  ShieldAlert,
  Terminal,
  User,
  CornerDownRight,
  Zap,
} from 'lucide-react';
import i18n from '@/i18n';
import MarkdownContent from '@/components/ui/MarkdownContent';
import {
  fetchWorkbenchRaw,
  type RecordKind,
  type WorkbenchRecord,
} from '@/hooks/useWorkbenchRecords';

// ── 配色 ──────────────────────────────────────────────────────────────
// **这一栏只有三个色相**：品牌绿（活跃、子轨迹）、告警橙、报错红。全部走主题变量，
// 明暗两套各取各的那一份，NEVER 写死色值。
//
// 从前这里另立了一套写死的柔色板——鼠尾草绿的「成功」、青灰的「已完成」、紫的「旁路
// 注入」。它们和主题变量各走各的，浅色主题下从来没被验过；更要紧的是，一屏记录里
// 「成功」和「已完成」占了绝大多数，给这两档各配一个颜色，等于把整条流染成彩色，
// 真正需要被一眼找到的报错反而淹在里面。
//
// 现在的规则：**默认结局不给颜色。** 成功、已完成、结束——这些是记录流的常态，用中性
// 灰。只有需要人做点什么的两档才有颜色：出错（红）、在等（橙）。
const ACCENT_TEXT = 'text-accent-primary';
const ACCENT_BG = 'bg-accent-primary-10';
const ACCENT_RING = 'ring-1 ring-border-accent';
const ERR_TEXT = 'text-accent-error';
const ERR_BG = 'bg-accent-error-10';
const ERR_RING = 'ring-1 ring-accent-error/35';
const WAIT_TEXT = 'text-accent-warning';
const WAIT_BG = 'bg-accent-warning-10';
const WAIT_RING = 'ring-1 ring-accent-warning/35';
const OK_TEXT = 'text-text-secondary';
const DONE_TEXT = 'text-text-muted';
const DONE_BG = 'bg-bg-subtle';
// 旁路注入要与人说的、agent 说的分得开：读这一格时唯一要知道的事，就是"这句话是被别人
// 塞进来的"。分得开靠的不是再发明一个色相——**是虚线轮廓**。虚线在任何主题下都读作
// "外来的、临时贴上去的"，而且它不消耗颜色预算：颜色留给出错与在等。
const HOOK_TEXT = 'text-text-secondary';
const HOOK_BG = 'bg-bg-subtle';
const HOOK_RING = 'border border-dashed border-border-strong';
// 后台任务完成：不上色，卡底加一圈实线边，跟工具卡同一个形状。
const TASK_CARD_NEUTRAL = 'border border-border-color bg-bg-card';

// ── 三组归属 ──────────────────────────────────────────────────────────
export type KindGroup = 'text' | 'tool' | 'system';

/** 十六种形态各落在哪一组。测试拿它断言分组穷尽且不重叠。 */
export const KIND_GROUP: Record<RecordKind, KindGroup> = {
  'user.say': 'text',
  'agent.say': 'text',
  'agent.think': 'text',
  'context.inject': 'text',
  'tool.call': 'tool',
  'tool.result': 'tool',
  'subagent.dispatch': 'tool',
  'todo.snapshot': 'tool',
  'permission.outcome': 'tool',
  'media.attach': 'tool',
  error: 'system',
  interrupt: 'system',
  'session.state': 'system',
  'context.compact': 'system',
  'call.envelope': 'system',
  'usage.tick': 'system',
};

/**
 * 形态在界面上叫什么。这里摆的是**词表键**，NEVER 把机器标记名直接摆给人看，也 NEVER
 * 在模块级把字取出来——那会把它锁死在开局那一种语言上。取字由各张卡在渲染时做。
 */
export const KIND_LABEL_KEY: Record<RecordKind, string> = {
  'user.say': 'workbench.record.kind.userSay',
  'agent.say': 'workbench.record.kind.agentSay',
  'agent.think': 'workbench.record.kind.agentThink',
  'context.inject': 'workbench.record.kind.contextInject',
  'tool.call': 'workbench.record.kind.toolCall',
  'tool.result': 'workbench.record.kind.toolResult',
  'subagent.dispatch': 'workbench.record.kind.subagentDispatch',
  'todo.snapshot': 'workbench.record.kind.todoSnapshot',
  'permission.outcome': 'workbench.record.kind.permissionOutcome',
  'media.attach': 'workbench.record.kind.mediaAttach',
  error: 'workbench.record.kind.error',
  interrupt: 'workbench.record.kind.interrupt',
  'session.state': 'workbench.record.kind.sessionState',
  'context.compact': 'workbench.record.kind.contextCompact',
  'call.envelope': 'workbench.record.kind.callEnvelope',
  'usage.tick': 'workbench.record.kind.usageTick',
};

// ── 取值小工具 ────────────────────────────────────────────────────────
type Payload = Record<string, unknown>;

function str(payload: Payload, key: string): string {
  const value = payload[key];
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function num(payload: Payload, key: string): number | null {
  const value = payload[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function list(payload: Payload, key: string): unknown[] {
  const value = payload[key];
  return Array.isArray(value) ? value : [];
}

function dict(value: unknown): Payload {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Payload) : {};
}

/**
 * 毫秒 → 人话。只报已经发生的时长，NEVER 报预计还要多久。
 *
 * 取字走 i18next 实例而不是 `useTranslation`——它是纯函数，不是组件。取字发生在调用
 * 那一刻，也就是渲染那一刻，所以拿到的永远是当下这一种语言。
 */
export function formatDuration(ms: number | null): string {
  if (ms === null || ms < 0) return '';
  if (ms < 1000) return i18n.t('workbench.record.duration.ms', { n: ms });
  if (ms < 60_000) {
    return i18n.t('workbench.record.duration.sec', { n: (ms / 1000).toFixed(1) });
  }
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds
    ? i18n.t('workbench.record.duration.minSec', { m: minutes, s: seconds })
    : i18n.t('workbench.record.duration.min', { m: minutes });
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes < 0) return '';
  if (bytes < 1024) return i18n.t('workbench.record.bytes.b', { n: bytes });
  if (bytes < 1024 * 1024) {
    return i18n.t('workbench.record.bytes.kb', { n: (bytes / 1024).toFixed(1) });
  }
  return i18n.t('workbench.record.bytes.mb', { n: (bytes / 1024 / 1024).toFixed(1) });
}

/** 毫秒时间戳 → 本地时刻。naive local time，不拼 Z 后缀。 */
export function formatClock(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 单行参数预览。多行一律压成一行，长了省略——卡头不许被一条长命令顶宽。 */
function previewArgs(args: Payload): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(args)) {
    if (key.startsWith('__')) continue;
    const text =
      typeof value === 'string' ? value : value === null ? 'null' : JSON.stringify(value) ?? '';
    parts.push(`${key}=${text}`);
    if (parts.join(' ').length > 200) break;
  }
  return parts.join('  ').replace(/\s+/g, ' ').slice(0, 200);
}

// ── 工具家族 ──────────────────────────────────────────────────────────
const TOOL_FAMILY_LABEL_KEY: Record<string, string> = {
  shell: 'workbench.record.toolFamily.shell',
  'file-read': 'workbench.record.toolFamily.fileRead',
  'file-write': 'workbench.record.toolFamily.fileWrite',
  search: 'workbench.record.toolFamily.search',
  web: 'workbench.record.toolFamily.web',
  agent: 'workbench.record.toolFamily.agent',
  todo: 'workbench.record.toolFamily.todo',
  ask: 'workbench.record.toolFamily.ask',
  schedule: 'workbench.record.toolFamily.schedule',
  mcp: 'workbench.record.toolFamily.mcp',
  other: 'workbench.record.toolFamily.other',
};

function toolIcon(family: string) {
  switch (family) {
    case 'shell':
      return <Terminal size={14} />;
    case 'file-read':
      return <FileText size={14} />;
    case 'file-write':
      return <PenLine size={14} />;
    case 'search':
      return <Search size={14} />;
    case 'web':
      return <Globe size={14} />;
    case 'agent':
      return <Bot size={14} />;
    case 'todo':
      return <ListChecks size={14} />;
    case 'mcp':
      return <Layers size={14} />;
    default:
      return <Braces size={14} />;
  }
}

const STATUS_TEXT_KEY: Record<string, string> = {
  ok: 'workbench.record.status.ok',
  error: 'workbench.record.status.error',
  denied: 'workbench.record.status.denied',
  interrupted: 'workbench.record.status.interrupted',
  completed: 'workbench.record.status.completed',
  pending: 'workbench.record.status.pending',
};

/** 状态一律带文字标签，颜色不是唯一通道——拿掉颜色也读得出。 */
function StatusChip({ status }: { status: string }) {
  const { t } = useTranslation();
  if (!status) return null;
  const tone =
    status === 'error'
      ? `${ERR_BG} ${ERR_TEXT}`
      : status === 'denied' || status === 'interrupted'
        ? `${WAIT_BG} ${WAIT_TEXT}`
        : `${DONE_BG} ${OK_TEXT}`;
  return (
    <span className={`rounded-full px-2 py-[1px] text-[11px] leading-[1.45] ${tone}`}>
      {STATUS_TEXT_KEY[status] ? t(STATUS_TEXT_KEY[status]) : status}
    </span>
  );
}

/** 截断三态。三者一眼可辨，且各自带图标加文字。 */
function TruncationChip({ state, ref_ }: { state: string; ref_: string }) {
  const { t } = useTranslation();
  if (state === 'clipped') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-[1px] text-[11px] ${ERR_BG} ${ERR_TEXT}`}
      >
        <Scissors size={11} />
        {t('workbench.record.clipped')}
      </span>
    );
  }
  if (state === 'offloaded') {
    return (
      <span
        className={`inline-flex max-w-full items-center gap-1 rounded-full px-2 py-[1px] text-[11px] ${DONE_BG} ${DONE_TEXT}`}
      >
        <FileText size={11} />
        <span className="truncate font-mono">
          {ref_
            ? t('workbench.record.offloadedRef', { ref: ref_ })
            : t('workbench.record.offloaded')}
        </span>
      </span>
    );
  }
  return null;
}

// ── 三个外壳 ──────────────────────────────────────────────────────────
interface ShellProps {
  record: WorkbenchRecord;
  /** 正文可有可无：状态变更、调用边界这类形态一行就说完了，没有正文。 */
  children?: ReactNode;
}

function Timestamp({ ts }: { ts: number }) {
  const clock = formatClock(ts);
  if (!clock) return null;
  return <span className="shrink-0 font-mono text-[11px] text-text-muted">{clock}</span>;
}

function AgentPath({ path }: { path: string[] }) {
  const { t } = useTranslation();
  if (!path.length) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-[1px] text-[11px] ${ACCENT_BG} ${ACCENT_TEXT}`}
    >
      <Bot size={10} />
      {t('workbench.record.subtrace')}
    </span>
  );
}

/**
 * 每一条记录的头一行都长这样：类型标签在最左，元信息居中省略，时刻钉在最右。
 *
 * **类型靠"标签是什么样"来分，不是靠"标签写了什么"。** 十五种形态的名字都是两到四个
 * 汉字、同一个字号、同一个灰——静止时它们看上去是同一种东西，人必须逐条读字才知道
 * 这条是回复还是工具还是记账。所以标签自己带三种形状：说话的是实心字，工具的是等宽
 * 字，系统记账的是更小更淡的字。一屏扫过去，不读字也认得出哪几条是对话。
 */
function CardHead({
  record,
  icon,
  label,
  labelTone = 'text-text-secondary',
  meta,
  trailing,
  open,
  onToggle,
}: {
  record: WorkbenchRecord;
  icon?: ReactNode;
  label: ReactNode;
  labelTone?: string;
  meta?: ReactNode;
  trailing?: ReactNode;
  /** 给了 onToggle 才长折叠开关。 */
  open?: boolean;
  onToggle?: () => void;
}) {
  const name = (
    <span className={`inline-flex shrink-0 items-center gap-1 ${labelTone}`}>
      {icon}
      {label}
    </span>
  );
  return (
    <header className="flex items-center gap-2 text-[11px] text-text-muted">
      {onToggle ? (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className={`inline-flex shrink-0 items-center gap-1 hover:opacity-80 ${labelTone}`}
        >
          <ChevronRight
            size={12}
            className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
          />
          {icon}
          {label}
        </button>
      ) : (
        name
      )}
      <span className="min-w-0 flex-1 truncate">{meta}</span>
      {trailing}
      <AgentPath path={record.agent_path} />
      <Timestamp ts={record.ts} />
    </header>
  );
}

/**
 * 文本类外壳：正文优先，容器尽量轻。
 *
 * **默认没有容器。** agent 的回复是这一栏里字最多、也最该被读进去的东西；给它套一个
 * 卡底，一屏就成了五六个灰盒子叠在一起，读一段要先跨过一道边。只有需要被认出来的那
 * 几种（你说、思考、旁路）才自带纸色或虚线轮廓——由调用方经 `tone` 指定。
 */
function TextShell({
  record,
  icon,
  label,
  labelTone,
  meta,
  tone = '',
  collapsible = false,
  defaultOpen = true,
  children,
}: ShellProps & {
  icon?: ReactNode;
  label: string;
  labelTone?: string;
  meta?: ReactNode;
  tone?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // 有纸色的才需要内距把字撑开；没纸色的不加，否则正文会莫名其妙地缩在中间。
  const padded = tone && tone !== 'bg-transparent';
  return (
    <article
      data-kind={record.kind}
      data-group={KIND_GROUP[record.kind]}
      className={`min-w-0 rounded-[8px] ${padded ? 'px-3 py-2' : ''} ${tone}`}
    >
      <CardHead
        record={record}
        icon={icon}
        label={label}
        labelTone={labelTone}
        meta={meta}
        open={open}
        onToggle={collapsible ? () => setOpen((v) => !v) : undefined}
      />
      {open ? <div className="mt-1.5 min-w-0">{children}</div> : null}
    </article>
  );
}

/**
 * 工具类外壳：一行卡头（家族图标 + 名字 + 一行预览 + 状态），输出收在下面。
 *
 * **默认是收起来的。** 从前默认摊开：一次 `Read` 的输出就是两百行，一屏记录里躺着七八
 * 次调用，人要滚过几千行才看得到 agent 下一句说了什么。工具的输出是要查的时候才查的
 * 东西，卡头那一行（工具名 + 参数预览 + 状态）已经答了"它干了什么、成没成"。
 * 唯一的例外是失败：那一条自己摊开——出了错还要人再点一下才看得见，是把最该被看见的
 * 东西藏起来。
 *
 * **卡头不再自带一层底色。** 卡头有底、卡身有底、外面还有一圈边，三层套在一起，一屏
 * 就成了一堆窗口。现在整卡一个底、一圈边，卡头与卡身之间只用一条发丝线分开。
 */
function ToolShell({
  record,
  icon,
  title,
  subtitle,
  chips,
  headTone = '',
  ringTone = '',
  collapsible = false,
  defaultOpen = false,
  children,
}: ShellProps & {
  icon: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  chips?: ReactNode;
  headTone?: string;
  ringTone?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const hasBody = Boolean(children);
  return (
    <article
      data-kind={record.kind}
      data-group={KIND_GROUP[record.kind]}
      className={`min-w-0 overflow-hidden rounded-[8px] border border-border-color ${
        headTone || 'bg-bg-card'
      } ${ringTone}`}
    >
      <header className="flex items-center gap-2 px-3 py-2">
        {collapsible && hasBody ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 text-text-muted hover:text-text-primary"
            aria-expanded={open}
            aria-label={t('workbench.record.toggle')}
          >
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            />
          </button>
        ) : null}
        <span className="shrink-0 text-text-muted">{icon}</span>
        {/* 工具名一律等宽字。这是"这条是工具"的第一眼线索，不必读字就成立。 */}
        <span className="shrink-0 font-mono text-[12px] font-semibold text-text-primary">
          {title}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-muted">
          {subtitle}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {chips}
          <AgentPath path={record.agent_path} />
          <Timestamp ts={record.ts} />
        </span>
      </header>
      {hasBody && open ? (
        <div className="min-w-0 border-t border-border-color px-3 py-2">{children}</div>
      ) : null}
    </article>
  );
}

/**
 * 系统类外壳：不是对话，是发生在会话上的事。
 *
 * **它是一行日志，不是一张卡。** 状态变更、调用边界、上下文压缩这些是引擎的记账，一场
 * 会话里能有几百条。每一条都给一个纸色方块，人读到的就是一整屏方块。所以默认无底色、
 * 11px、更淡的灰——需要它时它在，不需要时它退到背景里。
 * 只有报错与打断这两种自带纸色（由调用方经 `tone` 指定）：那两条本来就该跳出来。
 */
function SystemShell({
  record,
  icon,
  label,
  meta,
  tone = '',
  collapsible = false,
  defaultOpen = false,
  children,
}: ShellProps & {
  icon: ReactNode;
  label: ReactNode;
  meta?: ReactNode;
  tone?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const hasBody = Boolean(children);
  const padded = Boolean(tone);
  return (
    <article
      data-kind={record.kind}
      data-group={KIND_GROUP[record.kind]}
      className={`min-w-0 rounded-[8px] ${padded ? 'px-3 py-2' : 'px-1 py-0.5'} ${tone}`}
    >
      <div className="flex items-center gap-2 text-[11px] text-text-muted">
        {collapsible && hasBody ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 hover:text-text-primary"
            aria-expanded={open}
            aria-label={t('workbench.record.toggle')}
          >
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            />
          </button>
        ) : null}
        <span className="shrink-0">{icon}</span>
        <span className="shrink-0">{label}</span>
        <span className="min-w-0 flex-1 truncate">{meta}</span>
        <AgentPath path={record.agent_path} />
        <Timestamp ts={record.ts} />
      </div>
      {hasBody && open ? <div className="mt-1.5 min-w-0">{children}</div> : null}
    </article>
  );
}

// ── 正文块 ────────────────────────────────────────────────────────────
/** 中文正文：14px / 1.72。长会话一路读下来，这个行高比 1.5 明显省力。 */
function Prose({ text }: { text: string }) {
  const { t } = useTranslation();
  if (!text) {
    return <p className="text-[13px] italic text-text-muted">{t('workbench.record.emptyBody')}</p>;
  }
  return (
    <p className="whitespace-pre-wrap break-words text-[14px] leading-[1.72] text-text-primary">
      {text}
    </p>
  );
}

/**
 * 排过版的正文。agent 的回复本来就是 Markdown 写的——标题、清单、表格、代码块，
 * 照字面铺开等于把排版信息当噪音丢掉，一屏井号和星号读起来比什么都累。
 */
function Rich({ text }: { text: string }) {
  const { t } = useTranslation();
  if (!text) {
    return <p className="text-[13px] italic text-text-muted">{t('workbench.record.emptyBody')}</p>;
  }
  return (
    <MarkdownContent
      content={text}
      className="min-w-0 break-words text-[14px] leading-[1.72] text-text-primary"
    />
  );
}

/**
 * 等宽输出块。最高 230px，超出**在块内滚**，不撑页面。
 * 230px 约十二行，够看出这次调用干了什么，又不至于把一屏占满。
 */
function Mono({ text }: { text: string }) {
  const { t } = useTranslation();
  if (!text) {
    return <p className="text-[12px] italic text-text-muted">{t('workbench.record.noOutput')}</p>;
  }
  return (
    <pre className="max-h-[230px] overflow-auto whitespace-pre-wrap break-words rounded-[3px] bg-bg-subtle p-2 font-mono text-[12px] leading-[1.6] text-text-secondary">
      {text}
    </pre>
  );
}

// ── 十五种形态的内容区 ────────────────────────────────────────────────
/**
 * 你说的那句话。
 *
 * **人的输入要一眼认得出来。** 一场会话里人真正开口的次数是个位数，其余全是 agent、
 * 工具与旁路在说话；这几张卡要是跟周围一个颜色，人就得逐张读标签才能找到"我当时问的
 * 是什么"。所以整卡换纸色加一圈环——不用单边竖条，那是肌肉记忆不是设计。
 */
function UserSay({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const images = list(p, 'images');
  const mode = str(p, 'input_mode');
  const command = str(p, 'command');
  const reminders = list(p, 'reminders').filter((r): r is string => typeof r === 'string' && !!r);
  const text = str(p, 'text');

  // 敲在输入框里是常态，说出来等于没说。只有"当时不是直接打字"才值得标一句：插话是
  // 趁 agent 在忙时打进去的，接口发起的那几条根本不是人坐在这儿敲的。
  const modeKey = INPUT_MODE_LABEL_KEY[mode];
  const inline = !!command && isInlineArg(text);

  return (
    <TextShell
      record={record}
      icon={command ? <Terminal size={12} /> : <User size={12} />}
      label={t(KIND_LABEL_KEY['user.say'])}
      labelTone={`text-[11px] font-semibold ${ACCENT_TEXT}`}
      tone={`${ACCENT_BG} ${ACCENT_RING}`}
      meta={modeKey ? t(modeKey) : undefined}
    >
      {/* 命令摆成一枚等宽徽标。参数跟不跟它连排，看参数是**一个取值**还是**一段话**：
          `/model Opus` 人打的就是连着的一句，拆成两行两种字号会读成"命令是 /model，
          然后我说了一句 Opus"；`/goal` 后面那一整段任务书（本机最长 2601 字、82 条带
          换行）挤进徽标里则谁都读不下去。判据取形状不取语义——单行且短的连排，带换行
          或长的分开。 */}
      {command ? (
        <p
          data-testid="user-command"
          className="inline-block max-w-full break-all rounded-[4px] bg-bg-card px-2 py-[3px] font-mono text-[12px] text-text-primary"
        >
          {inline ? `${command} ${text}` : command}
        </p>
      ) : null}
      {!inline && (text || !command) ? (
        <div className={command ? 'mt-1.5' : undefined}>
          <Prose text={text} />
        </div>
      ) : null}
      {images.length ? (
        <p className="mt-1.5 text-[11px] text-text-muted">
          {t('workbench.record.attachedImages', { n: images.length })}
        </p>
      ) : null}
      {reminders.length ? <Reminders items={reminders} /> : null}
    </TextShell>
  );
}

/**
 * 这段参数该不该跟命令连成一句。
 *
 * 分界不在语义上——界面看不出 `Opus` 是取值而 `修完 bug` 是句子，也不需要看出来：
 * **短到一行读得完的，连排都不难看**。本机 343 条斜杠命令里 21 条参数在这个范围内
 * （`/model Opus`、`/effort low` 是主力），其余不是空的，就是 `/goal` 后面那种整段
 * 任务书——42 条二十到六十字的指令句、132 条六十字以上、其中 82 条带换行。
 *
 * 二十四这个数是照真实数据划的，不是猜的：短参数那一批最长七个字，指令句那一批最短
 * 二十二字，界线落在两批中间的空当里，两边都不贴边。
 */
const INLINE_ARG_MAX = 24;

function isInlineArg(text: string): boolean {
  return !!text && !text.includes('\n') && text.length <= INLINE_ARG_MAX;
}

/**
 * 当时这句话是怎么进来的。**打字是常态，不标**——每张卡都挂一句"输入方式 typed"，
 * 等于把机器字段名摆给人看，还把真正特殊的那两种淹掉了。
 */
const INPUT_MODE_LABEL_KEY: Record<string, string> = {
  queued: 'workbench.record.inputMode.queued',
  sdk: 'workbench.record.inputMode.sdk',
  suggestion_accepted: 'workbench.record.inputMode.suggestion',
  'slash-command': 'workbench.record.inputMode.slashCommand',
  'bash-command': 'workbench.record.inputMode.bashCommand',
};

/**
 * 引擎追加在这句话尾巴上的提醒。
 *
 * 它跟人写的那段话之间在档案里没有任何分隔，照原样铺开会读成人自己说的——那些"记得
 * 用 uv run"之类的句子，人从来没打过。所以剥出来折起来，要看再点开。
 */
function Reminders({ items }: { items: string[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="user-reminders"
        className="inline-flex items-center gap-1 text-[11px] text-text-muted hover:text-text-secondary"
      >
        <ChevronRight
          size={11}
          className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        />
        {t('workbench.record.appendedReminders', { n: items.length })}
      </button>
      {open ? (
        <div className="mt-1.5 space-y-1.5">
          {items.map((text, i) => (
            <div
              key={i}
              className="max-h-[200px] overflow-auto whitespace-pre-wrap break-words rounded-[6px] border border-dashed border-border-color px-2.5 py-1.5 text-[12px] leading-[1.7] text-text-muted"
            >
              {text}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function AgentSay({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  return (
    <TextShell
      record={record}
      icon={<Bot size={12} />}
      label={t(KIND_LABEL_KEY['agent.say'])}
      labelTone="text-[11px] font-semibold text-text-primary"
      tone="bg-transparent"
      meta={str(p, 'model')}
    >
      <Rich text={str(p, 'text')} />
    </TextShell>
  );
}

function AgentThink({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const text = str(record.payload, 'text');
  // 正文没落盘的思考（模型这一轮的推理是加密的，落盘时只剩一个空壳）照常出卡的话，
  // 一屏能排下八九个「思考 0 字」的空盒子，把真正有内容的对话挤没了。它确实发生过，
  // 所以 NEVER 丢掉——但它只值一行，不值一张卡。
  if (!text) {
    return (
      <div
        data-kind={record.kind}
        data-group="text"
        data-testid="think-empty"
        className="flex min-w-0 items-center gap-2 px-1 text-[11px] text-text-muted"
      >
        <Circle size={7} />
        <span>{t('workbench.record.thinkEmpty')}</span>
        <span className="h-px flex-1 border-t border-dashed border-border-color" />
        <span className="font-mono">{formatClock(record.ts)}</span>
      </div>
    );
  }
  return (
    <TextShell
      record={record}
      icon={<Circle size={10} />}
      label={t(KIND_LABEL_KEY['agent.think'])}
      labelTone="text-[11px] text-text-muted"
      tone="border border-dashed border-border-color"
      meta={t('workbench.record.charCount', { n: text.length })}
      collapsible
      defaultOpen={false}
    >
      <p className="whitespace-pre-wrap break-words text-[13px] leading-[1.72] text-text-secondary">
        {text}
      </p>
    </TextShell>
  );
}

/**
 * hook 是在什么当口把话塞进来的。取中文，NEVER 把 ``PreToolUse`` 这种机器名摆给人看
 * ——认不出这几个词的人，看到它只知道"有东西"，看不出"有东西拦在我动手之前"。
 */
const HOOK_EVENT_LABEL_KEY: Record<string, string> = {
  SessionStart: 'workbench.record.hookEvent.SessionStart',
  UserPromptSubmit: 'workbench.record.hookEvent.UserPromptSubmit',
  PreToolUse: 'workbench.record.hookEvent.PreToolUse',
  PostToolUse: 'workbench.record.hookEvent.PostToolUse',
  Stop: 'workbench.record.hookEvent.Stop',
  PreCompact: 'workbench.record.hookEvent.PreCompact',
  Notification: 'workbench.record.hookEvent.Notification',
};

/**
 * 旁路注入卡：**不是人说的，也不是 agent 说的，是第三方塞进这场对话的话。**
 *
 * 这一格从前混在通用的「注入内容」里、默认折叠、标签是 `PreToolUse:Bash` 这种机器串，
 * 结果是整条旁路在中栏上等于不存在。现在它自成一色、默认摊开、按事件说人话，并且**同
 * 一次注入只出一张卡**（hook 进程的原始标准输出那一份在数据层就并掉了）。
 *
 * 一次事件上挂了几个 hook 就有几段，段界保留——两个 hook 各说一句，和一个 hook 说了
 * 很长一句，读起来是两回事。
 */
function HookInject({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const event = str(p, 'hook_event');
  const target = str(p, 'hook_target');
  const blocks = list(p, 'blocks').filter((b): b is string => typeof b === 'string' && !!b);
  const body = str(p, 'body');
  const segments = blocks.length ? blocks : body ? [body] : [];
  const exit = num(p, 'exit_code');
  const failed = exit !== null && exit !== 0;
  const stderr = str(p, 'stderr');
  const prevented = p.prevented_continuation === true;
  const [open, setOpen] = useState(true);

  return (
    <article
      data-kind={record.kind}
      data-group="text"
      data-source="hook"
      data-testid="hook-inject"
      className={`min-w-0 rounded-[8px] px-3 py-2 ${HOOK_BG} ${HOOK_RING}`}
    >
      <header className="flex items-center gap-2 text-[11px]">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className={`inline-flex shrink-0 items-center gap-1 font-semibold ${HOOK_TEXT}`}
        >
          <ChevronRight
            size={12}
            className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
          />
          <Zap size={12} />
          <span>{t('workbench.record.hookInject')}</span>
        </button>
        <span className="min-w-0 flex-1 truncate text-text-secondary">
          {HOOK_EVENT_LABEL_KEY[event] ? t(HOOK_EVENT_LABEL_KEY[event]) : event}
          {target ? <span className="ml-1 font-mono text-text-muted">{target}</span> : null}
        </span>
        {segments.length > 1 ? (
          <span className="shrink-0 rounded-full bg-bg-card px-2 py-[1px] font-mono text-text-muted">
            {t('workbench.record.segments', { n: segments.length })}
          </span>
        ) : null}
        {prevented ? (
          <span className={`shrink-0 rounded-full px-2 py-[1px] ${WAIT_BG} ${WAIT_TEXT}`}>
            {t('workbench.record.blockedStop')}
          </span>
        ) : null}
        {failed ? (
          <span className={`shrink-0 rounded-full px-2 py-[1px] ${ERR_BG} ${ERR_TEXT}`}>
            {t('workbench.record.exitCode', { code: exit })}
          </span>
        ) : null}
        <AgentPath path={record.agent_path} />
        <Timestamp ts={record.ts} />
      </header>

      {open ? (
        <div className="mt-2 min-w-0 space-y-2">
          {segments.length ? (
            segments.map((text, i) => (
              <div
                key={i}
                className="max-h-[260px] overflow-auto whitespace-pre-wrap break-words rounded-[6px] border border-border-color px-2.5 py-2 text-[13px] leading-[1.7] text-text-secondary"
              >
                {text}
              </div>
            ))
          ) : (
            <p className="text-[12px] italic text-text-muted">
              {t('workbench.record.hookSaidNothing')}
            </p>
          )}
          {stderr ? (
            <div>
              <p className={`mb-1 text-[11px] ${ERR_TEXT}`}>{t('workbench.record.stderr')}</p>
              <Mono text={stderr} />
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

/** 插话的三种下场各配一句人话与一个颜色。写的是**结果**，不是过程。 */
const QUEUE_STATE: Record<string, { key: string; tone: string }> = {
  absorbed: { key: 'workbench.record.queueState.absorbed', tone: `${DONE_BG} ${DONE_TEXT}` },
  submitted: { key: 'workbench.record.queueState.submitted', tone: `${DONE_BG} ${DONE_TEXT}` },
  pending: { key: 'workbench.record.queueState.pending', tone: `${WAIT_BG} ${WAIT_TEXT}` },
};

/**
 * 插话 —— 人在 agent 干活时打进去的那句话。
 *
 * 它跟别的注入内容不是一类东西：**这是人说的话**，只是因为当时 agent 正忙，引擎把它
 * 排了一下队。它在会话记录里没有「用户消息」那种形态，这张卡是它唯一的痕迹——所以
 * 正文默认摊开（跟其他发言一样），而不是折起来等人去点。
 *
 * 卡上必须写清下场。只说"排队"不说"后来怎么了"，人看到"排队"只会以为它还在等、或者
 * 压根没进去；而绝大多数插话在几秒内就已经送达、模型也照做了。
 */
function QueuedCommand({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const state = QUEUE_STATE[str(p, 'queue_state')] ?? QUEUE_STATE.pending;
  return (
    <TextShell
      record={record}
      icon={<CornerDownRight size={12} />}
      label={t('workbench.record.queuedCommand')}
      tone={`${ACCENT_BG} ${ACCENT_RING}`}
      meta={
        <span className={`rounded-full px-2 py-[1px] ${state.tone}`}>{t(state.key)}</span>
      }
    >
      <Prose text={str(p, 'body')} />
    </TextShell>
  );
}

/**
 * 后台任务四种下场。完成是常态不给颜色，另外三种都要人回头看一眼。
 *
 * `card` 是整张卡的底：它落在「对话」那一档里，夹在人和 agent 的发言中间，从前那层
 * `bg-bg-subtle` 跟纸面几乎同色，一眼认不出这是一条外来的通知。**底色跟着下场走**——
 * 出错整卡报错红、叫停整卡告警橙；完成不上色，只用卡底加一圈边把它从正文里托出来，
 * 跟工具卡同一个形状。颜色预算照旧只花在要人做点什么的那两档上。
 */
const TASK_STATUS: Record<string, { key: string; tone: string; card: string }> = {
  completed: {
    key: 'workbench.record.taskStatus.completed',
    tone: `${DONE_BG} ${DONE_TEXT}`,
    card: TASK_CARD_NEUTRAL,
  },
  failed: {
    key: 'workbench.record.taskStatus.failed',
    tone: `${ERR_BG} ${ERR_TEXT}`,
    card: `${ERR_BG} ${ERR_RING}`,
  },
  killed: {
    key: 'workbench.record.taskStatus.killed',
    tone: `${ERR_BG} ${ERR_TEXT}`,
    card: `${ERR_BG} ${ERR_RING}`,
  },
  stopped: {
    key: 'workbench.record.taskStatus.stopped',
    tone: `${WAIT_BG} ${WAIT_TEXT}`,
    card: `${WAIT_BG} ${WAIT_RING}`,
  },
};

/**
 * 后台任务跑完了。
 *
 * 这条从前顶着「你说」出现，正文是一坨带尖括号的任务号与落盘路径——人看到的是自己
 * 说了一句机器话。它其实是引擎在报账：某个后台任务有下场了。摘要那一句是人话，摆
 * 出来；任务号与输出文件是给要追下去的人留的，折起来。
 */
function TaskNotification({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const status = TASK_STATUS[str(p, 'task_status')];
  const file = str(p, 'output_file');
  return (
    <TextShell
      record={record}
      icon={<Zap size={12} />}
      label={t('workbench.record.taskNotification')}
      tone={status?.card ?? TASK_CARD_NEUTRAL}
      meta={
        status ? (
          <span className={`rounded-full px-2 py-[1px] ${status.tone}`}>{t(status.key)}</span>
        ) : undefined
      }
    >
      <p className="whitespace-pre-wrap break-words text-[13px] leading-[1.7] text-text-secondary">
        {str(p, 'body')}
      </p>
      {file ? (
        <p className="mt-1.5 break-all font-mono text-[11px] text-text-muted">{file}</p>
      ) : null}
    </TextShell>
  );
}

/**
 * 在本机跑的那条命令说了什么。
 *
 * 斜杠命令的回显与叹号直跑的输出是同一件事：命令跑在本机，结果贴回上下文。从前它顶着
 * 「你说」出现，正文外面还裹着一层 `<local-command-stdout>`——人会以为自己说了这句话。
 * 它是输出，所以走等宽块；默认折起来，因为对应的那条命令就在上一张卡上，多数时候看
 * 一眼命令就够了。
 */
function LocalCommandOutput({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const stderr = str(p, 'stderr');
  const stdout = str(p, 'stdout') || str(p, 'body');
  return (
    <TextShell
      record={record}
      icon={<Terminal size={12} />}
      label={t('workbench.record.localCommandOutput')}
      tone="bg-bg-subtle"
      meta={
        stderr ? (
          <span className={`rounded-full px-2 py-[1px] ${ERR_BG} ${ERR_TEXT}`}>
            {t('workbench.record.stderr')}
          </span>
        ) : undefined
      }
      collapsible
      defaultOpen={false}
    >
      <Mono text={stdout} />
      {stderr ? (
        <div className="mt-1.5">
          <p className={`mb-1 text-[11px] ${ERR_TEXT}`}>{t('workbench.record.stderr')}</p>
          <Mono text={stderr} />
        </div>
      ) : null}
    </TextShell>
  );
}

function ContextInject({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const files = list(p, 'files');
  const exit = num(p, 'exit_code');
  const unrecognized = p.unrecognized === true;
  const label = str(p, 'label') || str(p, 'channel') || t(KIND_LABEL_KEY['context.inject']);
  return (
    <TextShell
      record={record}
      icon={<Download size={12} />}
      label={unrecognized ? t('workbench.record.unrecognized', { label }) : label}
      tone="bg-bg-subtle"
      meta={
        <span className="flex items-center gap-2">
          <span className="truncate">{str(p, 'channel')}</span>
          {exit !== null ? (
            <span className="font-mono">{t('workbench.record.exitCode', { code: exit })}</span>
          ) : null}
        </span>
      }
      collapsible
      defaultOpen={false}
    >
      {files.length ? (
        <ul className="space-y-0.5 font-mono text-[12px] text-text-secondary">
          {files.map((f, i) => (
            <li key={i} className="break-all">
              {typeof f === 'string' ? f : JSON.stringify(f)}
            </li>
          ))}
        </ul>
      ) : (
        <Mono text={str(p, 'body') || str(p, 'stdout')} />
      )}
    </TextShell>
  );
}

function ToolCall({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const family = str(p, 'tool_family') || 'other';
  return (
    <ToolShell
      record={record}
      icon={toolIcon(family)}
      title={str(p, 'tool_name') || t('workbench.record.unnamedTool')}
      subtitle={str(p, 'title') || previewArgs(dict(p.args))}
      chips={
        <span className="rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-muted">
          {TOOL_FAMILY_LABEL_KEY[family] ? t(TOOL_FAMILY_LABEL_KEY[family]) : family}
        </span>
      }
      collapsible
      defaultOpen={false}
    >
      <Mono text={JSON.stringify(dict(p.args), null, 2)} />
    </ToolShell>
  );
}

function ToolResult({ record, sessionId }: { record: WorkbenchRecord; sessionId: string }) {
  const { t } = useTranslation();
  const p = record.payload;
  const truncation = str(p, 'truncation') || 'none';
  const [raw, setRaw] = useState<string | null>(null);
  const [rawError, setRawError] = useState<string | null>(null);
  const [rawLoading, setRawLoading] = useState(false);

  // 原文按需取，且只有工具结果这条路有入口。报错卡永远没有这个按钮。
  const canFetchRaw = record.raw_available && truncation !== 'none';

  const takeRaw = async () => {
    setRawLoading(true);
    setRawError(null);
    try {
      setRaw(JSON.stringify(await fetchWorkbenchRaw(sessionId, record.id), null, 2));
    } catch (e) {
      setRawError(e instanceof Error ? e.message : String(e));
    } finally {
      setRawLoading(false);
    }
  };

  const duration = formatDuration(num(p, 'duration_ms'));
  const status = str(p, 'status');
  // 失败的那一条自己摊开。其余收着——一次 Read 的输出两百行，一屏躺着七八次调用，
  // 全摊开的话人要滚过几千行才看得到 agent 下一句说了什么。
  const failed = status === 'error';
  // 内容被截断或被挪走的那几条也摊开：卡身里放着「取原文」，那是人拿回丢掉那段的
  // 唯一入口。收起来等于把补救办法藏在一次点击后面，而卡头上的徽章刚说完"没了"。
  const needsAction = failed || Boolean(truncation);
  return (
    <ToolShell
      record={record}
      icon={<Terminal size={14} />}
      title={str(p, 'tool_name') || t(KIND_LABEL_KEY['tool.result'])}
      subtitle={duration ? t('workbench.record.elapsed', { duration }) : undefined}
      headTone={failed ? ERR_BG : undefined}
      ringTone={failed ? ERR_RING : undefined}
      collapsible
      defaultOpen={needsAction}
      chips={
        <>
          <TruncationChip state={truncation} ref_={str(p, 'truncation_ref')} />
          <StatusChip status={status} />
        </>
      }
    >
      <Mono text={str(p, 'body')} />
      {canFetchRaw ? (
        <div className="mt-2">
          <button
            type="button"
            onClick={takeRaw}
            disabled={rawLoading}
            className="rounded-[3px] border border-border-color px-2 py-1 text-[11px] text-text-secondary hover:text-text-primary disabled:opacity-50"
          >
            {rawLoading ? t('workbench.record.fetchingRaw') : t('workbench.record.fetchRaw')}
          </button>
          {rawError ? <p className={`mt-1 text-[11px] ${ERR_TEXT}`}>{rawError}</p> : null}
          {raw ? (
            <div className="mt-2">
              <Mono text={raw} />
            </div>
          ) : null}
        </div>
      ) : null}
    </ToolShell>
  );
}

function SubagentDispatch({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const stats = dict(p.stats);
  // 允许出现的量只有已发生的绝对数：调了几次工具、多少 token、跑了多久。
  const facts: string[] = [];
  const tokens = typeof stats.total_tokens === 'number' ? stats.total_tokens : null;
  const calls =
    typeof stats.total_tool_use_count === 'number' ? stats.total_tool_use_count : null;
  const spent =
    typeof stats.total_duration_ms === 'number' ? stats.total_duration_ms : num(p, 'duration_ms');
  if (calls !== null) facts.push(t('workbench.record.toolCalls', { n: calls }));
  if (tokens !== null) facts.push(t('workbench.record.tokens', { n: tokens }));
  if (spent !== null) {
    facts.push(t('workbench.record.spent', { duration: formatDuration(spent) }));
  }

  return (
    <ToolShell
      record={record}
      icon={<Bot size={14} />}
      title={str(p, 'agent_type') || t('workbench.record.subagent')}
      subtitle={str(p, 'description') || str(p, 'title')}
      headTone={ACCENT_BG}
      ringTone={ACCENT_RING}
      chips={<StatusChip status={str(p, 'status')} />}
      collapsible
      defaultOpen={false}
    >
      {facts.length ? (
        <p className="mb-2 font-mono text-[11px] text-text-muted">{facts.join(' · ')}</p>
      ) : null}
      {str(p, 'prompt') ? (
        <div className="mb-2">
          <p className="mb-1 text-[11px] text-text-muted">
            {t('workbench.record.dispatchPrompt')}
          </p>
          <Mono text={str(p, 'prompt')} />
        </div>
      ) : null}
      {str(p, 'content') || str(p, 'body') ? (
        <div>
          <p className="mb-1 text-[11px] text-text-muted">
            {t('workbench.record.dispatchResult')}
          </p>
          <Mono text={str(p, 'content') || str(p, 'body')} />
        </div>
      ) : null}
      {p.trace_available === false ? (
        <p className="mt-1.5 text-[11px] text-text-muted">{t('workbench.record.noTrace')}</p>
      ) : null}
    </ToolShell>
  );
}

function TodoSnapshot({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const items = list(p, 'items');
  // 引擎被动重发的清单一个字没改也发，默认折叠；agent 主动写入的展开。
  const passive = str(p, 'source') === 'engine-reminder';
  return (
    <ToolShell
      record={record}
      icon={<ListChecks size={14} />}
      title={t(KIND_LABEL_KEY['todo.snapshot'])}
      subtitle={passive ? t('workbench.record.todoPassive') : t('workbench.record.todoActive')}
      chips={
        <span className="rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-muted">
          {t('workbench.record.itemCount', { n: items.length })}
        </span>
      }
      collapsible
      defaultOpen={!passive}
    >
      <ul className="space-y-1">
        {items.map((item, i) => {
          const it = dict(item);
          const status = typeof it.status === 'string' ? it.status : '';
          const content =
            typeof it.content === 'string'
              ? it.content
              : typeof it.subject === 'string'
                ? it.subject
                : JSON.stringify(item);
          const done = status === 'completed';
          const doing = status === 'in_progress';
          return (
            <li key={i} className="flex items-start gap-2 text-[13px] leading-[1.72]">
              <span
                className={`mt-[5px] flex h-[13px] w-[13px] shrink-0 items-center justify-center rounded-[3px] border ${
                  doing ? 'border-transparent ' + ACCENT_BG : 'border-border-color'
                }`}
              >
                {doing ? (
                  <span className={`h-[5px] w-[5px] rounded-full ${ACCENT_TEXT} bg-current`} />
                ) : null}
                {done ? <span className="text-[10px] text-text-muted">✓</span> : null}
              </span>
              <span
                className={
                  done ? 'text-text-muted line-through' : 'break-words text-text-primary'
                }
              >
                {content}
              </span>
            </li>
          );
        })}
      </ul>
    </ToolShell>
  );
}

function PermissionOutcome({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  return (
    <ToolShell
      record={record}
      icon={<ShieldAlert size={14} />}
      title={str(p, 'tool_name') || t(KIND_LABEL_KEY['permission.outcome'])}
      subtitle={str(p, 'reason')}
      headTone={WAIT_BG}
      /* 正文只有一行「权限模式 X」，收起来省不下什么，还多一次点击。 */
      defaultOpen
      chips={
        <span className={`rounded-full px-2 py-[1px] text-[11px] ${WAIT_BG} ${WAIT_TEXT}`}>
          {str(p, 'decision') === 'denied'
            ? t('workbench.record.status.denied')
            : str(p, 'decision')}
        </span>
      }
    >
      {str(p, 'mode') ? (
        <p className="font-mono text-[11px] text-text-muted">
          {t('workbench.record.permMode', { mode: str(p, 'mode') })}
        </p>
      ) : null}
    </ToolShell>
  );
}

function MediaAttach({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const name = str(p, 'display_name') || str(p, 'ref') || t(KIND_LABEL_KEY['media.attach']);
  const size = formatBytes(num(p, 'bytes'));
  return (
    <ToolShell
      record={record}
      icon={<Paperclip size={14} />}
      title={name}
      subtitle={str(p, 'media_type')}
      defaultOpen
      chips={
        size ? (
          <span className="rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-muted">
            {size}
          </span>
        ) : null
      }
    >
      {str(p, 'ref') ? (
        <p className="break-all font-mono text-[12px] text-text-secondary">{str(p, 'ref')}</p>
      ) : null}
    </ToolShell>
  );
}

/**
 * 报错卡。**只有范围、代码、消息三行，没有「查看原文」入口。**
 *
 * 那条原文的响应头里带着 Cloudflare 的登录凭据。服务端对报错类取原文恒回 403，界面这
 * 一层连按钮都不渲染——两道都要有，任何一道都不许省。
 */
function ErrorCard({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  return (
    <article
      data-kind={record.kind}
      data-group="system"
      className={`min-w-0 rounded-[8px] px-3 py-2 ${ERR_BG} ${ERR_RING}`}
    >
      <header className="mb-1.5 flex items-center gap-2">
        <AlertTriangle size={14} className={ERR_TEXT} />
        <span className={`text-[13px] font-semibold ${ERR_TEXT}`}>
          {t(KIND_LABEL_KEY.error)}
        </span>
        <span className="flex-1" />
        <AgentPath path={record.agent_path} />
        <Timestamp ts={record.ts} />
      </header>
      <dl className="space-y-1 text-[12px]">
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-text-muted">{t('workbench.record.errScope')}</dt>
          <dd className="min-w-0 break-words font-mono text-text-secondary">
            {str(p, 'scope')}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-text-muted">{t('workbench.record.errCode')}</dt>
          <dd className="min-w-0 break-words font-mono text-text-secondary">{str(p, 'code')}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-text-muted">{t('workbench.record.errMessage')}</dt>
          <dd className="min-w-0 whitespace-pre-wrap break-words text-text-primary">
            {str(p, 'message')}
          </dd>
        </div>
      </dl>
      <p className="mt-2 flex items-center gap-1 text-[11px] text-text-muted">
        <Lock size={11} />
        {t('workbench.record.rawWithheld')}
      </p>
    </article>
  );
}

function Interrupt({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const phase = str(p, 'phase');
  const phaseText =
    phase === 'tool' || phase === 'tool-executing'
      ? t('workbench.record.phaseTool')
      : phase === 'generating'
        ? t('workbench.record.phaseGenerating')
        : '';
  return (
    <div
      data-kind={record.kind}
      data-group="system"
      className="flex min-w-0 items-center gap-2 py-1"
    >
      <span className="h-px flex-1 border-t border-dashed border-border-color" />
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-bg-subtle px-2.5 py-1 text-[11px] text-text-secondary">
        <Scissors size={11} />
        {t('workbench.record.interrupted')}
        {phaseText ? <span className="text-text-muted">· {phaseText}</span> : null}
        <span className="font-mono text-text-muted">{formatClock(record.ts)}</span>
      </span>
      <span className="h-px flex-1 border-t border-dashed border-border-color" />
    </div>
  );
}

function SessionState({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const from = str(p, 'from');
  const to = str(p, 'to');
  const FIELD_KEY: Record<string, string> = {
    title: 'workbench.record.stateField.title',
    model: 'workbench.record.stateField.model',
    agent: 'workbench.record.stateField.agent',
    mode: 'workbench.record.stateField.mode',
    'permission-mode': 'workbench.record.stateField.permissionMode',
  };
  const field = str(p, 'field');
  return (
    <SystemShell
      record={record}
      icon={<Circle size={7} className="text-text-muted" />}
      label={
        <span className="text-text-secondary">
          {FIELD_KEY[field] ? t(FIELD_KEY[field]) : field}
        </span>
      }
      meta={
        <span className="font-mono">
          {from ? `${from} → ` : ''}
          <span className="text-text-primary">{to || t('workbench.record.emptyValue')}</span>
        </span>
      }
    />
  );
}

function ContextCompact({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const before = num(p, 'tokens_before');
  const after = num(p, 'tokens_after');
  return (
    <SystemShell
      record={record}
      icon={<Minimize2 size={12} className="text-text-muted" />}
      label={
        <span className="text-text-secondary">{t(KIND_LABEL_KEY['context.compact'])}</span>
      }
      meta={
        <span className="font-mono">
          {str(p, 'trigger') ? `${str(p, 'trigger')} · ` : ''}
          {before !== null ? t('workbench.record.compactBefore', { n: before }) : ''}
          {before !== null && after !== null ? ' → ' : ''}
          {after !== null ? t('workbench.record.compactAfter', { n: after }) : ''}
        </span>
      }
      collapsible
    >
      <Prose text={str(p, 'summary_text')} />
    </SystemShell>
  );
}

function CallEnvelope({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const facts: string[] = [];
  const duration = formatDuration(num(p, 'duration_ms'));
  if (duration) facts.push(t('workbench.record.spent', { duration }));
  const messages = num(p, 'message_count');
  if (messages !== null) facts.push(t('workbench.record.messageCount', { n: messages }));
  if (str(p, 'finish_reason')) {
    facts.push(t('workbench.record.finishReason', { reason: str(p, 'finish_reason') }));
  }
  const tokens = dict(p.tokens);
  for (const [key, labelKey] of [
    ['input', 'workbench.record.tokenIn'],
    ['output', 'workbench.record.tokenOut'],
  ] as const) {
    const v = tokens[key];
    if (typeof v === 'number') {
      facts.push(t('workbench.record.tokenFact', { label: t(labelKey), n: v }));
    }
  }
  const starts = num(p, 'step_start_count');
  const finishes = num(p, 'step_finish_count');
  if (starts !== null && finishes !== null && starts !== finishes) {
    facts.push(t('workbench.record.markersMissing'));
  }
  const phase = str(p, 'phase');
  return (
    <SystemShell
      record={record}
      icon={<Clock size={11} className="text-text-muted" />}
      label={
        <span className="text-text-muted">
          {t(KIND_LABEL_KEY['call.envelope'])}
          {phase === 'start'
            ? t('workbench.record.phaseStart')
            : phase === 'finish'
              ? t('workbench.record.phaseFinish')
              : ''}
        </span>
      }
      meta={<span className="font-mono">{facts.join(' · ')}</span>}
    />
  );
}

/** 千分位。六位数字连成一串谁也读不出量级，而这一格全是六七位的数。 */
function formatTokens(n: number): string {
  // 分位符固定用英文那一套：中文环境下的分位也是逗号，两种语言看到的是同一个形状。
  return n.toLocaleString('en-US');
}

/**
 * 一次调用返回后的用量刻度。
 *
 * **头一行只报两个数，因为人问的只有这两件事**：这场此刻占了多大上下文，一路下来一共
 * 烧了多少。两个数意思不一样——上下文是**水位**，会随一次压缩掉下去；累计是**流水**，
 * 只增不减。摆在一起才看得出"涨的是哪一个"。
 *
 * 本轮那个数和它的四项明细收在折叠里。它是累计的构成，不是人一眼要找的东西；而且缓存
 * 读取每一轮都要把整段上下文再读一遍，本轮那个数因此几乎总是贴着上下文的数走，两个数
 * 并排摆着只会让人以为自己看重了。
 *
 * 一个百分比都不出现：本文件第 3 条纪律，界面不呈现任何进度，只报已发生的绝对数。
 */
function UsageTick({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  const p = record.payload;
  const context = num(p, 'context_tokens');
  const total = num(p, 'total_tokens');
  const turn = num(p, 'turn_tokens');
  const breakdown = dict(p.breakdown);
  /** 展开后的每一行：左边一个名目，右边一个数。 */
  const rows: { key: string; label: string; value: string }[] = [];
  if (turn !== null) {
    rows.push({
      key: 'turn',
      label: t('workbench.record.usage.turn'),
      value: formatTokens(turn),
    });
  }
  for (const [key, labelKey] of [
    ['input', 'workbench.record.usage.input'],
    ['output', 'workbench.record.usage.output'],
    ['cache_creation', 'workbench.record.usage.cacheCreation'],
    ['cache_read', 'workbench.record.usage.cacheRead'],
  ] as const) {
    const value = breakdown[key];
    // 零的那一项不摆。四项里常有两项是零，全摆出来会把真正在动的那两项淹掉。
    if (typeof value === 'number' && value > 0) {
      rows.push({ key, label: t(labelKey), value: formatTokens(value) });
    }
  }
  const headline: string[] = [];
  if (context !== null) {
    headline.push(`${t('workbench.record.usage.context')} ${formatTokens(context)}`);
  }
  if (total !== null) {
    headline.push(`${t('workbench.record.usage.total')} ${formatTokens(total)}`);
  }
  return (
    <SystemShell
      record={record}
      icon={<Gauge size={12} className="text-text-muted" />}
      label={<span className="text-text-secondary">{t(KIND_LABEL_KEY['usage.tick'])}</span>}
      meta={<span className="font-mono">{headline.join(' · ')}</span>}
      collapsible
    >
      {/* 一项一行，数字右对齐。挤成一行时"入 2 · 出 463 · 缓存写 850 · 缓存读 205,461"
          要从左读到右才找得到某一项，而且四个数的位数差着三个量级，对不齐就比不出大小。 */}
      <dl className="space-y-0.5 text-[11px]">
        {rows.map((row) => (
          <div key={row.key} className="flex gap-2">
            <dt className="w-20 shrink-0 text-text-muted">{row.label}</dt>
            <dd className="w-24 shrink-0 text-right font-mono tabular-nums text-text-secondary">
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </SystemShell>
  );
}

// ── 分发 ──────────────────────────────────────────────────────────────
export interface RecordCardProps {
  record: WorkbenchRecord;
  /** 取原文要带会话编号——记录编号自己定位不到档案。 */
  sessionId: string;
}

/**
 * 一条记录 = 一张卡。**必须记忆化**：中栏一屏挂着两百张卡，agent 每吐一条新记录就要
 * 重渲染一次整栏；不记忆化的话那两百张全部重跑一遍分发与格式化，追加越密越卡，正是
 * "会话在跑的时候滚动很慢"的那一半原因。记录对象翻出来就不再改动，按引用比就够。
 */
function RecordCardInner({ record, sessionId }: RecordCardProps) {
  switch (record.kind) {
    // 文本类
    case 'user.say':
      return <UserSay record={record} />;
    case 'agent.say':
      return <AgentSay record={record} />;
    case 'agent.think':
      return <AgentThink record={record} />;
    case 'context.inject':
      // 旁路注入自成一格。判据是数据层给的 `source`，界面 NEVER 靠标签名反推——
      // 标签是给人看的，改一个字就会把归类改掉。
      // 插话自成一格：判据取数据层给的 `channel`，界面 NEVER 靠标签名反推——
      // 标签是给人看的，改一个字就会把归类改掉。
      if (record.payload.channel === 'queued_command') {
        return <QueuedCommand record={record} />;
      }
      if (record.payload.source === 'task-notification') {
        return <TaskNotification record={record} />;
      }
      if (record.payload.source === 'local-command') {
        return <LocalCommandOutput record={record} />;
      }
      return record.payload.source === 'hook' ? (
        <HookInject record={record} />
      ) : (
        <ContextInject record={record} />
      );
    // 工具类
    case 'tool.call':
      return <ToolCall record={record} />;
    case 'tool.result':
      return <ToolResult record={record} sessionId={sessionId} />;
    case 'subagent.dispatch':
      return <SubagentDispatch record={record} />;
    case 'todo.snapshot':
      return <TodoSnapshot record={record} />;
    case 'permission.outcome':
      return <PermissionOutcome record={record} />;
    case 'media.attach':
      return <MediaAttach record={record} />;
    // 系统类
    case 'error':
      return <ErrorCard record={record} />;
    case 'interrupt':
      return <Interrupt record={record} />;
    case 'session.state':
      return <SessionState record={record} />;
    case 'context.compact':
      return <ContextCompact record={record} />;
    case 'call.envelope':
      return <CallEnvelope record={record} />;
    case 'usage.tick':
      return <UsageTick record={record} />;
    default:
      // 十六种之外的形态在核心数据层就被拦住了（`UnifiedRecord.__post_init__` 会炸）。
      // 真跑到这里说明两边的形态清单脱了节，显示出来而不是静默丢弃。
      return <UnknownKind record={record} />;
  }
}

/** 分发那一支的兜底卡。单独成一个组件，是为了让取字这件事发生在组件里。 */
function UnknownKind({ record }: { record: WorkbenchRecord }) {
  const { t } = useTranslation();
  return (
    <SystemShell
      record={record}
      icon={<AlertTriangle size={12} className={ERR_TEXT} />}
      label={<span className={ERR_TEXT}>{t('workbench.record.unknownKind')}</span>}
      meta={String(record.kind)}
    />
  );
}

const RecordCard = memo(RecordCardInner);
RecordCard.displayName = 'RecordCard';

export default RecordCard;
