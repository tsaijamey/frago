/**
 * GroupPicker — 会话卡上「放进分组」点开的那一小块。
 *
 * 三件事：挑一个现有标签把这场放进去（从原来那组搬走）、移出分组、当场新建一个标签并
 * 放进去。新建放在同一块里而不是另开一个入口：人往往是在给某一场找地方时才发现"还没有
 * 这个组"，让他先关掉、去别处建、再回来放，是白让他多走一圈。
 *
 * **挂在 body 上、按按钮的位置定位。** 左栏是窗口化的滚动列表，浮层要是长在行里，靠下
 * 那几行点开会被滚动容器的边切掉。清单一滚，按钮就不在原处了，浮层随之收起。
 */

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Check, Sparkles } from 'lucide-react';
import type { GroupTag } from '@/hooks/useSessionGroups';

const WIDTH = 224;
/** 浮层大致多高。按钮下方放不下这么高就改往上开。 */
const EST_HEIGHT = 320;

export interface GroupPickerProps {
  anchor: DOMRect;
  tags: GroupTag[];
  /** 这场眼下在哪个组里。没分组是 null。 */
  current: string | null;
  onPick: (tagId: string | null) => void;
  /** 建一个标签并把这场放进去。失败时抛，浮层留着让人改名重试。 */
  onCreate: (name: string) => Promise<void>;
  onClose: () => void;
}

export default function GroupPicker({ anchor, tags, current, onPick, onCreate, onClose }: GroupPickerProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    const onScroll = (e: Event) => {
      if (ref.current && e.target instanceof Node && ref.current.contains(e.target)) return;
      onClose();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [onClose]);

  const openUp = anchor.bottom + EST_HEIGHT > window.innerHeight && anchor.top > EST_HEIGHT;
  const left = Math.max(8, Math.min(anchor.right - WIDTH, window.innerWidth - WIDTH - 8));
  const position = openUp
    ? { left, bottom: window.innerHeight - anchor.top + 4 }
    : { left, top: anchor.bottom + 4 };

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate(trimmed);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-label={t('workbench.rail.groupPickTitle')}
      data-testid="group-picker"
      style={{ ...position, width: WIDTH }}
      className="fixed z-50 flex max-h-[320px] flex-col rounded-[8px] border border-border-color bg-[var(--bg-base)] py-1.5 shadow-lg"
      onClick={(e) => e.stopPropagation()}
    >
      <p className="px-3 pb-1 pt-0.5 text-[11px] text-text-muted">{t('workbench.rail.groupPickTitle')}</p>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tags.map((tag) => (
          <button
            key={tag.id}
            type="button"
            data-testid="group-option"
            onClick={() => onPick(tag.id)}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-text-primary transition-colors duration-200 hover:bg-bg-hover"
          >
            <span className="flex w-3 shrink-0 justify-center">
              {tag.id === current ? <Check size={12} className="text-accent-primary" /> : null}
            </span>
            <span className="min-w-0 flex-1 truncate">{tag.name}</span>
            {tag.source === 'ai' ? (
              <Sparkles size={10} className="shrink-0 text-text-dim" aria-label={t('workbench.rail.groupSourceAi')} />
            ) : null}
          </button>
        ))}
        {current ? (
          <button
            type="button"
            data-testid="group-option-none"
            onClick={() => onPick(null)}
            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] text-text-secondary transition-colors duration-200 hover:bg-bg-hover"
          >
            <span className="w-3 shrink-0" />
            {t('workbench.rail.groupNone')}
          </button>
        ) : null}
      </div>
      <div className="mt-1 border-t border-border-color px-2 pt-1.5">
        <input
          autoFocus
          value={name}
          disabled={busy}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={t('workbench.rail.groupNewPlaceholder')}
          data-testid="group-new-input"
          className="h-7 w-full rounded-[6px] bg-bg-subtle px-2 text-[12px] text-text-primary outline-none ring-1 ring-inset ring-transparent placeholder:text-text-muted focus:ring-border-strong"
        />
        {error ? <p className="px-1 pt-1 text-[11px] text-accent-error">{error}</p> : null}
      </div>
    </div>,
    document.body
  );
}
