/**
 * SessionSearchPalette — 全站的 ⌘K 搜会话浮窗。
 *
 * **搜的是 `frago session search` 那一条。** 一句话先由模型摊成关键词，再翻遍本机会话
 * 备份，按命中的不同关键词数排序。终端里搜到过的那一场，换到网页上必须还搜得到。
 *
 * **结果只摆在浮窗里，不去筛左栏。** 左栏答的是「现在什么情况」，搜索答的是「我记得
 * 说过的那一场在哪」；两件事挤在同一张清单上，筛完的清单既不是全部、也不像搜索结果。
 *
 * **回车才搜。** 一趟里模型扩展要十几秒，边敲边搜每个字都烧一次模型。输入框里的字与
 * 上一趟搜的那句相同时，回车改为打开高亮的那一场——同一个键，永远只做眼下唯一合理的事，
 * 底栏的提示跟着变。
 *
 * **点窗外就关，这里是站内浮窗「点遮罩不关」那条规矩的例外。** 那条规矩防的是人填到
 * 一半的东西说没就没；这里关窗不丢任何东西——那句话和那批结果都留着，再按一次 ⌘K
 * 原样回来。人搜完常常要挨个点开几场对照，每次都重搜一趟十几秒，才是真的丢东西。
 *
 * 颜色一律走 CSS 变量；表面照三级：遮罩用 `--bg-overlay`，浮窗本身是浮层 `bg-elevated`。
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { CornerDownLeft, Loader2, Search } from 'lucide-react';
import { usePageStore, useUIStore } from '@/stores/appStore';
import { useSessionSearch, type SessionSearchHit } from '@/hooks/useSessionSearch';
import { useWorkbenchLabels } from '@/hooks/useWorkbenchSessions';
import { relativeTime } from './SessionItem';

/** 备份里的来源名 → 工作台的家族名。两处叫法不同，卡片上摆的是工作台那套。 */
const FAMILY_OF_SOURCE: Record<string, string> = { claude: 'claude-code', opencode: 'opencode' };

/** 摘要里把命中的那个词挑出来。大小写不敏感，与检索时的判据一致。 */
function highlight(text: string, term: string): ReactNode {
  const at = text.toLowerCase().indexOf(term.toLowerCase());
  if (!term || at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-[3px] bg-accent-primary-10 px-0.5 text-text-primary">
        {text.slice(at, at + term.length)}
      </mark>
      {text.slice(at + term.length)}
    </>
  );
}

function HitRow({
  hit,
  total,
  active,
  onPick,
  onHover,
  rowRef,
}: {
  hit: SessionSearchHit;
  total: number;
  active: boolean;
  onPick: () => void;
  onHover: () => void;
  rowRef: (el: HTMLButtonElement | null) => void;
}) {
  const { t } = useTranslation();
  const { familyLabel } = useWorkbenchLabels();
  const snippet = hit.snippets[0];
  return (
    <button
      ref={rowRef}
      type="button"
      role="option"
      aria-selected={active}
      data-testid="session-search-hit"
      onClick={onPick}
      onMouseMove={onHover}
      className={`block w-full rounded-[8px] px-3 py-2 text-left transition-colors duration-200 ${
        active ? 'bg-bg-active' : ''
      }`}
    >
      <div className="flex items-baseline gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text-primary">
          {hit.title || hit.session_id}
        </span>
        <span className="shrink-0 text-[11px] text-text-muted">
          {relativeTime(hit.last_activity * 1000)}
        </span>
      </div>
      <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-text-muted">
        <span className="shrink-0">{familyLabel(FAMILY_OF_SOURCE[hit.source] ?? hit.source)}</span>
        {hit.cwd ? (
          <>
            <span className="shrink-0">·</span>
            <span className="min-w-0 truncate font-mono">{hit.cwd}</span>
          </>
        ) : null}
        <span className="shrink-0">·</span>
        <span className="shrink-0">
          {t('sessionSearch.matched', { n: hit.matched_terms.length, total })}
        </span>
        {hit.degraded ? (
          <>
            <span className="shrink-0">·</span>
            <span className="shrink-0">{t('sessionSearch.degraded')}</span>
          </>
        ) : null}
      </div>
      {snippet ? (
        <p className="mt-1 line-clamp-2 break-all text-[12px] leading-[1.5] text-text-secondary">
          {highlight(snippet.text, snippet.term)}
        </p>
      ) : null}
    </button>
  );
}

function Key({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[4px] border border-border-color px-1 font-mono text-[10px] text-text-muted">
      {children}
    </kbd>
  );
}

export default function SessionSearchPalette() {
  const { t } = useTranslation();
  const open = useUIStore((s) => s.sessionSearchOpen);
  const setOpen = useUIStore((s) => s.setSessionSearchOpen);
  const currentPage = usePageStore((s) => s.currentPage);
  const switchPage = usePageStore((s) => s.switchPage);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);
  const search = useSessionSearch();
  const [text, setText] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  /**
   * ⌘K（别的平台是 Ctrl+K）在哪一页都能开，再按一次就关。
   *
   * 焦点在输入框里也照样认：人正在别处打字时想起要找一场会话，是这个快捷键最常见的时刻。
   */
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(!useUIStore.getState().sessionSearchOpen);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setOpen]);

  /** 一开就能打字；上次那句全选着，直接敲就是换一句，按回车就是接着看上次那批。 */
  useEffect(() => {
    if (open) inputRef.current?.select();
  }, [open]);

  const hits = useMemo(() => search.result?.hits ?? [], [search.result]);
  useEffect(() => setActive(0), [search.result]);
  useEffect(() => {
    rowRefs.current[active]?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  /** 输入框里的字就是上一趟搜的那句：回车打开高亮那场，否则回车去搜。 */
  const fresh = !search.searching && text.trim() === search.query && hits.length > 0;

  const pick = (hit: SessionSearchHit) => {
    setWorkbenchSessionId(hit.session_id);
    if (currentPage !== 'session_workbench') switchPage('session_workbench');
    setOpen(false);
  };

  /**
   * 浮窗开着时，Esc、上下键、回车在整个页面上都认，不看焦点在哪。
   *
   * 焦点并不总在浮窗里：点一下结果区的空白或关键词那几行，焦点就落回页面本身。按键若只挂
   * 在浮窗上，那一刻 Esc 关不掉、上下键也选不动，人只会以为浮窗卡住了。站内通用浮窗的 Esc
   * 也是挂在整个页面上的（见 `Modal`）。
   *
   * 焦点在某条结果上按回车时交给那颗按钮自己：它本来就会打开那一场，这里再打开一次是重复。
   */
  const onKeyDown = (e: globalThis.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.target as HTMLElement | null)?.getAttribute?.('role') === 'option') {
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
    } else if (e.key === 'ArrowDown' && hits.length) {
      e.preventDefault();
      setActive((i) => (i + 1) % hits.length);
    } else if (e.key === 'ArrowUp' && hits.length) {
      e.preventDefault();
      setActive((i) => (i - 1 + hits.length) % hits.length);
    } else if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      if (fresh) pick(hits[active]);
      else search.run(text);
    }
  };
  const keyHandler = useRef(onKeyDown);
  keyHandler.current = onKeyDown;
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => keyHandler.current(e);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  if (!open) return null;

  const result = search.result;
  const total = result?.plan.terms.length ?? 0;
  let body: ReactNode;
  if (search.searching) {
    body = (
      <p className="flex items-center gap-2 px-3 py-6 text-[12px] text-text-muted">
        <Loader2 size={14} className="shrink-0 animate-spin" />
        {t('sessionSearch.searching', { query: search.query })}
      </p>
    );
  } else if (search.error) {
    body = <p className="px-3 py-6 text-[12px] text-accent-error">{search.error}</p>;
  } else if (!result) {
    body = <p className="px-3 py-6 text-[12px] leading-[1.6] text-text-muted">{t('sessionSearch.hint')}</p>;
  } else {
    body = (
      <>
        <div className="space-y-1 px-3 pb-2 pt-1 text-[11px] leading-[1.6] text-text-muted">
          <p>
            <span>{t('sessionSearch.terms')} </span>
            <span className="text-text-secondary">{result.plan.terms.join(' · ')}</span>
          </p>
          <p>
            {t('sessionSearch.summary', {
              n: hits.length,
              scanned: result.scanned_sessions,
              seconds: (result.duration_ms / 1000).toFixed(1),
            })}
          </p>
          {/* 扩展失败退回原句切词时，那句说明就是这批结果为什么不太对的原因。 */}
          {result.plan.source === 'literal' ? <p>{result.plan.note}</p> : null}
          {result.warnings.map((w) => (
            <p key={w} className="text-text-secondary">
              {w}
            </p>
          ))}
        </div>
        {hits.length ? (
          <div role="listbox" aria-label={t('sessionSearch.label')} className="space-y-0.5 pb-1">
            {hits.map((hit, i) => (
              <HitRow
                key={`${hit.source}:${hit.session_id}`}
                hit={hit}
                total={total}
                active={i === active}
                onPick={() => pick(hit)}
                onHover={() => setActive(i)}
                rowRef={(el) => {
                  rowRefs.current[i] = el;
                }}
              />
            ))}
          </div>
        ) : (
          <p className="px-3 py-6 text-[12px] text-text-muted">{t('sessionSearch.empty')}</p>
        )}
      </>
    );
  }

  return createPortal(
    <div
      data-testid="session-search-palette"
      className="fixed inset-0 z-[1100] flex items-start justify-center bg-[var(--bg-overlay)] px-4 pt-[12vh] phone:pt-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) setOpen(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('sessionSearch.label')}
        className="flex max-h-[72vh] w-full max-w-[640px] flex-col overflow-hidden rounded-[12px] border border-border-color bg-bg-elevated shadow-[var(--shadow-lg)]"
      >
        <div className="flex h-12 shrink-0 items-center gap-2.5 border-b border-border-color px-4">
          <Search size={16} strokeWidth={1.5} className="shrink-0 text-text-muted" />
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t('sessionSearch.placeholder')}
            aria-label={t('sessionSearch.label')}
            data-testid="session-search-input"
            className="min-w-0 flex-1 bg-transparent text-[14px] text-text-primary outline-none placeholder:text-text-muted"
          />
          <Key>Esc</Key>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-1.5">{body}</div>

        <div className="flex h-9 shrink-0 items-center gap-4 border-t border-border-color px-4 text-[11px] text-text-muted phone:hidden">
          {hits.length ? (
            <span className="flex items-center gap-1.5">
              <Key>↑</Key>
              <Key>↓</Key>
              {t('sessionSearch.navigate')}
            </span>
          ) : null}
          <span className="flex items-center gap-1.5">
            <Key>
              <CornerDownLeft size={10} />
            </Key>
            {fresh ? t('sessionSearch.open') : t('sessionSearch.search')}
          </span>
          <span className="flex items-center gap-1.5">
            <Key>Esc</Key>
            {t('sessionSearch.close')}
          </span>
        </div>
      </div>
    </div>,
    document.body
  );
}
