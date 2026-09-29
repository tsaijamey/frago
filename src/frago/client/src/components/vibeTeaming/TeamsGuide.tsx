/**
 * 页头下的三步说明。第一次进来展开，点 × 收起并记住，页头的「?」可以再打开。
 *
 * 左格底色同左栏、右格同右栏：第几步落在哪一栏，一眼对得上。说法是对等的——两边
 * 各有自己的 agent、各有自己给队友定的规矩，两边都能请对方的 agent 做事。
 *
 * 独立成文件：它只在第一次出现，与两栏没有数据往来。
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { X } from 'lucide-react';

const SEEN_KEY = 'teams-guide-seen';

function seen(): boolean {
  try {
    return window.localStorage.getItem(SEEN_KEY) === '1';
  } catch {
    // 浏览器不给读（隐私窗口、禁用了存储）就当没看过：每次展开，× 仍能收起这一次。
    return false;
  }
}

/** 说明开着没有；收起时记住。 */
export function useTeamsGuide(): [boolean, () => void] {
  const [open, setOpen] = useState(() => !seen());
  const toggle = useCallback(() => {
    setOpen((was) => {
      if (was) {
        try {
          window.localStorage.setItem(SEEN_KEY, '1');
        } catch {
          // 记不住就记不住，这一次照样收起。
        }
      }
      return !was;
    });
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
