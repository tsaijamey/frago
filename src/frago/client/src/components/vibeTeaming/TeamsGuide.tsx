/**
 * 页头下的三步说明。默认收起不常驻占位，点击页头的「?」按需展开，点 × 或再次点击「?」收起。
 *
 * 左格底色同左栏、右格同右栏：第几步落在哪一栏，一眼对得上。说法是对等的——两边
 * 各有自己的 agent、各有自己给队友定的规矩，两边都能请对方的 agent 做事。
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

/** 说明默认收起，点击页头「?」按需展开/收起。 */
export function useTeamsGuide(): [boolean, () => void] {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => {
    setOpen((was) => !was);
  }, []);
  return [open, toggle];
}

function Step({
  n,
  who,
  title,
  body,
}: {
  n: number;
  who: 'me' | 'peer';
  title: string;
  body: string;
}) {
  return (
    <div className="grid min-w-0 grid-cols-[18px_minmax(0,1fr)] content-start gap-x-2">
      <span
        className={`mt-px flex h-[18px] w-[18px] items-center justify-center rounded-full text-[11px] font-semibold ${
          who === 'me'
            ? 'bg-text-primary text-bg-primary'
            : 'bg-[var(--peer-chip)] text-[var(--peer-ink)]'
        }`}
      >
        {n}
      </span>
      <span className="text-[12px] font-semibold leading-[1.5]">{title}</span>
      <span className="col-start-2 text-[12px] leading-[1.5] text-text-secondary">{body}</span>
    </div>
  );
}

export default function TeamsGuide({ onHide }: { onHide: () => void }) {
  const { t } = useTranslation();
  return (
    <div
      data-testid="teams-guide"
      className="grid shrink-0 grid-cols-2 border-b border-border-color"
    >
      <div className="min-w-0 px-[14px] pb-3 pt-2.5">
        <p className="mb-1.5 flex h-[18px] items-center text-[11px] font-medium uppercase tracking-wide text-text-muted">
          {t('team.guide.title')}
        </p>
        <Step n={1} who="me" title={t('team.guide.s1Title')} body={t('team.guide.s1Body')} />
      </div>
      <div className="relative grid min-w-0 grid-cols-2 gap-3.5 border-l border-border-color bg-[var(--peer-bg)] px-[14px] pb-3 pt-[34px]">
        <Step n={2} who="peer" title={t('team.guide.s2Title')} body={t('team.guide.s2Body')} />
        <Step n={3} who="peer" title={t('team.guide.s3Title')} body={t('team.guide.s3Body')} />
        <button
          type="button"
          onClick={onHide}
          title={t('team.guide.hide')}
          aria-label={t('team.guide.hide')}
          className="absolute right-2 top-1.5 flex h-[22px] w-[22px] items-center justify-center rounded-md text-text-muted hover:bg-bg-hover hover:text-text-primary"
        >
          <X size={13} />
        </button>
      </div>
    </div>
  );
}
