/**
 * RecordCard — 一条统一记录 = 一张卡片。
 *
 * 十五种形态**不是十五个平行分支**。按 spec 风险表的办法分三组，组内只换内容区：
 *
 * | 组 | 外壳 | 形态 |
 * |---|---|---|
 * | 文本类 | `TextShell` | user.say / agent.say / agent.think / context.inject |
 * | 工具类 | `ToolShell` | tool.call / tool.result / subagent.dispatch / todo.snapshot / permission.outcome / media.attach |
 * | 系统类 | `SystemShell` | error / interrupt / session.state / context.compact / call.envelope |
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

import { useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  Bot,
  Braces,
  ChevronRight,
  Circle,
  Clock,
  Download,
  FileText,
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
} from 'lucide-react';
import {
  fetchWorkbenchRaw,
  type RecordKind,
  type WorkbenchRecord,
} from '@/hooks/useWorkbenchRecords';

// ── 配色 ──────────────────────────────────────────────────────────────
// 强调位（子轨迹、子 agent、正在做的那一项）由品牌绿承担，走主题变量，明暗两套各取各的
// 那一份，NEVER 写死色值。其余状态色照抄设计稿，写成完整字面量而不是拼接——Tailwind 的
// 扫描器只认字面量。
const ACCENT_TEXT = 'text-accent-primary';
const ACCENT_BG = 'bg-accent-primary-10';
const ACCENT_RING = 'ring-1 ring-border-accent';
const ERR_TEXT = 'text-[#E4705C] [[data-theme=light]_&]:text-[#A8442F]';
const ERR_BG = 'bg-[#E4705C]/[0.12] [[data-theme=light]_&]:bg-[#A8442F]/[0.11]';
const ERR_RING = 'ring-1 ring-[#E4705C]/35 [[data-theme=light]_&]:ring-[#A8442F]/30';
const WAIT_TEXT = 'text-[#E3A857] [[data-theme=light]_&]:text-[#9A6E1B]';
const WAIT_BG = 'bg-[#E3A857]/[0.12] [[data-theme=light]_&]:bg-[#9A6E1B]/[0.11]';
const OK_TEXT = 'text-[#8FC29A] [[data-theme=light]_&]:text-[#4C7A56]';
const DONE_TEXT = 'text-[#8DB5AC] [[data-theme=light]_&]:text-[#56736E]';
const DONE_BG = 'bg-[#8DB5AC]/[0.12] [[data-theme=light]_&]:bg-[#56736E]/[0.11]';

// ── 三组归属 ──────────────────────────────────────────────────────────
export type KindGroup = 'text' | 'tool' | 'system';

/** 十五种形态各落在哪一组。测试拿它断言分组穷尽且不重叠。 */
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
};

/** 形态在界面上叫什么。取中文，NEVER 把机器标记名直接摆给人看。 */
export const KIND_LABEL: Record<RecordKind, string> = {
  'user.say': '你说',
  'agent.say': '回复',
  'agent.think': '思考',
  'context.inject': '注入内容',
  'tool.call': '工具调用',
  'tool.result': '工具结果',
  'subagent.dispatch': '派发子 agent',
  'todo.snapshot': '待办清单',
  'permission.outcome': '权限结果',
  'media.attach': '附件',
  error: '报错',
  interrupt: '打断',
  'session.state': '状态变更',
  'context.compact': '上下文压缩',
  'call.envelope': '调用边界',
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

/** 毫秒 → 人话。只报已经发生的时长，NEVER 报预计还要多久。 */
export function formatDuration(ms: number | null): string {
  if (ms === null || ms < 0) return '';
  if (ms < 1000) return `${ms} 毫秒`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} 秒`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`;
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes < 0) return '';
  if (bytes < 1024) return `${bytes} 字节`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
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
const TOOL_FAMILY_LABEL: Record<string, string> = {
  shell: '命令',
  'file-read': '读',
  'file-write': '写',
  search: '搜',
  web: '网',
  agent: '派发',
  todo: '待办',
  ask: '问你',
  schedule: '定时',
  mcp: '外接',
  other: '其他',
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

const STATUS_TEXT: Record<string, string> = {
  ok: '成功',
  error: '失败',
  denied: '被拒',
  interrupted: '被打断',
  completed: '已完成',
  pending: '未回',
};

/** 状态一律带文字标签，颜色不是唯一通道——拿掉颜色也读得出。 */
function StatusChip({ status }: { status: string }) {
  if (!status) return null;
  const tone =
    status === 'error'
      ? `${ERR_BG} ${ERR_TEXT}`
      : status === 'denied' || status === 'interrupted'
        ? `${WAIT_BG} ${WAIT_TEXT}`
        : `${DONE_BG} ${OK_TEXT}`;
  return (
    <span className={`rounded-full px-2 py-[1px] text-[11px] leading-[1.45] ${tone}`}>
      {STATUS_TEXT[status] ?? status}
    </span>
  );
}

/** 截断三态。三者一眼可辨，且各自带图标加文字。 */
function TruncationChip({ state, ref_ }: { state: string; ref_: string }) {
  if (state === 'clipped') {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded-full px-2 py-[1px] text-[11px] ${ERR_BG} ${ERR_TEXT}`}
      >
        <Scissors size={11} />
        中段内容已永久丢失
      </span>
    );
  }
  if (state === 'offloaded') {
    return (
      <span
        className={`inline-flex max-w-full items-center gap-1 rounded-full px-2 py-[1px] text-[11px] ${DONE_BG} ${DONE_TEXT}`}
      >
        <FileText size={11} />
        <span className="truncate font-mono">全文在别处{ref_ ? `：${ref_}` : ''}</span>
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
  if (!path.length) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-[1px] text-[11px] ${ACCENT_BG} ${ACCENT_TEXT}`}
    >
      <Bot size={10} />
      子轨迹
    </span>
  );
}

/**
 * 文本类外壳：正文优先，容器尽量轻。头部一行是标签、时刻与可折叠开关，正文由调用方给。
 */
function TextShell({
  record,
  icon,
  label,
  meta,
  tone = '',
  collapsible = false,
  defaultOpen = true,
  children,
}: ShellProps & {
  icon?: ReactNode;
  label: string;
  meta?: ReactNode;
  tone?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <article
      data-kind={record.kind}
      data-group={KIND_GROUP[record.kind]}
      className={`rounded-[10px] px-3 py-2.5 ${tone || 'bg-bg-card'} min-w-0`}
    >
      <header className="mb-1.5 flex items-center gap-2 text-[11px] text-text-muted">
        {collapsible ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="inline-flex items-center gap-1 text-text-secondary hover:text-text-primary"
            aria-expanded={open}
          >
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            />
            {icon}
            <span>{label}</span>
          </button>
        ) : (
          <span className="inline-flex items-center gap-1 text-text-secondary">
            {icon}
            {label}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{meta}</span>
        <AgentPath path={record.agent_path} />
        <Timestamp ts={record.ts} />
      </header>
      {open ? <div className="min-w-0">{children}</div> : null}
    </article>
  );
}

/**
 * 工具类外壳：卡头（家族图标 + 名字 + 一行预览 + 状态）压在卡身上面，卡身装输出。
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
  defaultOpen = true,
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
  const [open, setOpen] = useState(defaultOpen);
  const hasBody = Boolean(children);
  return (
    <article
      data-kind={record.kind}
      data-group={KIND_GROUP[record.kind]}
      className={`min-w-0 overflow-hidden rounded-[6px] border border-border-color bg-bg-secondary ${ringTone}`}
    >
      <header className={`flex items-center gap-2 px-3 py-2 ${headTone || 'bg-bg-card'}`}>
        {collapsible && hasBody ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 text-text-muted hover:text-text-primary"
            aria-expanded={open}
            aria-label="展开或收起"
          >
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            />
          </button>
        ) : null}
        <span className="shrink-0 text-text-secondary">{icon}</span>
        <span className="shrink-0 font-mono text-[13px] font-semibold text-text-primary">
          {title}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-muted">
          {subtitle}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {chips}
          <AgentPath path={record.agent_path} />
          <Timestamp ts={record.ts} />
        </span>
      </header>
      {hasBody && open ? <div className="min-w-0 px-3 py-2.5">{children}</div> : null}
    </article>
  );
}

/**
 * 系统类外壳：不是对话，是发生在会话上的事。默认横贯一行，正文可有可无。
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
  const [open, setOpen] = useState(defaultOpen);
  const hasBody = Boolean(children);
  return (
    <article
      data-kind={record.kind}
      data-group={KIND_GROUP[record.kind]}
      className={`min-w-0 rounded-[6px] px-3 py-2 ${tone || 'bg-bg-subtle'}`}
    >
      <div className="flex items-center gap-2 text-[12px]">
        {collapsible && hasBody ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="shrink-0 text-text-muted hover:text-text-primary"
            aria-expanded={open}
            aria-label="展开或收起"
          >
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
            />
          </button>
        ) : null}
        <span className="shrink-0">{icon}</span>
        <span className="shrink-0">{label}</span>
        <span className="min-w-0 flex-1 truncate text-[11px] text-text-muted">{meta}</span>
        <AgentPath path={record.agent_path} />
        <Timestamp ts={record.ts} />
      </div>
      {hasBody && open ? <div className="mt-2 min-w-0">{children}</div> : null}
    </article>
  );
}

// ── 正文块 ────────────────────────────────────────────────────────────
/** 中文正文：14px / 1.72。长会话一路读下来，这个行高比 1.5 明显省力。 */
function Prose({ text }: { text: string }) {
  if (!text) return <p className="text-[13px] italic text-text-muted">（正文为空）</p>;
  return (
    <p className="whitespace-pre-wrap break-words text-[14px] leading-[1.72] text-text-primary">
      {text}
    </p>
  );
}

/**
 * 等宽输出块。最高 230px，超出**在块内滚**，不撑页面。
 * 230px 约十二行，够看出这次调用干了什么，又不至于把一屏占满。
 */
function Mono({ text }: { text: string }) {
  if (!text) return <p className="text-[12px] italic text-text-muted">（没有输出）</p>;
  return (
    <pre className="max-h-[230px] overflow-auto whitespace-pre-wrap break-words rounded-[3px] bg-bg-subtle p-2 font-mono text-[12px] leading-[1.6] text-text-secondary">
      {text}
    </pre>
  );
}

// ── 十五种形态的内容区 ────────────────────────────────────────────────
function UserSay({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const images = list(p, 'images');
  return (
    <TextShell
      record={record}
      icon={<User size={12} />}
      label="你说"
      tone="bg-bg-card rounded-tl-[3px]"
      meta={str(p, 'input_mode') ? `输入方式 ${str(p, 'input_mode')}` : undefined}
    >
      <Prose text={str(p, 'text')} />
      {images.length ? (
        <p className="mt-1.5 text-[11px] text-text-muted">随附图片 {images.length} 张</p>
      ) : null}
    </TextShell>
  );
}

function AgentSay({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  return (
    <TextShell
      record={record}
      icon={<Bot size={12} />}
      label="回复"
      tone="bg-transparent"
      meta={str(p, 'model')}
    >
      <Prose text={str(p, 'text')} />
    </TextShell>
  );
}

function AgentThink({ record }: { record: WorkbenchRecord }) {
  const text = str(record.payload, 'text');
  return (
    <TextShell
      record={record}
      icon={<Circle size={10} />}
      label="思考"
      tone="border border-dashed border-border-color bg-transparent"
      meta={`${text.length} 字`}
      collapsible
      defaultOpen={false}
    >
      <p className="whitespace-pre-wrap break-words text-[13px] leading-[1.72] text-text-secondary">
        {text}
      </p>
    </TextShell>
  );
}

function ContextInject({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const files = list(p, 'files');
  const exit = num(p, 'exit_code');
  const unrecognized = p.unrecognized === true;
  const label = str(p, 'label') || str(p, 'channel') || '注入内容';
  return (
    <TextShell
      record={record}
      icon={<Download size={12} />}
      label={unrecognized ? `未识别 · ${label}` : label}
      tone="bg-bg-subtle"
      meta={
        <span className="flex items-center gap-2">
          <span className="truncate">{str(p, 'channel')}</span>
          {exit !== null ? <span className="font-mono">退出码 {exit}</span> : null}
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
  const p = record.payload;
  const family = str(p, 'tool_family') || 'other';
  return (
    <ToolShell
      record={record}
      icon={toolIcon(family)}
      title={str(p, 'tool_name') || '（无名工具）'}
      subtitle={str(p, 'title') || previewArgs(dict(p.args))}
      chips={
        <span className="rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-muted">
          {TOOL_FAMILY_LABEL[family] ?? family}
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
  return (
    <ToolShell
      record={record}
      icon={<Terminal size={14} />}
      title={str(p, 'tool_name') || '工具结果'}
      subtitle={duration ? `耗时 ${duration}` : undefined}
      chips={
        <>
          <TruncationChip state={truncation} ref_={str(p, 'truncation_ref')} />
          <StatusChip status={str(p, 'status')} />
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
            {rawLoading ? '取原文…' : '取原文'}
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
  const p = record.payload;
  const stats = dict(p.stats);
  // 允许出现的量只有已发生的绝对数：调了几次工具、多少 token、跑了多久。
  const facts: string[] = [];
  const tokens = typeof stats.total_tokens === 'number' ? stats.total_tokens : null;
  const calls =
    typeof stats.total_tool_use_count === 'number' ? stats.total_tool_use_count : null;
  const spent =
    typeof stats.total_duration_ms === 'number' ? stats.total_duration_ms : num(p, 'duration_ms');
  if (calls !== null) facts.push(`调用工具 ${calls} 次`);
  if (tokens !== null) facts.push(`${tokens} token`);
  if (spent !== null) facts.push(`历时 ${formatDuration(spent)}`);

  return (
    <ToolShell
      record={record}
      icon={<Bot size={14} />}
      title={str(p, 'agent_type') || '子 agent'}
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
          <p className="mb-1 text-[11px] text-text-muted">派发时交代的话</p>
          <Mono text={str(p, 'prompt')} />
        </div>
      ) : null}
      {str(p, 'content') || str(p, 'body') ? (
        <div>
          <p className="mb-1 text-[11px] text-text-muted">子 agent 交回来的东西</p>
          <Mono text={str(p, 'content') || str(p, 'body')} />
        </div>
      ) : null}
      {p.trace_available === false ? (
        <p className="mt-1.5 text-[11px] text-text-muted">这次派发没有留下轨迹文件</p>
      ) : null}
    </ToolShell>
  );
}

function TodoSnapshot({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const items = list(p, 'items');
  // 引擎被动重发的清单一个字没改也发，默认折叠；agent 主动写入的展开。
  const passive = str(p, 'source') === 'engine-reminder';
  return (
    <ToolShell
      record={record}
      icon={<ListChecks size={14} />}
      title="待办清单"
      subtitle={passive ? '引擎重发' : 'agent 写入'}
      chips={
        <span className="rounded-full bg-bg-subtle px-2 py-[1px] text-[11px] text-text-muted">
          {items.length} 条
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
  const p = record.payload;
  return (
    <ToolShell
      record={record}
      icon={<ShieldAlert size={14} />}
      title={str(p, 'tool_name') || '权限结果'}
      subtitle={str(p, 'reason')}
      headTone={WAIT_BG}
      chips={
        <span className={`rounded-full px-2 py-[1px] text-[11px] ${WAIT_BG} ${WAIT_TEXT}`}>
          {str(p, 'decision') === 'denied' ? '被拒' : str(p, 'decision')}
        </span>
      }
    >
      {str(p, 'mode') ? (
        <p className="font-mono text-[11px] text-text-muted">权限模式 {str(p, 'mode')}</p>
      ) : null}
    </ToolShell>
  );
}

function MediaAttach({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const name = str(p, 'display_name') || str(p, 'ref') || '附件';
  const size = formatBytes(num(p, 'bytes'));
  return (
    <ToolShell
      record={record}
      icon={<Paperclip size={14} />}
      title={name}
      subtitle={str(p, 'media_type')}
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
  const p = record.payload;
  return (
    <article
      data-kind={record.kind}
      data-group="system"
      className={`min-w-0 rounded-[6px] px-3 py-2.5 ${ERR_BG} ${ERR_RING}`}
    >
      <header className="mb-1.5 flex items-center gap-2">
        <AlertTriangle size={14} className={ERR_TEXT} />
        <span className={`text-[13px] font-semibold ${ERR_TEXT}`}>报错</span>
        <span className="flex-1" />
        <AgentPath path={record.agent_path} />
        <Timestamp ts={record.ts} />
      </header>
      <dl className="space-y-1 text-[12px]">
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-text-muted">范围</dt>
          <dd className="min-w-0 break-words font-mono text-text-secondary">
            {str(p, 'scope')}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-text-muted">代码</dt>
          <dd className="min-w-0 break-words font-mono text-text-secondary">{str(p, 'code')}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-12 shrink-0 text-text-muted">消息</dt>
          <dd className="min-w-0 whitespace-pre-wrap break-words text-text-primary">
            {str(p, 'message')}
          </dd>
        </div>
      </dl>
      <p className="mt-2 flex items-center gap-1 text-[11px] text-text-muted">
        <Lock size={11} />
        原文带登录凭据，不予提供
      </p>
    </article>
  );
}

function Interrupt({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const phase = str(p, 'phase');
  const phaseText =
    phase === 'tool' || phase === 'tool-executing'
      ? '工具正在跑的时候'
      : phase === 'generating'
        ? '模型正在写的时候'
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
        你按了停止
        {phaseText ? <span className="text-text-muted">· {phaseText}</span> : null}
        <span className="font-mono text-text-muted">{formatClock(record.ts)}</span>
      </span>
      <span className="h-px flex-1 border-t border-dashed border-border-color" />
    </div>
  );
}

function SessionState({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const from = str(p, 'from');
  const to = str(p, 'to');
  const FIELD: Record<string, string> = {
    title: '标题',
    model: '模型',
    agent: 'agent',
    mode: '模式',
    'permission-mode': '权限模式',
  };
  const field = str(p, 'field');
  return (
    <SystemShell
      record={record}
      icon={<Circle size={7} className="text-text-muted" />}
      label={<span className="text-text-secondary">{FIELD[field] ?? field}</span>}
      meta={
        <span className="font-mono">
          {from ? `${from} → ` : ''}
          <span className="text-text-primary">{to || '（空）'}</span>
        </span>
      }
    />
  );
}

function ContextCompact({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const before = num(p, 'tokens_before');
  const after = num(p, 'tokens_after');
  return (
    <SystemShell
      record={record}
      icon={<Minimize2 size={12} className="text-text-muted" />}
      label={<span className="text-text-secondary">上下文压缩</span>}
      meta={
        <span className="font-mono">
          {str(p, 'trigger') ? `${str(p, 'trigger')} · ` : ''}
          {before !== null ? `压缩前 ${before} token` : ''}
          {before !== null && after !== null ? ' → ' : ''}
          {after !== null ? `压缩后 ${after} token` : ''}
        </span>
      }
      collapsible
    >
      <Prose text={str(p, 'summary_text')} />
    </SystemShell>
  );
}

function CallEnvelope({ record }: { record: WorkbenchRecord }) {
  const p = record.payload;
  const facts: string[] = [];
  const duration = formatDuration(num(p, 'duration_ms'));
  if (duration) facts.push(`历时 ${duration}`);
  const messages = num(p, 'message_count');
  if (messages !== null) facts.push(`${messages} 条消息`);
  if (str(p, 'finish_reason')) facts.push(`结束于 ${str(p, 'finish_reason')}`);
  const tokens = dict(p.tokens);
  for (const [key, label] of [
    ['input', '入'],
    ['output', '出'],
  ] as const) {
    const v = tokens[key];
    if (typeof v === 'number') facts.push(`${label} ${v} token`);
  }
  const starts = num(p, 'step_start_count');
  const finishes = num(p, 'step_finish_count');
  if (starts !== null && finishes !== null && starts !== finishes) {
    facts.push('这条消息里的边界标记缺一半');
  }
  const phase = str(p, 'phase');
  return (
    <SystemShell
      record={record}
      icon={<Clock size={11} className="text-text-muted" />}
      label={
        <span className="text-text-muted">
          调用边界
          {phase === 'start' ? ' · 开始' : phase === 'finish' ? ' · 结束' : ''}
        </span>
      }
      meta={<span className="font-mono">{facts.join(' · ')}</span>}
    />
  );
}

// ── 分发 ──────────────────────────────────────────────────────────────
export interface RecordCardProps {
  record: WorkbenchRecord;
  /** 取原文要带会话编号——记录编号自己定位不到档案。 */
  sessionId: string;
}

export default function RecordCard({ record, sessionId }: RecordCardProps) {
  switch (record.kind) {
    // 文本类
    case 'user.say':
      return <UserSay record={record} />;
    case 'agent.say':
      return <AgentSay record={record} />;
    case 'agent.think':
      return <AgentThink record={record} />;
    case 'context.inject':
      return <ContextInject record={record} />;
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
    default:
      // 十五种之外的形态在核心数据层就被拦住了（`UnifiedRecord.__post_init__` 会炸）。
      // 真跑到这里说明两边的形态清单脱了节，显示出来而不是静默丢弃。
      return (
        <SystemShell
          record={record}
          icon={<AlertTriangle size={12} className={ERR_TEXT} />}
          label={<span className={ERR_TEXT}>界面认不出的记录形态</span>}
          meta={String((record as WorkbenchRecord).kind)}
        />
      );
  }
}
