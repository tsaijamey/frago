/**
 * SessionLaunchPanel — 新建会话发出第一句话之后、档案落盘之前的原地对话流过渡视图。
 *
 * 点击「开始会话」后不再展示突兀的居中绿色信封卡片，而是直接进入与会话详情一致的
 * 「档位条 + 对话流 + 底部输入框」布局：
 * - 刚发出的第一句话置顶渲染为标准「你说」气泡（带新消息描边）；
 * - 气泡下方紧接轻量步骤链（认领编号 › 写下第一笔）与单行实时状态条；
 * - 若启动失败，第一句话仍保留在气泡中，下方内联展示错误原因并提供「返回修改」与「收起」。
 */

import { Fragment, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Check, Loader2, Paperclip, Send } from 'lucide-react';
import type { SessionLaunch } from '@/hooks/useSessionLaunch';
import { withTilde } from './filePaths';
import { KIND_LABEL_KEY, formatClock, formatDuration } from './RecordCard';
import { LENS_LABEL_KEY, LENS_ORDER, type StreamLens } from './RecordStream';
import { SEG_GROUP, SEG_ITEM, SEG_OFF, SEG_ON, SEG_TIGHT } from './seg';

export interface SessionLaunchPanelProps {
  launch: SessionLaunch;
  /** 人把没起来的那张卡收掉。 */
  onDismiss: () => void;
  /** 启动失败时回到内联新建会话起始页重新编辑。 */
  onBackToEdit?: () => void;
}

/** 一步走到哪了：还没轮到、正在走、已经过去。 */
type StepState = 'waiting' | 'active' | 'done';

function Step({ state, label }: { state: StepState; label: string }) {
  return (
    <span
      data-testid="launch-step"
      data-state={state}
      className={`inline-flex items-center gap-1 text-[11px] ${
        state === 'waiting'
          ? 'text-text-muted'
          : state === 'active'
            ? 'font-medium text-text-primary'
            : 'text-text-secondary'
      }`}
    >
      <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center">
        {state === 'done' ? (
          <Check size={12} className="text-accent-primary" />
        ) : state === 'active' ? (
          <Loader2 size={11} className="animate-spin text-text-secondary" />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-text-muted" />
        )}
      </span>
      <span>{label}</span>
    </span>
  );
}

export default function SessionLaunchPanel({
  launch,
  onDismiss,
  onBackToEdit,
}: SessionLaunchPanelProps) {
  const { t } = useTranslation();
  const failed = launch.phase === 'failed';
  const claiming = launch.phase === 'claiming';
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (failed) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(id);
  }, [failed, launch.at]);

  const clock = formatClock(launch.at);
  const elapsed = formatDuration(Math.max(1_000, now - launch.at));
  const hasMessage = Boolean(launch.text);
  const [lens, setLens] = useState<StreamLens>('talk');
  const counts: Record<StreamLens, number> = {
    all: hasMessage ? 1 : 0,
    talk: hasMessage ? 1 : 0,
    hook: 0,
    tool: 0,
    system: 0,
  };

  return (
    <div
      data-testid="session-launch"
      data-phase={launch.phase}
      className="flex h-full min-h-0 min-w-0 flex-col"
    >
      {/* 顶部镜头档位条：直接复用会话详情 RecordStream 的同一套词条、顺序与默认选中态，接管时零跳变 */}
      <div
        data-testid="stream-lens"
        className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border-color px-4 py-2"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
          <div className={SEG_GROUP}>
            <button
              type="button"
              data-testid="lens-watcher"
              aria-pressed="false"
              disabled={!hasMessage}
              className={`${SEG_ITEM} ${SEG_TIGHT} ${SEG_OFF}`}
            >
              {t('workbench.stream.watcher')}
              <span className="font-mono opacity-60">{hasMessage ? 1 : 0}</span>
            </button>
          </div>
          <span
            data-testid="lens-executor-label"
            className="shrink-0 select-none whitespace-nowrap px-0.5 text-[12px] font-medium text-text-muted"
          >
            {t('workbench.stream.executor')}
          </span>
          <div className={SEG_GROUP}>
            {LENS_ORDER.map((id) => (
              <Fragment key={id}>
                {id === 'system' ? (
                  <button
                    type="button"
                    data-testid="lens-files"
                    aria-pressed="false"
                    title={t('workbench.files.lensHint')}
                    className={`${SEG_ITEM} ${SEG_TIGHT} ${SEG_OFF}`}
                  >
                    {t('workbench.files.lens')}
                    <span className="font-mono opacity-60">0</span>
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => setLens(id)}
                  aria-pressed={lens === id}
                  data-testid={`lens-${id}`}
                  title={id === 'hook' ? t('workbench.stream.lensHookFull') : undefined}
                  disabled={counts[id] === 0}
                  className={`${SEG_ITEM} ${SEG_TIGHT} ${lens === id ? SEG_ON : SEG_OFF}`}
                >
                  {t(LENS_LABEL_KEY[id])}
                  <span className="font-mono opacity-60">{counts[id]}</span>
                </button>
              </Fragment>
            ))}
          </div>
        </div>
      </div>

      {/* 对话流主区：刚发出的第一句话直接作为首条「你说」气泡落地 */}
      <div className="min-h-0 flex-1 overflow-y-auto pb-10 pl-4 pr-4 pt-4">
        <div className="flex w-full min-w-0 flex-col gap-2.5">
          {launch.text ? (
            <div className="flex min-w-0 flex-col gap-1.5">
              <div
                data-testid="trail-bubble"
                data-fresh="true"
                className="rounded-[9px] outline outline-1 outline-offset-2 outline-[var(--sel-border)]"
              >
                <article
                  data-kind="user.say"
                  className="min-w-0 rounded-[8px] bg-bg-subtle px-3 py-2 ring-1 ring-border-color"
                >
                  <header className="flex items-center gap-2 text-[11px] text-text-muted">
                    <span className="inline-flex shrink-0 items-center gap-1 text-[11px] font-semibold text-text-muted">
                      {t(KIND_LABEL_KEY['user.say'])}
                    </span>
                    {clock ? (
                      <span className="shrink-0 font-mono text-[11px] text-text-muted">{clock}</span>
                    ) : null}
                    <span className="flex-1" />
                  </header>
                  <div className="mt-1.5 min-w-0">
                    <p
                      data-testid="launch-first-message"
                      className="whitespace-pre-wrap break-words text-[16px] leading-[1.72] text-text-primary"
                    >
                      {launch.text}
                    </p>
                  </div>
                </article>
              </div>
            </div>
          ) : null}

          {failed ? (
            <div className="flex flex-wrap items-center gap-2.5 rounded-[8px] border border-accent-error/40 bg-accent-error-10 px-3.5 py-2.5 text-[12px] text-accent-error">
              <AlertTriangle size={14} className="shrink-0 text-accent-error" />
              <p data-testid="launch-error" className="min-w-0 flex-1 leading-5 text-accent-error">
                {t('workbench.launch.failed', { reason: launch.error ?? '' })}
              </p>
              <div className="flex shrink-0 items-center gap-1.5">
                {onBackToEdit ? (
                  <button
                    type="button"
                    data-testid="launch-back-to-edit"
                    onClick={onBackToEdit}
                    className="rounded-[6px] border border-border-color bg-bg-card px-2.5 py-1 text-[11.5px] font-medium text-text-primary hover:bg-bg-hover"
                  >
                    {t('workbench.launch.backToEdit')}
                  </button>
                ) : null}
                <button
                  type="button"
                  data-testid="launch-dismiss"
                  onClick={onDismiss}
                  aria-label={t('workbench.launch.dismiss')}
                  className="rounded-[6px] border border-border-color bg-bg-card px-2.5 py-1 text-[11.5px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
                >
                  {t('workbench.launch.dismiss')}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1 px-3 text-[11px]">
                <Step
                  state={claiming ? 'active' : 'done'}
                  label={t('workbench.launch.stepClaim', { name: launch.agentName })}
                />
                <span aria-hidden className="text-text-dim">
                  ›
                </span>
                <Step
                  state={claiming ? 'waiting' : 'active'}
                  label={t('workbench.launch.stepFirstRecord')}
                />
              </div>

              <div
                data-testid="launch-live-status"
                className="flex min-w-0 max-w-[640px] items-center gap-2 self-start rounded-[8px] border border-border-color bg-bg-secondary px-3 py-1.5 text-[11.5px] text-text-muted"
              >
                {claiming ? (
                  <>
                    <Loader2 size={12} className="shrink-0 animate-spin text-text-secondary" />
                    <span className="shrink-0 font-medium text-text-primary">
                      {t('workbench.launch.railClaiming', { name: launch.agentName })}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-muted">
                      {withTilde(launch.cwd)}
                    </span>
                  </>
                ) : (
                  <>
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-primary"
                    />
                    <span className="shrink-0 font-medium text-text-primary">
                      {t('workbench.progress.agentOnIt')}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-text-muted">
                      {t('workbench.launch.railWarming', { name: launch.agentName })} ·{' '}
                      <span className="font-mono">{withTilde(launch.cwd)}</span>
                    </span>
                  </>
                )}
                <span className="shrink-0 font-mono text-[11px] text-text-dim">{elapsed}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 底部输入框占位：与真实会话详情输入框同位同高，避免首条记录落盘时底栏跳变 */}
      <div className="shrink-0 border-t border-border-color bg-bg-primary px-4 py-3">
        <div className="flex flex-col gap-2 rounded-[10px] border border-border-color bg-bg-secondary px-3 py-2.5 opacity-60">
          <p className="select-none text-[13px] text-text-muted">
            {t('workbench.composer.placeholderWithFamily', { family: launch.agentName })}
          </p>
          <div className="flex items-center justify-between pt-1">
            <span className="inline-flex h-6 w-6 items-center justify-center rounded-[6px] text-text-muted">
              <Paperclip size={14} />
            </span>
            <button
              type="button"
              disabled
              className="inline-flex h-7 items-center gap-1.5 rounded-[8px] bg-accent-primary px-3 text-[12px] font-medium text-[var(--text-on-accent)] opacity-50"
            >
              <Send size={12} />
              {t('workbench.composer.send')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
