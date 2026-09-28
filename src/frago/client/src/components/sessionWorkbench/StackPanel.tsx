/**
 * StackPanel — 右栏下半的暂存列表。只属于当前这场会话，与 `frago todo` 无关。
 *
 * 代理一次列出好几个待决的点，人更愿意一条一条地答：一次顾的点越多，每一点得到的注意力
 * 越少。麻烦在于每答完一条，代理就接着跑，记录流里冒出一大段新内容，原来那份清单被推到
 * 很远的上面。这张列表就是把那几个点先摘下来，摆在手边，一条一条处理。
 *
 * 每一条：
 *
 * | 部位 | 做什么 |
 * |---|---|
 * | 原文 | 折到三行，可展开；点它记录流滚回原处并闪一下 |
 * | 想法 | 点开就地改；没写过的给一个「写想法」 |
 * | 「填入」 | 按引用格式填进输入框，想法接在 `>>> ` 后面 |
 * | 状态 | 没用过（琥珀）/ 已填入待发出 / 用过了（蓝、整条降一档）/ 没找到原处 |
 * | 顺序 | 拖动，或「更多」里的上移、下移；删除也在那里，直接删 |
 *
 * 颜色只有一个意思：琥珀 = 还等着你，蓝 = 回应过了。条目前面那颗小圆点与记录流里的
 * 底色、缩略滚动条上的刻度是同一个颜色，三处说的是同一件事。
 *
 * 右栏被拖得很窄时原文截断，「填入」不换行、不消失——它是这张列表存在的理由。
 */

import { useLayoutEffect, useRef, useState, type DragEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDown, ArrowUp, CornerDownLeft, GripVertical, Layers, MoreHorizontal, Trash2 } from 'lucide-react';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import { squeeze } from './SelectionQuote';

/**
 * 这一句话出门时带走了哪几条待发出的暂存。
 *
 * 点了「填入」只算待发出；真正发出去的那句话里**还带着这条原文**才算用上——填进去之后
 * 又删掉、改填了别的，那条就没用上。比对时去掉空白，人在框里调了调换行不影响。
 */
export function marksAboard(text: string, pendingIds: string[], marks: WorkbenchMark[]): string[] {
  const sent = squeeze(text);
  return pendingIds.filter((id) => {
    const mark = marks.find((m) => m.id === id);
    const needle = mark ? squeeze(mark.text) : '';
    return needle ? sent.includes(needle) : false;
  });
}

/** 某一条跳回原处的下场。searching 是正在往前翻页找。 */
export type LocateState = 'searching' | 'notFound';

export interface StackPanelProps {
  /** 全部标注（引用也在里面）；这里只摆暂存那几条，顺序照数组。 */
  marks: WorkbenchMark[];
  /** 已经填进输入框、等着发出的那几条。 */
  pendingIds?: string[];
  /** 跳回原处的下场，按标注编号。 */
  locate?: Record<string, LocateState>;
  onFill: (mark: WorkbenchMark) => void;
  onLocate: (mark: WorkbenchMark) => void;
  onDelete: (id: string) => void;
  /** 把这一条挪到整份数组里的 `to` 位置。 */
  onMove: (id: string, to: number) => void;
  onNoteChange: (id: string, note: string) => void;
}

/** 列表里那一种小字按钮：悬停只换字色，不换底——这一栏的底是纸色，一换就花。 */
const SMALL_ACTION = 'shrink-0 text-[11px] text-text-muted hover:text-text-primary';

function StackItem({
  mark,
  index,
  count,
  pending,
  locate,
  onFill,
  onLocate,
  onDelete,
  onMoveTo,
  onNoteChange,
  dragging,
  onDragStart,
  onDragEnd,
  onDropHere,
}: {
  mark: WorkbenchMark;
  index: number;
  count: number;
  pending: boolean;
  locate: LocateState | undefined;
  onFill: () => void;
  onLocate: () => void;
  onDelete: () => void;
  /** 挪到暂存列表里的第几位。 */
  onMoveTo: (stackIndex: number) => void;
  onNoteChange: (note: string) => void;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDropHere: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(mark.note);
  const [menuOpen, setMenuOpen] = useState(false);
  const [dropTarget, setDropTarget] = useState(false);
  const body = useRef<HTMLButtonElement>(null);
  // Esc 放弃之后输入框随即卸掉，有的浏览器会在那一刻补发一次失焦——不许它把草稿存进去。
  const discarded = useRef(false);

  // 装不下三行才给「展开」。右栏被拖宽拖窄、原文换了，都要重新量。
  useLayoutEffect(() => {
    const el = body.current;
    if (!el || expanded) return undefined;
    const measure = () => setOverflows(el.scrollHeight > el.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [mark.text, expanded]);

  const saveNote = () => {
    if (discarded.current) {
      discarded.current = false;
      return;
    }
    setEditing(false);
    if (draft.trim() !== mark.note) onNoteChange(draft.trim());
  };

  const allowDrop = (e: DragEvent) => {
    if (!dragging) {
      e.preventDefault();
      setDropTarget(true);
    }
  };

  return (
    <li
      data-testid="stack-item"
      data-used={mark.used ? 'true' : undefined}
      data-pending={pending ? 'true' : undefined}
      onDragOver={allowDrop}
      onDragLeave={() => setDropTarget(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDropTarget(false);
        onDropHere();
      }}
      /* 拖到这一条上时，整条铺一层中性底说「会落在这里」。不画单边的线——那是选中态的
         老写法，这里也没有选中这回事。 */
      className={`group relative flex min-w-0 gap-1.5 rounded-[8px] py-2 pl-1 pr-3 transition-colors ${
        dropTarget ? 'bg-bg-subtle' : ''
      } ${dragging ? 'opacity-40' : ''}`}
    >
      <span
        draggable
        onDragStart={(e) => {
          e.dataTransfer?.setData('text/plain', mark.id);
          onDragStart();
        }}
        onDragEnd={onDragEnd}
        title={t('workbench.stack.drag')}
        aria-hidden
        className="mt-[3px] shrink-0 cursor-grab text-text-muted opacity-0 transition-opacity group-hover:opacity-100"
      >
        <GripVertical size={12} />
      </span>
      {/* 琥珀 = 还等着你，蓝 = 回应过了。与记录流底色、缩略滚动条刻度同色。 */}
      <span
        aria-hidden
        className={`mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full ${
          mark.used ? 'bg-accent-info' : 'bg-accent-warning'
        }`}
      />
      <div className={`flex min-w-0 flex-1 flex-col gap-1 ${mark.used ? 'opacity-60' : ''}`}>
        <div className="flex min-w-0 items-start gap-2">
          <button
            ref={body}
            type="button"
            data-testid="stack-item-text"
            onClick={onLocate}
            title={t('workbench.stack.locate')}
            className={`min-w-0 flex-1 whitespace-pre-wrap break-words text-left text-[12px] leading-[1.6] text-text-primary hover:text-accent-primary ${
              expanded ? '' : 'line-clamp-3'
            }`}
          >
            {mark.text}
          </button>
          <button
            type="button"
            data-testid="stack-item-fill"
            onClick={onFill}
            title={t('workbench.stack.fillHint')}
            className="flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-[6px] border border-border-color px-2 text-[11px] text-text-secondary transition-colors hover:border-border-accent hover:text-accent-primary"
          >
            <CornerDownLeft size={11} />
            {t('workbench.stack.fill')}
          </button>
        </div>

        {editing ? (
          <textarea
            autoFocus
            data-testid="stack-item-note-input"
            value={draft}
            rows={2}
            placeholder={t('workbench.stack.notePlaceholder')}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={saveNote}
            onKeyDown={(e) => {
              // 回车存，Shift+回车换行；Esc 放弃这次改动。
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                saveNote();
              } else if (e.key === 'Escape') {
                e.preventDefault();
                discarded.current = true;
                setDraft(mark.note);
                setEditing(false);
              }
            }}
            className="w-full resize-none rounded-[6px] border border-border-color bg-bg-card px-2 py-1 text-[12px] leading-[1.6] text-text-primary outline-none placeholder:text-text-muted focus:border-text-muted"
          />
        ) : mark.note ? (
          <button
            type="button"
            data-testid="stack-item-note"
            onClick={() => {
              discarded.current = false;
              setDraft(mark.note);
              setEditing(true);
            }}
            className="min-w-0 whitespace-pre-wrap break-words text-left text-[12px] leading-[1.6] text-text-secondary hover:text-text-primary"
          >
            <span className="mr-1 font-mono text-text-muted">&gt;&gt;&gt;</span>
            {mark.note}
          </button>
        ) : null}

        <div className="flex min-w-0 items-center gap-2">
          {mark.used ? (
            <span data-testid="stack-item-used" className="shrink-0 text-[11px] text-accent-info">
              {t('workbench.stack.used')}
            </span>
          ) : null}
          {pending ? (
            <span className="min-w-0 truncate text-[11px] text-text-muted">
              {t('workbench.stack.pending')}
            </span>
          ) : null}
          {locate === 'searching' ? (
            <span className="min-w-0 truncate text-[11px] text-text-muted">
              {t('workbench.stack.searching')}
            </span>
          ) : null}
          {locate === 'notFound' ? (
            <span data-testid="stack-item-not-found" className="min-w-0 truncate text-[11px] text-accent-error">
              {t('workbench.stack.notFound')}
            </span>
          ) : null}
          {!mark.note && !editing ? (
            <button
              type="button"
              data-testid="stack-item-add-note"
              onClick={() => {
                discarded.current = false;
                setDraft('');
                setEditing(true);
              }}
              className={SMALL_ACTION}
            >
              {t('workbench.stack.addNote')}
            </button>
          ) : null}
          {overflows || expanded ? (
            <button type="button" onClick={() => setExpanded((v) => !v)} className={SMALL_ACTION}>
              {expanded ? t('workbench.stack.collapse') : t('workbench.stack.expand')}
            </button>
          ) : null}
          <span className="flex-1" />
          <div className="relative shrink-0">
            <button
              type="button"
              data-testid="stack-item-more"
              aria-label={t('workbench.stack.more')}
              title={t('workbench.stack.more')}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
              className="flex h-5 w-5 items-center justify-center rounded-[4px] text-text-muted hover:text-text-primary"
            >
              <MoreHorizontal size={13} />
            </button>
            {menuOpen ? (
              <div
                role="menu"
                onMouseLeave={() => setMenuOpen(false)}
                className="absolute right-0 top-full z-20 mt-1 flex min-w-[112px] flex-col rounded-[8px] border border-border-color bg-bg-card py-1 shadow-lg"
              >
                <MenuItem
                  testId="stack-item-up"
                  icon={<ArrowUp size={12} />}
                  label={t('workbench.stack.moveUp')}
                  disabled={index === 0}
                  onClick={() => {
                    setMenuOpen(false);
                    onMoveTo(index - 1);
                  }}
                />
                <MenuItem
                  testId="stack-item-down"
                  icon={<ArrowDown size={12} />}
                  label={t('workbench.stack.moveDown')}
                  disabled={index === count - 1}
                  onClick={() => {
                    setMenuOpen(false);
                    onMoveTo(index + 1);
                  }}
                />
                <MenuItem
                  testId="stack-item-delete"
                  icon={<Trash2 size={12} />}
                  label={t('workbench.stack.delete')}
                  onClick={() => {
                    setMenuOpen(false);
                    onDelete();
                  }}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </li>
  );
}

function MenuItem({
  testId,
  icon,
  label,
  disabled = false,
  onClick,
}: {
  testId: string;
  icon: ReactNode;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      className="flex items-center gap-2 px-3 py-1 text-left text-[12px] text-text-secondary hover:bg-bg-hover hover:text-text-primary disabled:opacity-40 disabled:hover:bg-transparent"
    >
      {icon}
      {label}
    </button>
  );
}

export default function StackPanel({
  marks,
  pendingIds = [],
  locate = {},
  onFill,
  onLocate,
  onDelete,
  onMove,
  onNoteChange,
}: StackPanelProps) {
  const { t } = useTranslation();
  const stacks = marks.filter((m) => m.kind === 'stack');
  const [draggingId, setDraggingId] = useState<string | null>(null);

  /**
   * 暂存列表里的第几位换算成整份数组里的位置。引用也在那份数组里（不进列表），挪的时候
   * 落在目标那一条原来的位置上：往下挪落在它后面，往上挪落在它前面。
   */
  const moveTo = (id: string, stackIndex: number) => {
    const target = stacks[Math.min(Math.max(0, stackIndex), stacks.length - 1)];
    if (!target || target.id === id) return;
    onMove(id, marks.indexOf(target));
  };

  return (
    <section data-testid="stack-panel" className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-1.5 px-3 pb-1 pt-2.5">
        <Layers size={12} className="shrink-0 text-text-muted" />
        <span className="text-[11px] font-medium tracking-wide text-text-muted">
          {t('workbench.stack.title')}
        </span>
        {stacks.length ? (
          <span className="font-mono text-[11px] text-text-muted opacity-70">
            {t('workbench.stack.count', { n: stacks.length })}
          </span>
        ) : null}
      </header>
      {stacks.length === 0 ? (
        <p data-testid="stack-empty" className="px-3 pb-3 text-[12px] leading-[1.6] text-text-muted">
          {t('workbench.stack.empty')}
        </p>
      ) : (
        // 条与条之间用虚线：与摘要里「已经发生的事」同一种写法，是同一格里的条目。
        <ul className="min-h-0 flex-1 divide-y divide-dashed divide-border-color overflow-y-auto pb-4 pl-2">
          {stacks.map((mark, index) => (
            <StackItem
              key={mark.id}
              mark={mark}
              index={index}
              count={stacks.length}
              pending={pendingIds.includes(mark.id)}
              locate={locate[mark.id]}
              onFill={() => onFill(mark)}
              onLocate={() => onLocate(mark)}
              onDelete={() => onDelete(mark.id)}
              onMoveTo={(to) => moveTo(mark.id, to)}
              onNoteChange={(note) => onNoteChange(mark.id, note)}
              dragging={draggingId === mark.id}
              onDragStart={() => setDraggingId(mark.id)}
              onDragEnd={() => setDraggingId(null)}
              onDropHere={() => {
                if (draggingId) moveTo(draggingId, index);
                setDraggingId(null);
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
