/**
 * 左栏的队友请求块：队友经中继让我的 agent 做的一件事。
 *
 * 它在本机会话里是一条用户发言，正文带着投递前缀、本机主人的设置与核实行——那几行是
 * 给 agent 看的。人要看的是三件事：这是队友来的（整块冷色底、冷色头像、「From your
 * teammate」）、他要什么（原文）、按我的规矩大概怎么处理（最底下一行）。
 *
 * **界面不判定来路。** 「verified」来自本机投递账（与 `frago team verify` 同一个判据），
 * 核实不了就写「not verified」，不猜。处理那一行是按请求里的词猜的，悬停写明以 agent
 * 自己的回复为准——agent 读的是原文，界面只是在旁边提个醒。
 *
 * 之后怎么处理由 agent 写在它自己的回复里：直接做的照常出工具调用与回复；要问我的，
 * 回复末尾是一张「来自队友」的决定卡（画法归 `20260924-webui-decision-cards`）；拒绝的
 * 照常显示那段回复。
 */

import { useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Shield } from 'lucide-react';
import { formatClock } from '@/components/sessionWorkbench/RecordCard';
import { verifyRelayed } from '@/hooks/useTeam';
import TeamAvatar from './TeamAvatar';
import { classifyTier, verdictOf, type RequestRules } from './teamRequest';

/** 核实通过的记住：来路不会变，每 15 秒重画一次不该每次都去问。 */
const verified = new Set<string>();

/**
 * 没通过的隔一会儿再问一次。同步循环是先把消息投进会话、再把编号记进投递账，这条发言
 * 刚出现的那一两秒里去问，查到的是还没记上的账。
 */
const RECHECK_MS = 5_000;

function useVerified(code: string, messageId: string): boolean | null {
  const key = `${code}:${messageId}`;
  const [genuine, setGenuine] = useState<boolean | null>(verified.has(key) ? true : null);
  useEffect(() => {
    if (verified.has(key)) {
      setGenuine(true);
      return;
    }
    let live = true;
    let timer: number | undefined;
    const ask = (again: boolean) => {
      verifyRelayed(code, messageId)
        .then((ok) => {
          if (ok) verified.add(key);
          if (!live) return;
          setGenuine(ok);
          if (!ok && again) timer = window.setTimeout(() => ask(false), RECHECK_MS);
        })
        .catch(() => {
          // 问不到就不写，NEVER 替它写一个「verified」。
        });
    };
    ask(true);
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [code, messageId, key]);
  return genuine;
}

const TIER_KEY = {
  read: 'team.incoming.tierRead',
  change: 'team.incoming.tierChange',
  never: 'team.incoming.tierNever',
} as const;

export default function IncomingRequest({
  body,
  code,
  messageId,
  ts,
  rules,
}: {
  body: string;
  /** 本机这一侧参加的那个码（完整的，只用来核实，不显示）。 */
  code: string;
  messageId: string;
  ts: number;
  /** 本机主人此刻的设置；旧版服务端没有时不画最底下那一行。 */
  rules: RequestRules | null;
}) {
  const { t } = useTranslation();
  const genuine = useVerified(code, messageId);
  const guess = classifyTier(body);
  const tier = guess.tier === 'idle' ? 'read' : guess.tier;
  const verdict = rules ? verdictOf(tier, rules) : null;

  return (
    <div
      data-testid="team-incoming"
      className="rounded-[10px] border border-border-color bg-[var(--peer-bg)] px-2.5 pb-[9px] pt-2"
    >
      <div className="flex min-w-0 items-center gap-[7px] text-[11px] text-text-muted">
        <TeamAvatar who="peer" size="sm" />
        <span className="inline-flex h-[18px] shrink-0 items-center whitespace-nowrap rounded-full bg-[var(--peer-chip)] px-[7px] font-medium text-[var(--peer-ink)]">
          {t('team.incoming.from')}
        </span>
        <span className="min-w-0 truncate">
          {t('team.incoming.via')}
          {genuine === null
            ? ''
            : ` · ${genuine ? t('team.incoming.verified') : t('team.incoming.notVerified')}`}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[11px] text-text-dim">
          {formatClock(ts)}
        </span>
      </div>
      <p className="mt-[5px] whitespace-pre-wrap text-[13px] leading-[1.55] [overflow-wrap:anywhere]">
        {body}
      </p>
      {verdict ? (
        <p
          data-testid="team-incoming-rules"
          title={t('team.incoming.yourRulesTip')}
          className="mt-1.5 flex items-center gap-[5px] text-[11px] text-text-muted [&_b]:font-medium [&_b]:text-text-secondary"
        >
          <Shield size={12} className="shrink-0" />
          <span>
            <Trans
              i18nKey="team.incoming.yourRules"
              values={{
                tier: t(TIER_KEY[tier]),
                verdict: t(`team.rules.word.${verdict}`),
              }}
              components={{ b: <b /> }}
              shouldUnescape
            />
          </span>
        </p>
      ) : null}
    </div>
  );
}
