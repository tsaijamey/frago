import { useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { CiteDefinition } from '@/components/ui/citations';

export interface CitePopoverProps {
  def: CiteDefinition;
  anchorRect: DOMRect;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onOpen: (def: CiteDefinition) => void;
}

export default function CitePopover({
  def,
  anchorRect,
  onMouseEnter,
  onMouseLeave,
  onOpen,
}: CitePopoverProps) {
  const { t } = useTranslation();
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number }>(() => ({
    left: Math.max(12, Math.min(anchorRect.left, window.innerWidth - 352)),
    top: Math.max(52, anchorRect.bottom + 8),
  }));

  useLayoutEffect(() => {
    const el = popRef.current;
    const popW = el?.offsetWidth || 340;
    const popH = el?.offsetHeight || 168;
    const margin = 12;
    const headerFloor = 52;
    const composerCeil = window.innerHeight - 92;

    const left = Math.max(margin, Math.min(anchorRect.left, window.innerWidth - popW - margin));
    let top = anchorRect.bottom + 8;
    if (top + popH > composerCeil) {
      const above = anchorRect.top - popH - 8;
      top = above >= headerFloor ? above : Math.max(headerFloor, window.innerHeight - popH - margin);
    }
    setPos({ left, top });
  }, [anchorRect, def.id]);

  const isWeb = def.kind === 'web';
  const locText = isWeb
    ? def.uri
    : `${def.filePath ?? ''}${def.line ? `:${def.line}` : ''}`;

  return (
    <div
      ref={popRef}
      className="cite-popover open"
      data-testid="cite-popover"
      style={{ left: `${pos.left}px`, top: `${pos.top}px` }}
      role="tooltip"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="cite-pop-head">
        <span className="cite-pop-num">[{def.label}]</span>
        <span className="cite-pop-title">{def.title}</span>
        <span className={`cite-pop-kind${isWeb ? ' web' : ''}`}>
          {isWeb ? t('workbench.citations.webBadge') : t('workbench.citations.localBadge')}
        </span>
      </div>
      {locText ? <div className="cite-pop-path">{locText}</div> : null}
      {def.excerpt ? <div className="cite-pop-excerpt">{def.excerpt}</div> : null}
      <div className="cite-pop-foot">
        <span>
          {isWeb
            ? t('workbench.citations.clickVerifyWeb')
            : t('workbench.citations.clickVerifyLocal')}
        </span>
        <button
          type="button"
          className="cite-pop-open"
          data-testid="cite-popover-open"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(def);
          }}
        >
          {isWeb ? t('workbench.citations.openLink') : t('workbench.citations.openPreview')}
        </button>
      </div>
    </div>
  );
}
