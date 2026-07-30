/**
 * SessionRail — 左栏：新建会话、搜索、时间范围、状态筛选、会话清单、底部汇总。
 *
 * 两家（Claude Code / opencode）的会话在核心数据层就合并排好了，这里不重排。
 *
 * **筛选是两个维度，不是一个。** 状态答「现在什么情况」，时间范围答「哪一段时间的」，
 * 两者并存、互不替代。按来源筛的那一维不在这里——一千多场 Claude Code 会话摆在一起，
 * 知道它们都来自 Claude Code 没有任何用；来源仍在每张卡上看得见，改由底部汇总报两家各几场。
 *
 * **状态与摘要一个字都不在这里推导。** 服务端已经判完四档、填好两格摘要，界面照着显示。
 * 摆两处判据迟早各走各的，那时中栏和左栏会对同一场会话说两种话。
 *
 * **选中态不用左侧竖条。** 整卡换成品牌绿淡底、加一圈品牌绿环、标题转品牌绿。单边竖条
 * 是肌肉记忆，不是设计决策。
 *
 * **颜色一律走 CSS 变量。** 明暗两套主题各有一份品牌绿，写死色值会让其中一套失真。
 *
 * 底部汇总只报已经发生的绝对数：共几场、两家各几场。没有分母，也不该有。
 *
 * **列表走窗口化渲染。** 全量会话可能上千场，用 Virtuoso 只渲染视口内可见的卡片。
 */

import { useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { Loader2, Plus, RefreshCw, Search, X } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import SessionItem, { resumeCommand } from './SessionItem';
import NewSessionModal from './NewSessionModal';
import {
  DAY_OPTIONS,
  STATUS_LABEL,
  type DayRange,
  type StatusFilter,
  type WorkbenchSession,
  type WorkbenchSessionsState,
} from '@/hooks/useWorkbenchSessions';

/** 品牌绿承担选中、当前、活跃。三处共用一套，别处不许再造。 */
const ACCENT_TEXT = 'text-accent-primary';
const ACCENT_BG = 'bg-accent-primary-10';

/** 四档筛选加一个全部。次序与判定顺序一致，看的人不必再学一套排列。 */
const FILTERS: StatusFilter[] = ['all', 'running', 'error', 'done', 'idle'];

const FILTER_LABEL: Record<StatusFilter, string> = { all: '全部', ...STATUS_LABEL };

/** 时间范围：不限，加四档。0 排在最前，与状态那一行的「全部」对齐。 */
const DAY_FILTERS: DayRange[] = [0, ...DAY_OPTIONS];

/**
 * 每一档点与字的颜色。停着不给红或黄——两百多场停着是会话正常的归宿。
 */
const STATUS_DOT: Record<string, string> = {
  running: 'bg-accent-primary',
  error: 'bg-accent-error',
  done: 'bg-accent-info',
  idle: 'bg-text-muted',
};

export interface SessionRailProps {
  state: WorkbenchSessionsState;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function SessionRail({ state, selectedId, onSelect }: SessionRailProps) {
  const {
    sessions,
    visible,
    counts,
    loading,
    error,
    search,
    setSearch,
    status,
    setStatus,
    days,
    setDays,
    reload,
  } = state;
  const showToast = useAppStore((s) => s.showToast);
  const [newOpen, setNewOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const familyCounts = useMemo(() => {
    let cc = 0;
    let oc = 0;
    for (const s of sessions) {
      if (s.family === 'claude-code') cc += 1;
      else if (s.family === 'opencode') oc += 1;
    }
    return { cc, oc };
  }, [sessions]);

  const handleCopy = async (session: WorkbenchSession) => {
    try {
      await navigator.clipboard.writeText(resumeCommand(session));
      setCopiedId(session.session_id);
      showToast('恢复命令已复制', 'success');
      setTimeout(() => setCopiedId((cur) => (cur === session.session_id ? null : cur)), 1500);
    } catch {
      showToast('复制失败', 'error');
    }
  };

  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-r border-border-color bg-bg-secondary">
      <div className="shrink-0 space-y-2 border-b border-border-color px-3 py-3">
        <button
          type="button"
          onClick={() => setNewOpen(true)}
          data-testid="new-session"
          className="flex w-full items-center justify-center gap-1.5 rounded-[6px] bg-accent-primary px-2 py-1.5 text-[12px] font-semibold text-[var(--text-on-accent)] transition-opacity duration-200 hover:opacity-90"
        >
          <Plus size={13} />
          <span>新建会话</span>
        </button>

        <div className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5 rounded-[6px] border border-border-color bg-bg-card px-2 py-1.5 focus-within:border-accent-primary">
            <Search size={13} className="shrink-0 text-text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜标题、目录、会话编号"
              aria-label="搜会话"
              className="w-full min-w-0 bg-transparent text-[12px] text-text-primary outline-none placeholder:text-text-muted"
            />
            {search ? (
              <button
                type="button"
                onClick={() => setSearch('')}
                aria-label="清空搜索"
                className="shrink-0 text-text-muted hover:text-text-primary"
              >
                <X size={12} />
              </button>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => void reload()}
            disabled={loading}
            aria-label="重新拉清单"
            className="shrink-0 rounded-[6px] border border-border-color p-1.5 text-text-muted hover:text-text-primary disabled:opacity-50"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {DAY_FILTERS.map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              aria-pressed={days === d}
              data-testid={`day-filter-${d}`}
              className={`rounded-full px-2.5 py-[3px] text-[11px] transition-colors duration-200 ${
                days === d
                  ? `${ACCENT_BG} ${ACCENT_TEXT}`
                  : 'bg-bg-card text-text-muted hover:text-text-secondary'
              }`}
            >
              {d === 0 ? '不限' : `${d} 天`}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setStatus(id)}
              aria-pressed={status === id}
              data-testid={`status-filter-${id}`}
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-[3px] text-[11px] transition-colors duration-200 ${
                status === id
                  ? `${ACCENT_BG} ${ACCENT_TEXT}`
                  : 'bg-bg-card text-text-muted hover:text-text-secondary'
              }`}
            >
              {id === 'all' ? null : <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[id]}`} />}
              <span>{FILTER_LABEL[id]}</span>
              <span className="font-mono opacity-70">{counts[id]}</span>
            </button>
          ))}
        </div>
      </div>

      {/* 列表区：Virtuoso 只渲染视口内卡片。装载时给骨架屏占位，有数据才展示窗口化列表。 */}
      <div className="min-h-0 flex-1">
        {error ? (
          <p className="m-3 rounded-[6px] bg-bg-subtle px-2.5 py-2 text-[12px] text-text-secondary">
            {error}
          </p>
        ) : loading ? (
          <div className="px-3 py-3 animate-pulse">
            {Array.from({ length: 6 }).map((_, i) => (
              <div
                key={i}
                className="mb-1.5 w-full rounded-[10px] border border-border-color bg-bg-card px-[11px] pb-[11px] pt-[10px]"
              >
                <div className="mb-2 h-3.5 w-2/3 rounded bg-bg-subtle" />
                <div className="mb-1.5 h-3 w-1/3 rounded bg-bg-subtle" />
                <div className="h-2.5 w-1/2 rounded bg-bg-subtle" />
              </div>
            ))}
          </div>
        ) : !visible.length ? (
          <p className="px-1 py-6 text-center text-[12px] text-text-muted">没有匹配的会话</p>
        ) : (
          <Virtuoso
            data={visible}
            initialItemCount={Math.min(visible.length, 30)}
            itemContent={(_, session) => (
              <div className="px-3">
                <SessionItem
                  session={session}
                  selected={session.session_id === selectedId}
                  copied={copiedId === session.session_id}
                  onSelect={onSelect}
                  onCopy={handleCopy}
                />
                <div className="h-1.5" />
              </div>
            )}
          />
        )}
      </div>

      <div className="shrink-0 border-t border-border-color px-3 py-2 font-mono text-[11px] text-text-muted">
        共 {sessions.length} 场 · Claude Code {familyCounts.cc} 场 · opencode{' '}
        {familyCounts.oc} 场
      </div>

      <NewSessionModal
        isOpen={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={async (sid) => {
          onSelect(sid);
          for (const delay of [1500, 3000, 6000, 12000]) {
            await new Promise((r) => setTimeout(r, delay));
            await reload();
          }
        }}
      />
    </aside>
  );
}
