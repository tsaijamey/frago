/**
 * SessionRail — 左栏：新建会话、搜索、时间范围、状态筛选、会话清单、底部汇总。
 *
 * 三家（Claude Code / opencode / codex）的会话在核心数据层就合并排好了，这里不重排。
 *
 * **筛选是两个维度，不是一个。** 状态答「现在什么情况」，时间范围答「哪一段时间的」，
 * 两者并存、互不替代。按来源筛的那一维不在这里——一千多场 Claude Code 会话摆在一起，
 * 知道它们都来自 Claude Code 没有任何用；来源仍在每张卡上看得见，改由底部汇总报两家各几场。
 *
 * **搜索有两条腿。** 标题、目录、编号在本地即时筛，敲一个字就有反应；会话内容（提示词
 * 与 agent 回复正文）由服务端搜，慢一拍，所以它自己报进度、自己报哪里没搜全。两条的
 * 结果取并集，命中的那几场把命中的原话摆到卡片上。
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
 *
 * **置顶区是一片自己说了算的地方。** 名单存在服务端（见 `useSessionPins`），次序照置顶
 * 的次序而不是活动时刻，数量不设上限，整片可以折起来。它**不跟状态与时间范围走**——那
 * 两道答的是「翻哪一段、翻哪一档」，而置顶答的是「这几场我随时要回来」，点一下「7 天」
 * 就让人挑出来的那几场消失，是把筛选的语义套到了一个不该被筛的地方。搜索另说：那一刻人
 * 是在找某一场，置顶区跟着筛才不会答非所问。
 *
 * 一场都没置顶时不长分区标题，整片仍是从前那个单列清单——空着的分区标题只是噪音。
 *
 * **分区标题是列表里的普通一行，不是窗口化列表的 group header。** group header 的位置要
 * 等列表量完每一行的高度才算得出来，量完之前那两行标题一个都不在页面上——真实浏览器里
 * 撞见过整片清单已经摆好、标题还没出现。标题上坐着折叠开关，它不该等任何东西。
 */

import { useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { ChevronDown, ChevronRight, Loader2, Pin, Plus, RefreshCw, Search, X } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import SessionItem, { resumeCommand } from './SessionItem';
import NewSessionModal from './NewSessionModal';
import { useSessionPins } from '@/hooks/useSessionPins';
import { waitForSession } from '@/hooks/useAgentClients';
import {
  DAY_OPTIONS,
  MIN_CONTENT_QUERY,
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

/** 列表里的一行：要么是分区标题，要么是一张会话卡。 */
type RailRow =
  | { kind: 'pinned-header' }
  | { kind: 'rest-header' }
  | { kind: 'session'; session: WorkbenchSession };

export interface SessionRailProps {
  state: WorkbenchSessionsState;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function SessionRail({ state, selectedId, onSelect }: SessionRailProps) {
  const {
    sessions,
    visible,
    searched,
    counts,
    loading,
    error,
    search,
    setSearch,
    status,
    setStatus,
    days,
    setDays,
    content,
    reload,
  } = state;
  const showToast = useAppStore((s) => s.showToast);
  const pins = useSessionPins();
  const [newOpen, setNewOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const familyCounts = useMemo(() => {
    let cc = 0;
    let oc = 0;
    let cx = 0;
    for (const s of sessions) {
      if (s.family === 'claude-code') cc += 1;
      else if (s.family === 'opencode') oc += 1;
      else if (s.family === 'codex') cx += 1;
    }
    return { cc, oc, cx };
  }, [sessions]);

  /**
   * 置顶区摆哪几场。
   *
   * 次序照置顶的次序，不按最后活动时刻重排——那一区的意义正是"我说了算"，跟着活动时刻
   * 重排等于把人刚摆好的次序打乱。名单里有编号、清单里却没有那场（档案被删或被滚删）时
   * 就是不显示，NEVER 因此把编号从名单里踢掉：一次滚删不该悄悄清空人的置顶。
   */
  const pinnedRows = useMemo(() => {
    if (!pins.pinned.length) return [];
    const rank = new Map(pins.pinned.map((id, i) => [id, i]));
    return searched
      .filter((s) => rank.has(s.session_id))
      .sort((a, b) => rank.get(a.session_id)! - rank.get(b.session_id)!);
  }, [searched, pins.pinned]);

  /** 置顶的那几场不在下面再出现一次。同一场摆两处，人会以为是两场。 */
  const restRows = useMemo(
    () => (pins.pinned.length ? visible.filter((s) => !pins.isPinned(s.session_id)) : visible),
    [visible, pins]
  );

  /**
   * 摆进列表的每一行：分区标题与会话卡走同一条队。
   *
   * 分区标题做成**普通一行**而不是窗口化列表的 group header：group header 的位置要等
   * 列表量完每一行的高度才算得出来，量完之前那两行标题一个都不在页面上——真实浏览器里
   * 就撞见过整片清单已经摆好、标题还没出现。标题是折叠开关所在，它不该等任何东西。
   *
   * 一场都没置顶时连标题都不长，整片就是从前那个单列清单——空着的分区标题只是噪音。
   */
  const rows = useMemo<RailRow[]>(() => {
    if (!pins.pinned.length) return restRows.map((session) => ({ kind: 'session' as const, session }));
    return [
      { kind: 'pinned-header' as const },
      ...(pins.collapsed
        ? []
        : pinnedRows.map((session) => ({ kind: 'session' as const, session }))),
      { kind: 'rest-header' as const },
      ...restRows.map((session) => ({ kind: 'session' as const, session })),
    ];
  }, [pins.pinned.length, pins.collapsed, pinnedRows, restRows]);

  const handleTogglePin = async (session: WorkbenchSession) => {
    const wasPinned = pins.isPinned(session.session_id);
    try {
      await pins.toggle(session.session_id);
      // 折起来的时候置顶一场，那一场会立刻消失在眼前。说一句它去哪了。
      if (!wasPinned && pins.collapsed) showToast('已置顶，在折起来的置顶区里', 'success');
    } catch (e) {
      showToast(e instanceof Error ? e.message : '置顶没存下', 'error');
    }
  };

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
              placeholder="搜标题、目录，或会话里说过的话"
              aria-label="搜会话"
              className="w-full min-w-0 bg-transparent text-[12px] text-text-primary outline-none placeholder:text-text-muted"
            />
            {content.searching ? (
              <Loader2 size={12} className="shrink-0 animate-spin text-text-muted" />
            ) : null}
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

        {/* 内容检索比敲字慢一拍，所以它自己报进度。没搜到就明说没搜到，NEVER 让人
            对着一份只按标题筛出来的清单以为"内容里也没有"。 */}
        {search.trim().length >= MIN_CONTENT_QUERY ? (
          <p data-testid="content-search-status" className="text-[11px] text-text-muted">
            {content.error
              ? content.error
              : content.searching
                ? '正在会话内容里找…'
                : `会话内容里命中 ${content.matches.size} 场`}
          </p>
        ) : null}
        {content.warnings.map((warning) => (
          <p key={warning} className="text-[11px] text-text-secondary">
            {warning}
          </p>
        ))}
      </div>

      {/* 列表区：Virtuoso 只渲染视口内卡片。装载时给骨架屏占位，有数据才展示窗口化列表。 */}
      <div className="min-h-0 flex-1">
        {/* 报错摆在清单**上面**而不是替掉清单：定时重取偶尔失手时，手上那份清单仍
            比一句错误有用得多。 */}
        {error && (
          <p className="m-3 rounded-[6px] bg-bg-subtle px-2.5 py-2 text-[12px] text-text-secondary">
            {error}
          </p>
        )}
        {loading && !visible.length ? (
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
        ) : !rows.length ? (
          <p className="px-1 py-6 text-center text-[12px] text-text-muted">没有匹配的会话</p>
        ) : (
          /* 置顶区与其余那一片共用同一条队、同一条滚动条。两个列表并排摆的话，置顶那一片
             要么自己不窗口化（置顶数不设上限，迟早卡），要么各滚各的（两条滚动条挨着，
             没人分得清该滚哪条）。 */
          <Virtuoso
            data={rows}
            initialItemCount={Math.min(rows.length, 30)}
            computeItemKey={(_, row) =>
              row.kind === 'session' ? row.session.session_id : row.kind
            }
            itemContent={(_, row) => {
              if (row.kind === 'pinned-header') {
                return (
                  <button
                    type="button"
                    onClick={() => pins.setCollapsed(!pins.collapsed)}
                    aria-expanded={!pins.collapsed}
                    data-testid="pinned-header"
                    className="flex w-full items-center gap-1.5 px-3 pb-1.5 pt-1 text-[11px] text-text-muted transition-colors duration-200 hover:text-text-secondary"
                  >
                    {pins.collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
                    <Pin size={11} fill="currentColor" className={ACCENT_TEXT} />
                    <span className={ACCENT_TEXT}>置顶</span>
                    {/* 折起来时这个数就是全部线索：不报的话，人看不出自己折掉了什么。 */}
                    <span className="font-mono opacity-70">{pinnedRows.length}</span>
                  </button>
                );
              }
              if (row.kind === 'rest-header') {
                return (
                  <div
                    data-testid="rest-header"
                    className="px-3 pb-1.5 pt-2 text-[11px] text-text-muted"
                  >
                    其余 <span className="font-mono opacity-70">{restRows.length}</span>
                  </div>
                );
              }
              const session = row.session;
              return (
                <div className="px-3">
                  <SessionItem
                    session={session}
                    selected={session.session_id === selectedId}
                    copied={copiedId === session.session_id}
                    pinned={pins.isPinned(session.session_id)}
                    contentMatch={content.matches.get(session.session_id) ?? null}
                    onSelect={onSelect}
                    onCopy={handleCopy}
                    onTogglePin={handleTogglePin}
                  />
                  <div className="h-1.5" />
                </div>
              );
            }}
          />
        )}
      </div>

      <div className="shrink-0 border-t border-border-color px-3 py-2 font-mono text-[11px] text-text-muted">
        共 {sessions.length} 场 · Claude Code {familyCounts.cc} 场 · opencode{' '}
        {familyCounts.oc} 场 · codex {familyCounts.cx} 场
      </div>

      {/* 建完之后跳进那一场，并在随后的十几秒里反复重取清单——新会话的档案是 agent
          自己写的，写完才扫得到，一次重取多半扫了个空。

          编号不是当场就有的那两家（codex / opencode）先等它报编号：那段空窗如实说一句
          "正在起"，NEVER 静默地什么都不发生——人点了创建、界面纹丝不动，只会再点一次，
          于是起了两场。 */}
      <NewSessionModal
        isOpen={newOpen}
        onClose={() => setNewOpen(false)}
        onCreated={async (launch) => {
          let sid = launch.session_id;
          if (!sid) {
            showToast(`正在起 ${launch.display_name}，等它报出会话编号…`, 'info');
            try {
              sid = await waitForSession(launch.handle);
            } catch (e) {
              showToast(e instanceof Error ? e.message : '这一场没起来', 'error');
              return;
            }
          }
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
