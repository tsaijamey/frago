/**
 * 右下输入框上方：对方 agent 怎么对待我发过去的请求。
 *
 * **只读。** 这份处理方式是对方主人给他自己的 agent 定的，这里只展示、不给点改；按我
 * 正在写的那句请求点亮三格之一，发送键左边一句话说依据。
 *
 * 来源分两种，NEVER 混说：对方的设置经中继传过来了，标「Set by your teammate」；还没
 * 传过来（对方或中继是旧版），格子里是 frago 的缺省规矩，标「frago's rules」，悬停说清
 * 这不是对方设的——对方设不了、或者我们看不到的时候写「对方设的」，是假话。
 */

import { Trans, useTranslation } from 'react-i18next';
import { Lock } from 'lucide-react';
import {
  predictionKey,
  verdictOf,
  type RequestRules,
  type Tier,
  type TierGuess,
} from './teamRequest';

export type RulesSource = 'frago' | 'teammate';

const CELLS: { tier: Exclude<Tier, 'idle'>; label: string }[] = [
  { tier: 'read', label: 'team.tiers.read' },
  { tier: 'change', label: 'team.tiers.change' },
  { tier: 'never', label: 'team.tiers.never' },
];

export default function PeerTiers({
  rules,
  source,
  guess,
}: {
  rules: RequestRules;
  source: RulesSource;
  guess: TierGuess;
}) {
  const { t } = useTranslation();
  const idle = guess.tier === 'idle';
  const byTip = source === 'teammate' ? t('team.tiers.byTeammateTip') : t('team.tiers.byFragoTip');
  return (
    <div data-testid="peer-tiers">
      <div className="mt-2 flex min-w-0 items-center gap-1.5 whitespace-nowrap text-[11px] text-text-muted">
        <Lock size={12} className="shrink-0" />
        <span className="min-w-0 truncate">{t('team.tiers.title')}</span>
        <span
          data-testid="peer-tiers-source"
          data-source={source}
          title={byTip}
          className="ml-auto inline-flex h-[18px] shrink-0 items-center rounded-full bg-[var(--peer-chip)] px-[7px] text-[11px] font-medium text-[var(--peer-ink)]"
        >
          {source === 'teammate' ? t('team.tiers.byTeammate') : t('team.tiers.byFrago')}
        </span>
      </div>
      <div className="mt-[5px] grid grid-cols-3 gap-1.5">
        {CELLS.map(({ tier, label }) => {
          const verdict = verdictOf(tier, rules);
          const on = guess.tier === tier;
          return (
            <div
              key={tier}
              data-testid={`tier-${tier}`}
              data-on={on ? 'true' : undefined}
              title={tier === 'never' ? t('team.tiers.neverTip') : byTip}
              /* 点亮＝整格换中性底加一圈描边，与全局选中态同一套；没点亮的淡下去。
                 还没写字时三格都照常显示，让人先看清对方的规矩是什么。 */
              className={`min-w-0 cursor-default rounded-lg border px-2 py-[5px] ${
                on
                  ? 'border-[var(--sel-border)] bg-[var(--sel-bg)]'
                  : `border-border-color bg-bg-primary ${idle ? '' : 'opacity-70'}`
              }`}
            >
              <div className="truncate text-[11px] text-text-muted">{t(label)}</div>
              <div
                className={`truncate text-[12px] font-medium ${
                  on && verdict === 'refuse' ? 'text-accent-error' : ''
                }`}
              >
                {t(`team.verdict.${verdict}`)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** 发送键左边那一句：按哪个词判的、对方 agent 大概会怎么处理。 */
export function Prediction({ guess, rules }: { guess: TierGuess; rules: RequestRules }) {
  const key = predictionKey(guess, rules);
  const words = guess.words.map((w) => `“${w}”`).join(', ');
  return (
    <span
      data-testid="peer-prediction"
      data-key={key}
      className="min-w-0 flex-1 text-[11px] leading-[1.4] text-text-muted [&_b]:font-medium [&_b]:text-text-primary"
    >
      <Trans
        i18nKey={`team.predict.${key}`}
        values={{ words }}
        components={{ b: <b /> }}
        shouldUnescape
      />
    </span>
  );
}
