/**
 * 定时任务工作台——对齐主原型 `#schedules` / `#schedules/new` / `#schedules/edit/:id` / `#schedules/detail/:id`。
 *
 * 三态共用同一条页面壳：
 * - 列表总览（`#schedules`）：全局表头 + 禁用/停跑/异常恢复横幅 + 筛选搜索 + 任务清单（含数字员工彩标与末次会话链接）。
 * - 新建 / 编辑态（`#schedules/new`、`#schedules/edit/:id`）：左侧 280px 任务列表 + 右侧 3 张分组卡（基础节奏、两层执行形态、动态会话标题模板与 3 次预览），外加可选「一句话让 agent 创建」入口。
 * - 详情归属态（`#schedules/detail/:id`）：左侧 280px 任务列表 + 右侧归属标识卡、参数属性表、定时指令与继承上下文、执行记录与一键跳回工作台会话。
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import PageHeader from '@/components/layout/PageHeader';
import {
  Check,
  CirclePause,
  Clock,
  ExternalLink,
  Plus,
  RefreshCw,
  Search,
  TriangleAlert,
  X,
} from 'lucide-react';
import * as api from '@/api';
import type { ScheduleItem, ScheduleListResponse } from '@/api';
import type { EmployeeItem } from '@/types/api';
import type { RecipeItem } from '@/types/pywebview';
import { restartServer } from '@/api/client';
import { usePageStore } from '@/stores/pageStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmptyState from '@/components/ui/EmptyState';
import ScheduleDetail from './ScheduleDetail';
import ScheduleEditPane from './ScheduleEditPane';
import ScheduleStateIcon from './ScheduleStateIcon';
import {
  FILTERS,
  cronRawText,
  empColorToken,
  formatTime,
  frequencyText,
  lastRunText,
  matchesFilter,
  stateOf,
  targetText,
  type ScheduleFilter,
} from './scheduleMeta';

/** 执行记录要在人点完「立即跑」之后很快出现，所以比事务页刷得勤。 */
const REFRESH_MS = 10_000;

/** 点完「立即跑」隔多久补取一次。命令型大多一两秒就跑完，赶在自动刷新之前让结果露面。 */
const RUN_FOLLOWUP_MS = 2_500;

type ScheduleViewMode = 'list' | 'new' | 'edit' | 'detail';

interface ScheduleView {
  mode: ScheduleViewMode;
  id: string | null;
}

function parseScheduleRoute(rawId: string | null): ScheduleView {
  if (!rawId) return { mode: 'list', id: null };
  if (rawId === 'new') return { mode: 'new', id: null };
  if (rawId.startsWith('edit/')) {
    const id = rawId.slice(5).trim();
    return id ? { mode: 'edit', id } : { mode: 'new', id: null };
  }
  if (rawId.startsWith('detail/')) {
    const id = rawId.slice(7).trim();
    return id ? { mode: 'detail', id } : { mode: 'list', id: null };
  }
  return { mode: 'detail', id: rawId };
}

function ScheduleRow({
  schedule,
  employee,
  employeesLoaded,
  selected,
  now,
  onClick,
  onRunNow,
  busy,
}: {
  schedule: ScheduleItem;
  employee?: EmployeeItem;
  employeesLoaded: boolean;
  selected: boolean;
  now: Date;
  onClick: () => void;
  onRunNow: () => void;
  busy: boolean;
}) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');
  const switchPage = usePageStore((s) => s.switchPage);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);
  const state = stateOf(schedule);
  const target = targetText(schedule);
  const raw = cronRawText(schedule, t);
  const status = schedule.last_status;
  const failCount = Math.max(1, schedule.consecutive_failures || 1);

  const effectiveSessionId =
    schedule.last_session_id ||
    schedule.last_run?.session_id ||
    (schedule.history.length > 0 ? schedule.history[schedule.history.length - 1].session_id : null);

  const isEmployee = schedule.kind === 'employee';
  const empMissing =
    isEmployee &&
    (Boolean(schedule.employee_missing) ||
      (Boolean(schedule.employee_id) && employeesLoaded && !employee));
  const empColor = empColorToken(schedule.employee_id, employee?.color);

  return (
    <tr
      className={`sc-tr ${selected ? 'sc-tr--selected' : ''} ${
        state === 'failing' ? 'ui-row-failing' : ''
      } ${schedule.enabled ? '' : 'sc-row--disabled'}`}
      onClick={onClick}
    >
      <td>
        <div className="sc-cell-name">
          <ScheduleStateIcon state={state} />
          <button
            type="button"
            className="sc-name"
            onClick={(e) => {
              e.stopPropagation();
              onClick();
            }}
            aria-current={selected ? 'true' : undefined}
          >
            {schedule.name}
          </button>
          {isEmployee ? (
            <span
              className="sc-chip emp"
              data-emp-color={empColor}
              data-testid={`sc-row-emp-${schedule.id}`}
            >
              @{schedule.employee_id || '—'}
            </span>
          ) : (
            <span className="td-chip td-chip--normal">{t(`schedules.kind.${schedule.kind}`)}</span>
          )}
          {empMissing && (
            <span className="sc-chip warn" data-testid={`sc-row-emp-missing-${schedule.id}`}>
              <TriangleAlert size={10} />
              {t('schedules.state.failing')}
            </span>
          )}
          {!schedule.enabled && (
            <span className="td-chip sc-chip--disabled">{t('schedules.filter.disabled')}</span>
          )}
          {state === 'failing' && (
            <span className="td-chip sc-chip--failing">
              {t('schedules.row.failedCount', {
                count: failCount,
                defaultValue: isZh ? `失败 ×${failCount}` : `Failed ×${failCount}`,
              })}
            </span>
          )}
        </div>
        {target && <div className="sc-sub sc-target-line">{target}</div>}
      </td>
      <td className="sc-when">
        <div>{frequencyText(schedule, t)}</div>
        {raw && <div className="sc-raw">{raw}</div>}
      </td>
      <td className="sc-when" title={schedule.last_run_at ? formatTime(schedule.last_run_at) : undefined}>
        <div>{lastRunText(schedule.last_run_at, now, t)}</div>
        {(schedule.last_run_at && status) || state === 'failing' ? (
          <div className={`sc-sub sc-last-row ${status === 'failed' || state === 'failing' ? 'sc-fail' : ''}`}>
            <span>
              {status
                ? t(`schedules.runStatus.${status}`, { defaultValue: status })
                : t('schedules.runStatus.failed', { defaultValue: isZh ? '失败' : 'Failed' })}
            </span>
            {state === 'failing' && (
              <button
                type="button"
                className="fix-btn"
                disabled={busy}
                onClick={(e) => {
                  e.stopPropagation();
                  onRunNow();
                }}
                data-testid={`schedule-fix-run-${schedule.id}`}
              >
                {t('schedules.actions.runNow', { defaultValue: isZh ? '立即运行' : 'Run now' })}
              </button>
            )}
          </div>
        ) : null}
        {effectiveSessionId && (
          <button
            type="button"
            className="sc-run-link"
            onClick={(e) => {
              e.stopPropagation();
              setWorkbenchSessionId(effectiveSessionId);
              switchPage('session_workbench');
            }}
            title={schedule.last_session_title || t('schedules.history.openSession')}
          >
            <ExternalLink size={11} />
            <span>
              {schedule.last_session_title
                ? schedule.last_session_title
                : effectiveSessionId.length > 12
                  ? `${effectiveSessionId.slice(0, 5)}...${effectiveSessionId.slice(-3)}`
                  : effectiveSessionId}
            </span>
          </button>
        )}
      </td>
      <td className="sc-num">{t('schedules.row.runs', { count: schedule.run_count })}</td>
    </tr>
  );
}

export default function SchedulePage() {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');
  const currentScheduleId = usePageStore((s) => s.currentScheduleId);
  const switchPage = usePageStore((s) => s.switchPage);

  const [localView, setLocalView] = useState<ScheduleView | null>(null);
  useEffect(() => {
    setLocalView(null);
  }, [currentScheduleId]);

  const activeView = useMemo(
    () => localView ?? parseScheduleRoute(currentScheduleId),
    [localView, currentScheduleId]
  );

  const [body, setBody] = useState<ScheduleListResponse | null>(null);
  const [employees, setEmployees] = useState<EmployeeItem[]>([]);
  const [employeesLoaded, setEmployeesLoaded] = useState(false);
  const [recipes, setRecipes] = useState<RecipeItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<ScheduleFilter>('all');
  const [search, setSearch] = useState('');

  const [busy, setBusy] = useState<'run' | 'toggle' | 'remove' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [restartingScheduler, setRestartingScheduler] = useState(false);

  const { refresh } = useAutoRefresh(
    async () => {
      setRefreshing(true);
      try {
        const apiKeys = new Set(Object.keys(api));
        const hasEmployeesApi = apiKeys.has('getEmployees') && typeof api.getEmployees === 'function';
        const hasRecipesApi = apiKeys.has('getRecipes') && typeof api.getRecipes === 'function';
        const [schedulesRes, empList, recipeList] = await Promise.all([
          api.getSchedules(),
          hasEmployeesApi ? api.getEmployees().catch(() => null) : Promise.resolve(null),
          hasRecipesApi ? api.getRecipes().catch(() => []) : Promise.resolve([]),
        ]);
        setBody(schedulesRes);
        if (Array.isArray(empList)) {
          setEmployees(empList);
          setEmployeesLoaded(true);
        }
        if (Array.isArray(recipeList)) {
          setRecipes(recipeList);
        }
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRefreshing(false);
      }
    },
    { intervalMs: REFRESH_MS }
  );

  const schedules = useMemo(() => body?.schedules ?? [], [body]);

  const employeeById = useMemo(() => {
    const map = new Map<string, EmployeeItem>();
    for (const emp of employees) {
      map.set(emp.member_post_id, emp);
    }
    return map;
  }, [employees]);

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
      return [
        s.name,
        s.id,
        s.employee_id ?? '',
        s.employee_title ?? '',
        targetText(s),
        s.cron ?? '',
        s.notify?.to ?? '',
      ]
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [schedules, filter, search]);

  const allDisabled = schedules.length > 0 && counts.enabled === 0;
  const now = new Date();

  const selected = activeView.id
    ? schedules.find((s) => s.id === activeView.id) ?? null
    : null;
  const missing =
    (activeView.mode === 'detail' || activeView.mode === 'edit') &&
    Boolean(activeView.id) &&
    body !== null &&
    selected === null;

  const goList = () => {
    setLocalView({ mode: 'list', id: null });
    switchPage('schedules');
  };

  const goNew = () => {
    setLocalView({ mode: 'new', id: null });
    switchPage('schedule_detail', 'new');
  };

  const goEdit = (id: string) => {
    setLocalView({ mode: 'edit', id });
    switchPage('schedule_detail', `edit/${id}`);
  };

  const goDetail = (id: string) => {
    setLocalView({ mode: 'detail', id });
    switchPage('schedule_detail', `detail/${id}`);
  };

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
      window.setTimeout(() => void refresh(), RUN_FOLLOWUP_MS);
    });

  const toggle = (s: ScheduleItem) => act('toggle', () => api.toggleSchedule(s.id));

  const remove = (s: ScheduleItem) =>
    act('remove', async () => {
      await api.removeSchedule(s.id);
      goList();
    });

  const enableAllSchedules = () =>
    act('toggle', async () => {
      const disabled = schedules.filter((s) => !s.enabled);
      for (const s of disabled) {
        await api.toggleSchedule(s.id);
      }
      if (body && !body.scheduler_running) {
        await restartServer().catch(() => {});
      }
      setActionNotice(
        t('schedules.actions.enabledAllNotice', {
          defaultValue: isZh ? '已启用全部定时任务' : 'Enabled all schedules',
        })
      );
    });

  const restartScheduler = async () => {
    if (restartingScheduler) return;
    setRestartingScheduler(true);
    setActionError(null);
    try {
      await restartServer();
      setActionNotice(
        t('schedules.actions.restartedNotice', {
          defaultValue: isZh ? '已触发调度器重启' : 'Scheduler restart triggered',
        })
      );
      window.setTimeout(() => void refresh(), RUN_FOLLOWUP_MS);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setRestartingScheduler(false);
    }
  };

  const headerMeta = body
    ? counts.failing > 0
      ? t('schedules.headerMetaFailing', {
          count: schedules.length,
          enabled: counts.enabled,
          failing: counts.failing,
        })
      : t('schedules.headerMeta', {
          count: schedules.length,
          enabled: counts.enabled,
        })
    : undefined;

  const isWorkspace = activeView.mode !== 'list';

  return (
    <div className="td-page tdp sc-page">
      <PageHeader
        title={t('schedules.title')}
        meta={headerMeta}
        secondary={
          <>
            <div className="ui-seg-group" role="tablist" aria-label={t('schedules.title')}>
              <button
                type="button"
                role="tab"
                aria-selected={activeView.mode === 'list'}
                className={`ui-seg-pill ${activeView.mode === 'list' ? 'ui-seg-pill--active' : ''}`}
                onClick={goList}
                data-testid="sc-tab-list"
              >
                {t('schedules.views.list')}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeView.mode === 'new' || activeView.mode === 'edit'}
                className={`ui-seg-pill ${
                  activeView.mode === 'new' || activeView.mode === 'edit'
                    ? 'ui-seg-pill--active'
                    : ''
                }`}
                onClick={() => {
                  if (activeView.mode === 'detail' && selected) {
                    goEdit(selected.id);
                  } else {
                    goNew();
                  }
                }}
                data-testid="sc-tab-edit"
              >
                {t('schedules.views.edit')}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeView.mode === 'detail'}
                disabled={!selected && schedules.length === 0}
                className={`ui-seg-pill ${activeView.mode === 'detail' ? 'ui-seg-pill--active' : ''}`}
                onClick={() => {
                  const targetId = selected?.id ?? schedules[0]?.id;
                  if (targetId) goDetail(targetId);
                }}
                data-testid="sc-tab-detail"
              >
                {t('schedules.views.detail')}
              </button>
            </div>
            <button
              type="button"
              className="page-header-btn page-header-btn--icon page-header-btn--ghost"
              onClick={refresh}
              disabled={refreshing}
              title={t('common.refresh')}
              aria-label={t('common.refresh')}
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            </button>
          </>
        }
        primary={{
          label: t('schedules.views.newBtn'),
          icon: activeView.mode === 'new' ? <X size={14} /> : <Plus size={14} />,
          onClick: () => (activeView.mode === 'new' ? goList() : goNew()),
          pressed: activeView.mode === 'new',
        }}
      />

      {allDisabled ? (
        <div className="sc-banner" role="status">
          <CirclePause size={16} aria-hidden="true" />
          <span className="flex-1">
            <b>{t('schedules.allDisabled.title', { count: schedules.length })}</b>{' '}
            {t('schedules.allDisabled.body')}
          </span>
          <button
            type="button"
            className="fix-btn warn"
            onClick={() => void enableAllSchedules()}
            disabled={busy !== null}
            data-testid="schedules-enable-all"
          >
            {t('schedules.actions.enableAndStart', {
              defaultValue: isZh ? '启用并启动' : 'Enable & Start',
            })}
          </button>
        </div>
      ) : (
        body &&
        !body.scheduler_running && (
          <div className="sc-banner" role="status">
            <TriangleAlert size={16} aria-hidden="true" />
            <span className="flex-1">{t('schedules.schedulerStopped')}</span>
            <button
              type="button"
              className="fix-btn warn"
              onClick={() => void restartScheduler()}
              disabled={busy !== null || restartingScheduler}
              data-testid="schedules-restart-scheduler"
            >
              {t('schedules.actions.restartScheduler', {
                defaultValue: isZh ? '重启调度器' : 'Restart Scheduler',
              })}
            </button>
          </div>
        )
      )}

      {actionNotice && (
        <div className="alert-box-pri mx-4 mb-2 items-center" role="status">
          <Check size={14} className="shrink-0" />
          <span className="flex-1 text-[var(--text-primary)]">{actionNotice}</span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setActionNotice(null)}
          >
            {t('common.dismiss', { defaultValue: isZh ? '知道了' : 'Dismiss' })}
          </button>
        </div>
      )}

      {error && <div className="td-error">{t('schedules.loadFailed', { message: error })}</div>}
      {actionError && (
        <div className="td-error">{t('schedules.actions.failed', { message: actionError })}</div>
      )}
      {missing && <div className="td-error">{t('schedules.notFound', { id: activeView.id })}</div>}

      {!isWorkspace ? (
        <>
          <div className="td-toolbar tdp-toolbar">
            <div className="ui-seg-group tdp-seg-group" role="group" aria-label={t('schedules.detail.status')}>
              {FILTERS.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={`ui-seg-pill ${filter === name ? 'ui-seg-pill--active' : ''}`}
                  onClick={() => setFilter(name)}
                  aria-pressed={filter === name}
                >
                  {t(`schedules.filter.${name}`)}
                  <span className="ui-seg-count">{counts[name]}</span>
                </button>
              ))}
            </div>
            <div className="ui-search-box td-search">
              <Search size={16} className="ui-search-box-icon" />
              <input
                type="text"
                placeholder={t('schedules.searchPlaceholder')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label={t('schedules.searchPlaceholder')}
              />
              {search && (
                <button
                  type="button"
                  className="ui-search-box-clear"
                  onClick={() => setSearch('')}
                  aria-label={t('common.clear')}
                >
                  <X size={14} />
                </button>
              )}
            </div>
          </div>

          <div className="td-split">
            <div className="td-list-pane sc-list-pane">
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
                <table className="sc-table">
                  <colgroup>
                    <col />
                    <col className="sc-col-when" />
                    <col className="sc-col-last" />
                    <col className="sc-col-runs" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th scope="col">{t('schedules.table.schedule')}</th>
                      <th scope="col">{t('schedules.table.when')}</th>
                      <th scope="col">{t('schedules.table.lastRun')}</th>
                      <th scope="col" className="sc-num">
                        {t('schedules.table.runs')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((s) => (
                      <ScheduleRow
                        key={s.id}
                        schedule={s}
                        employee={s.employee_id ? employeeById.get(s.employee_id) : undefined}
                        employeesLoaded={employeesLoaded}
                        selected={s.id === activeView.id}
                        now={now}
                        busy={busy !== null}
                        onRunNow={() => void runNow(s)}
                        onClick={() => goDetail(s.id)}
                      />
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="sc-ws" data-testid="sc-workspace">
          <aside className="sc-list-pane" data-testid="sc-sidebar-list">
            <div className="sc-list-head">
              <h2>{t('schedules.views.sidebarTitle', { count: schedules.length })}</h2>
              <button
                type="button"
                className="sc-btn sm"
                onClick={goNew}
                data-testid="sc-sidebar-new-btn"
              >
                <Plus size={11} />
                {t('schedules.views.newBtn')}
              </button>
            </div>
            <div className="sc-list-items">
              {schedules.map((s) => {
                const st = stateOf(s);
                const emp = s.employee_id ? employeeById.get(s.employee_id) : undefined;
                const empColor = empColorToken(s.employee_id, emp?.color);
                const isSel = activeView.mode !== 'new' && s.id === activeView.id;
                const dotClass =
                  st === 'failing' ? 'd-err' : s.enabled ? 'd-run' : 'd-idle';
                return (
                  <button
                    key={s.id}
                    type="button"
                    className={`sc-card ${isSel ? 'sel' : ''}`}
                    onClick={() => goDetail(s.id)}
                    data-testid={`sc-sidebar-item-${s.id}`}
                  >
                    <div className="sc-card-top">
                      <span className={`sc-dot ${dotClass}`} />
                      <span className="sc-card-name">{s.name}</span>
                    </div>
                    <div className="sc-card-meta">
                      {s.kind === 'employee' ? (
                        <span className="sc-chip emp" data-emp-color={empColor}>
                          @{s.employee_id || '—'}
                        </span>
                      ) : (
                        <span className="sc-chip">{t(`schedules.kind.${s.kind}`)}</span>
                      )}
                      <span>{frequencyText(s, t)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </aside>

          {activeView.mode === 'new' && (
            <ScheduleEditPane
              key="create"
              schedule={null}
              employees={employees}
              recipes={recipes}
              onSaved={(saved) => {
                void refresh();
                goDetail(saved.id);
              }}
              onCancel={goList}
              onNlComposed={async (id) => {
                await refresh();
                if (id) goDetail(id);
              }}
            />
          )}

          {activeView.mode === 'edit' && selected && (
            <ScheduleEditPane
              key={`edit-${selected.id}`}
              schedule={selected}
              employees={employees}
              recipes={recipes}
              onSaved={(saved) => {
                void refresh();
                goDetail(saved.id);
              }}
              onCancel={() => goDetail(selected.id)}
              onPreviewDetail={() => goDetail(selected.id)}
            />
          )}

          {activeView.mode === 'detail' && selected && (
            <ScheduleDetail
              key={`detail-${selected.id}`}
              variant="workspace"
              schedule={selected}
              employee={
                selected.employee_id
                  ? employeeById.get(selected.employee_id) ??
                    (employeesLoaded ? null : undefined)
                  : undefined
              }
              busy={busy}
              onRun={() => void runNow(selected)}
              onToggle={() => void toggle(selected)}
              onRemove={() => void remove(selected)}
              onEdit={() => goEdit(selected.id)}
              onClose={goList}
            />
          )}

          {(activeView.mode === 'edit' || activeView.mode === 'detail') && !selected && (
            <div className="sc-work-pane">
              <div className="sc-work-in">
                <div className={missing ? 'sc-notice warn' : 'sc-notice'}>
                  {missing ? t('schedules.notFound', { id: activeView.id }) : t('common.loading')}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
