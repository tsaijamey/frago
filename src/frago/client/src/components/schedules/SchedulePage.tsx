/**
 * 定时任务——`frago schedule` 里那些任务，界面上第一次看得见、管得了。
 *
 * 任务存在 `~/.frago/schedules.json`，由服务端进程里的调度器每 5 秒读一遍、到点执行。
 * 顺序照搬服务端（按创建先后），跟 `frago schedule list` 一致。
 *
 * 调度器没在跑时页面顶上明说：清单里每一条「下次运行」都照常印着，但一条都不会兑现
 * ——不说出来，人会以为任务在跑。
 *
 * 新建走 agent：人写一句话，agent 去敲 `frago schedule add`。那条命令的校验（配方
 * 存不存在、cron 合不合法、通知落点配没配）只有走命令行才生效。
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Clock, Loader2, Plus, RefreshCw, Search, X } from 'lucide-react';
import * as api from '@/api';
import type { ScheduleItem, ScheduleListResponse } from '@/api';
import { usePageStore } from '@/stores/pageStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmptyState from '@/components/ui/EmptyState';
import ScheduleDetail from './ScheduleDetail';
import {
  FILTERS,
  STATE_CHIP,
  formatTime,
  frequencyText,
  matchesFilter,
  stateOf,
  targetText,
  type ScheduleFilter,
} from './scheduleMeta';

/** 执行记录要在人点完「立即跑」之后很快出现，所以比事务页刷得勤。 */
const REFRESH_MS = 10_000;

/** 点完「立即跑」隔多久补取一次。命令型大多一两秒就跑完，赶在自动刷新之前让结果露面。 */
const RUN_FOLLOWUP_MS = 2_500;

function ScheduleRow({
  schedule,
  selected,
  onClick,
}: {
  schedule: ScheduleItem;
  selected: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  const state = stateOf(schedule);

  return (
    <button
      type="button"
      className={`td-row ${selected ? 'td-row--selected' : ''} ${schedule.enabled ? '' : 'sc-row--disabled'}`}
      onClick={onClick}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="td-row-head">
        <span className={`td-chip ${STATE_CHIP[state]}`}>{t(`schedules.state.${state}`)}</span>
        <span className="td-chip td-chip--normal">{t(`schedules.kind.${schedule.kind}`)}</span>
        <span className="td-row-title">{schedule.name}</span>
      </div>
      <p className="td-row-line sc-row-target">{targetText(schedule)}</p>
      <div className="td-row-meta">
        <span>{frequencyText(schedule, t)}</span>
        {schedule.enabled && schedule.next_run_at && (
          <span>{t('schedules.row.next', { time: formatTime(schedule.next_run_at) })}</span>
        )}
        <span>{t('schedules.row.runs', { n: schedule.run_count })}</span>
        {schedule.consecutive_failures > 0 && (
          <span className="sc-warn">
            {t('schedules.row.failures', { n: schedule.consecutive_failures })}
          </span>
        )}
      </div>
    </button>
  );
}

export default function SchedulePage() {
  const { t } = useTranslation();
  const currentScheduleId = usePageStore((s) => s.currentScheduleId);
  const switchPage = usePageStore((s) => s.switchPage);

  const [body, setBody] = useState<ScheduleListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<ScheduleFilter>('all');
  const [search, setSearch] = useState('');

  const [busy, setBusy] = useState<'run' | 'toggle' | 'remove' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [composerOpen, setComposerOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [composing, setComposing] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composed, setComposed] = useState<api.ScheduleComposeResponse | null>(null);

  const { refresh } = useAutoRefresh(
    async () => {
      setRefreshing(true);
      try {
        setBody(await api.getSchedules());
        setError(null);
      } catch (e) {
        // 取不到就说取不到，不拿上一份旧清单顶着——旧的「上次成功」看起来和新的一模一样。
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRefreshing(false);
      }
    },
    { intervalMs: REFRESH_MS }
  );

  const schedules = useMemo(() => body?.schedules ?? [], [body]);

  const counts = useMemo(() => {
    const out = {} as Record<ScheduleFilter, number>;
    for (const name of FILTERS) out[name] = schedules.filter((s) => matchesFilter(s, name)).length;
    return out;
  }, [schedules]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return schedules.filter((s) => {
      if (!matchesFilter(s, filter)) return false;
      if (!q) return true;
      return [s.name, s.id, targetText(s), s.cron ?? '', s.notify?.to ?? '']
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [schedules, filter, search]);

  const selected = currentScheduleId
    ? schedules.find((s) => s.id === currentScheduleId) ?? null
    : null;
  const missing = Boolean(currentScheduleId) && body !== null && selected === null;

  /** 三个动作共用的外壳：锁按钮、报错、做完刷新。 */
  const act = async (kind: 'run' | 'toggle' | 'remove', work: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(kind);
    setActionError(null);
    try {
      await work();
      await refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const runNow = (s: ScheduleItem) =>
    act('run', async () => {
      await api.runSchedule(s.id);
      // 接口不等执行结束。补取一次，让这一轮的执行记录尽快露面。
      window.setTimeout(() => void refresh(), RUN_FOLLOWUP_MS);
    });

  const toggle = (s: ScheduleItem) => act('toggle', () => api.toggleSchedule(s.id));

  const remove = (s: ScheduleItem) =>
    act('remove', async () => {
      await api.removeSchedule(s.id);
      switchPage('schedules');
    });

  const submitDraft = async () => {
    const text = draft.trim();
    if (!text || composing) return;

    setComposing(true);
    setComposeError(null);
    setComposed(null);
    try {
      const result = await api.composeSchedule(text);
      setComposed(result);
      setDraft('');
      await refresh();
      if (result.schedule_id) switchPage('schedule_detail', result.schedule_id);
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : String(e));
    } finally {
      setComposing(false);
    }
  };

  return (
    <div className="td-page">
      <div className="cs-header" style={{ padding: '20px 20px 0' }}>
        <div>
          <h1 className="cs-title">{t('schedules.title')}</h1>
          <p className="cs-subtitle">{t('schedules.pageDesc')}</p>
        </div>
        <div className="td-head-actions">
          <button
            type="button"
            className={`td-add ${composerOpen ? 'td-add--open' : ''}`}
            onClick={() => setComposerOpen((open) => !open)}
            aria-expanded={composerOpen}
          >
            <Plus size={14} />
            {t('schedules.compose.button')}
          </button>
          <button type="button" className="cs-refresh" onClick={refresh} disabled={refreshing}>
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            {t('common.refresh')}
          </button>
        </div>
      </div>

      {composerOpen && (
        <div className="td-composer">
          <textarea
            className="td-composer-input"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void submitDraft();
              }
            }}
            placeholder={t('schedules.compose.placeholder')}
            disabled={composing}
            aria-label={t('schedules.compose.button')}
          />
          <div className="td-composer-foot">
            <span className="td-composer-hint">{t('schedules.compose.hint')}</span>
            <button
              type="button"
              className="td-composer-submit"
              onClick={() => void submitDraft()}
              disabled={composing || draft.trim() === ''}
            >
              {composing && <Loader2 size={14} className="animate-spin" />}
              {composing ? t('schedules.compose.working') : t('schedules.compose.submit')}
            </button>
          </div>

          {composeError && (
            <div className="td-error">{t('schedules.compose.failed', { message: composeError })}</div>
          )}

          {composed && (
            <div className="td-composer-result">
              <p className="td-composer-verdict">
                {composed.schedule_id
                  ? t('schedules.compose.created', { id: composed.schedule_id })
                  : t('schedules.compose.nothingCreated')}
              </p>
              {composed.command && (
                <code className="td-composer-command">{composed.command.join(' ')}</code>
              )}
              {composed.message && <p className="td-composer-message">{composed.message}</p>}
            </div>
          )}
        </div>
      )}

      {body && !body.scheduler_running && (
        <div className="td-error">{t('schedules.schedulerStopped')}</div>
      )}

      <div className="td-toolbar">
        <div className="td-filters">
          {FILTERS.map((name) => (
            <button
              key={name}
              type="button"
              className={`td-filter ${filter === name ? 'td-filter--active' : ''}`}
              onClick={() => setFilter(name)}
            >
              {t(`schedules.filter.${name}`)}
              <span className="td-filter-count">{counts[name]}</span>
            </button>
          ))}
        </div>
        <div className="search-box td-search">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder={t('schedules.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t('schedules.searchPlaceholder')}
          />
          {search && (
            <button
              type="button"
              className="search-clear"
              onClick={() => setSearch('')}
              aria-label={t('common.clear')}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {error && <div className="td-error">{t('schedules.loadFailed', { message: error })}</div>}
      {actionError && (
        <div className="td-error">{t('schedules.actions.failed', { message: actionError })}</div>
      )}
      {missing && <div className="td-error">{t('schedules.notFound', { id: currentScheduleId })}</div>}

      <div className="td-split">
        <div className="td-list-pane">
          {body === null && !error ? (
            <div className="td-hint">{t('common.loading')}</div>
          ) : visible.length === 0 ? (
            <EmptyState
              Icon={Clock}
              title={schedules.length === 0 ? t('schedules.emptyAll') : t('schedules.empty')}
              description={
                schedules.length === 0 ? t('schedules.emptyAllDesc') : t('schedules.emptyDesc')
              }
            />
          ) : (
            visible.map((s) => (
              <ScheduleRow
                key={s.id}
                schedule={s}
                selected={s.id === currentScheduleId}
                onClick={() =>
                  s.id === currentScheduleId
                    ? switchPage('schedules')
                    : switchPage('schedule_detail', s.id)
                }
              />
            ))
          )}
        </div>

        {selected && (
          <div className="td-detail-pane">
            {/* 换一条任务时整块重建，上一条停在「确认删除」的状态不能带过来。 */}
            <ScheduleDetail
              key={selected.id}
              schedule={selected}
              busy={busy}
              onRun={() => void runNow(selected)}
              onToggle={() => void toggle(selected)}
              onRemove={() => void remove(selected)}
              onClose={() => switchPage('schedules')}
            />
          </div>
        )}
      </div>
    </div>
  );
}
