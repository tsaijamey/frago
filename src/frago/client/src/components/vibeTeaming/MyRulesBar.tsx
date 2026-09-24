/**
 * 左栏输入框上方：我的 agent 怎么对待队友让它做的事。**只有我能改。**
 *
 * 平时收成一行摘要（「Teammate requests: read-only → do it · changes → ask me」），点开
 * 三行：只读的、会改动的各两种选法；第三档（秘密、删除）锁死为拒绝，悬停说明这是
 * frago 的规矩、谁也打不开。改了当场存进本机，下一条投进来的队友消息就带着新设置，
 * 下一轮同步对方右下那三格也跟着变。
 *
 * 选中态照全局规矩：中性实底，不用绿、不用单边条。
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Lock, Shield } from 'lucide-react';
import { saveRequestRules } from '@/hooks/useTeam';
import type { RequestRules } from './teamRequest';

function Choice<T extends string>({
  value,
  options,
  onPick,
  disabled,
}: {
  value: T;
  options: { value: T; label: string }[];
  onPick: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex shrink-0 items-center gap-0.5 rounded-[7px] border border-border-color p-0.5">
      {options.map((one) => (
        <button
          key={one.value}
          type="button"
          onClick={() => onPick(one.value)}
          disabled={disabled}
          aria-pressed={value === one.value}
          data-testid={`rule-${one.value}`}
          className={`rounded-[5px] px-2 py-[3px] text-[11px] transition-colors disabled:opacity-50 ${
            value === one.value
              ? 'bg-bg-active font-medium text-text-primary'
              : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'
          }`}
        >
          {one.label}
        </button>
      ))}
    </div>
  );
}

function Row({
  title,
  body,
  children,
  tip,
}: {
  title: string;
  body: string;
  children: React.ReactNode;
  tip?: string;
}) {
  return (
    <div
      title={tip}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2.5 border-t border-border-color py-1.5"
    >
      <div className="min-w-0">
        <div className="text-[12px] font-semibold leading-[1.4]">{title}</div>
        <div className="text-[11px] leading-[1.4] text-text-muted">{body}</div>
      </div>
      {children}
    </div>
  );
}

export default function MyRulesBar({
  rules,
  onSaved,
}: {
  rules: RequestRules;
  onSaved: (rules: RequestRules) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (next: RequestRules) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onSaved(await saveRequestRules(next));
    } catch (err) {
      setError(
        t('team.rules.saveFailed', {
          error: err instanceof Error ? err.message : String(err),
        }),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="my-rules" className="shrink-0 border-t border-border-color">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={t('team.rules.onlyYou')}
        className="flex h-[34px] w-full min-w-0 items-center gap-[7px] px-[14px] text-left text-[12px] hover:bg-bg-hover"
      >
        <Shield size={13} className="shrink-0 text-text-muted" />
        <span className="shrink-0 whitespace-nowrap text-text-muted">
          {t('team.rules.summaryKey')}
        </span>
        <span data-testid="my-rules-summary" className="min-w-0 flex-1 truncate text-text-primary">
          {t('team.rules.summary', {
            read: t(`team.rules.word.${rules.read}`),
            change: t(`team.rules.word.${rules.change}`),
          })}
        </span>
        <span className="inline-flex shrink-0 items-center gap-[3px] text-[11px] text-text-secondary">
          {open ? t('team.rules.close') : t('team.rules.open')}
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
      </button>
      {open ? (
        <div className="px-[14px] pb-2.5">
          <p className="mb-1.5 text-[11px] leading-[1.45] text-text-muted">
            {t('team.rules.note')}
          </p>
          <Row title={t('team.rules.readTitle')} body={t('team.rules.readBody')}>
            <Choice
              value={rules.read}
              disabled={busy}
              options={[
                { value: 'do', label: t('team.rules.doIt') },
                { value: 'ask', label: t('team.rules.askMe') },
              ]}
              onPick={(read) => void save({ ...rules, read })}
            />
          </Row>
          <Row title={t('team.rules.changeTitle')} body={t('team.rules.changeBody')}>
            <Choice
              value={rules.change}
              disabled={busy}
              options={[
                { value: 'ask', label: t('team.rules.askMe') },
                { value: 'refuse', label: t('team.rules.refuse') },
              ]}
              onPick={(change) => void save({ ...rules, change })}
            />
          </Row>
          <Row
            title={t('team.rules.neverTitle')}
            body={t('team.rules.neverBody')}
            tip={t('team.tiers.neverTip')}
          >
            <div className="flex shrink-0 items-center rounded-[7px] border border-border-color p-0.5">
              <span className="inline-flex cursor-help items-center gap-1 rounded-[5px] bg-bg-active px-2 py-[3px] text-[11px] font-medium text-text-primary">
                <Lock size={11} />
                {t('team.rules.refuse')}
              </span>
            </div>
          </Row>
          {error ? <p className="mt-1 text-[11px] text-accent-error">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
