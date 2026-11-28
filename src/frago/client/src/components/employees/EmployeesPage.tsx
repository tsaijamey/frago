/**
 * 员工页 —— 上区 3D 扑克牌选卡舞台 + 下区选中员工名下全部会话的双区驾驶舱。
 *
 * - 页头仅承载页面级动作：状态筛选（全部 / 运行中 / 待命）+ 刷新 + 中性描边「+ 新建员工」。
 * - 全屏唯一一颗实心品牌绿主动作按钮固定在下方选中员工上下文头栏的「+ 新建会话」。
 * - 点击非居中卡片切换选中并实时加载名下全部会话；点击任意会话（含 24 小时前历史会话）
 *   同步将其纳入左栏可见集合并直达 `#/sessions/<id>`。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Briefcase, Loader2, Plus, RefreshCw } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import { usePageStore } from '@/stores/pageStore';
import { useEmployeeList, type EmployeePost } from '@/hooks/useEmployees';
import {
  useEmployeeSessions,
  type EmployeeSessionFilter,
} from '@/hooks/useEmployeeSessions';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmployeeCardDeck from './EmployeeCardDeck';
import EmployeeSessionsPanel from './EmployeeSessionsPanel';
import LaunchEmployeeDialog from './LaunchEmployeeDialog';
import EmployeeDetailDialog from './EmployeeDetailDialog';
import EmployeeAvatarModal from './EmployeeAvatarModal';

const REFRESH_MS = 30_000;

type EmployeeStatusFilter = 'all' | 'running' | 'standby';

function employeeActiveCount(post: EmployeePost): number {
  return post.session_counts?.active ?? post.active_session_ids?.length ?? 0;
}

export default function EmployeesPage() {
  const { t } = useTranslation();
  const switchPage = usePageStore((s) => s.switchPage);
  const promoteSessionToToday = usePageStore((s) => s.promoteSessionToToday);
  const launchWorkbenchSession = usePageStore((s) => s.launchWorkbenchSession);

  const { employees, loading, error, reload: reloadEmployees } = useEmployeeList(true);

  const [empFilter, setEmpFilter] = useState<EmployeeStatusFilter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sessionFilter, setSessionFilter] = useState<EmployeeSessionFilter>('all');

  const [launchFor, setLaunchFor] = useState<EmployeePost | null>(null);
  const [detailFor, setDetailFor] = useState<EmployeePost | null>(null);
  const [avatarFor, setAvatarFor] = useState<EmployeePost | null>(null);
  const [creating, setCreating] = useState(false);

  const firstEnterButtonRef = useRef<HTMLButtonElement>(null);

  const runningCount = useMemo(
    () => employees.filter((e) => employeeActiveCount(e) > 0).length,
    [employees]
  );
  const standbyCount = Math.max(0, employees.length - runningCount);

  const filteredEmployees = useMemo(() => {
    if (empFilter === 'running') {
      return employees.filter((e) => employeeActiveCount(e) > 0);
    }
    if (empFilter === 'standby') {
      return employees.filter((e) => employeeActiveCount(e) === 0);
    }
    return employees;
  }, [employees, empFilter]);

  useEffect(() => {
    if (!filteredEmployees.length) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !filteredEmployees.some((e) => e.member_post_id === selectedId)) {
      setSelectedId(filteredEmployees[0].member_post_id);
      setSessionFilter('all');
    }
  }, [filteredEmployees, selectedId]);

  const selectedEmployee = useMemo(
    () =>
      filteredEmployees.find((e) => e.member_post_id === selectedId) ??
      filteredEmployees[0] ??
      null,
    [filteredEmployees, selectedId]
  );

  const sessionsState = useEmployeeSessions(
    selectedEmployee?.member_post_id ?? null,
    sessionFilter
  );

  const reloadAll = useCallback(() => {
    reloadEmployees();
    sessionsState.reload();
  }, [reloadEmployees, sessionsState]);

  useAutoRefresh(reloadAll, { intervalMs: REFRESH_MS });

  const handleSelectEmployee = useCallback((memberPostId: string) => {
    setSelectedId(memberPostId);
    setSessionFilter('all');
  }, []);

  const handleOpenSession = useCallback(
    (sessionId: string) => {
      promoteSessionToToday(sessionId);
      switchPage('session_workbench', sessionId);
    },
    [promoteSessionToToday, switchPage]
  );

  const handleActivateCenter = useCallback(() => {
    firstEnterButtonRef.current?.focus();
  }, []);

  const modalOpen = launchFor !== null || detailFor !== null || avatarFor !== null || creating;

  return (
    <div className="flex min-h-0 flex-1 flex-col emp-page-header">
      <PageHeader
        title={t('employees.page.title')}
        meta={
          loading && !employees.length
            ? undefined
            : runningCount > 0
              ? t('employees.page.countWithRunning', {
                  n: employees.length,
                  running: runningCount,
                })
              : t('employees.page.count', { n: employees.length })
        }
        secondary={
          <>
            {employees.length > 0 ? (
              <div
                className="emp-seg"
                role="group"
                aria-label={t('employees.page.filterAria')}
                data-testid="employees-status-filter"
              >
                <button
                  type="button"
                  className={`emp-seg-btn ${empFilter === 'all' ? 'on' : ''}`}
                  data-testid="employees-filter-all"
                  onClick={() => setEmpFilter('all')}
                >
                  {t('employees.page.filterAll', { n: employees.length })}
                </button>
                <button
                  type="button"
                  className={`emp-seg-btn ${empFilter === 'running' ? 'on' : ''}`}
                  data-testid="employees-filter-running"
                  onClick={() => setEmpFilter('running')}
                >
                  {t('employees.page.filterRunning', { n: runningCount })}
                </button>
                <button
                  type="button"
                  className={`emp-seg-btn ${empFilter === 'standby' ? 'on' : ''}`}
                  data-testid="employees-filter-standby"
                  onClick={() => setEmpFilter('standby')}
                >
                  {t('employees.page.filterStandby', { n: standbyCount })}
                </button>
              </div>
            ) : null}

            <button
              type="button"
              className="page-header-btn page-header-btn--icon"
              onClick={reloadAll}
              title={t('common.refresh')}
              aria-label={t('common.refresh')}
              data-testid="employees-refresh-btn"
            >
              <RefreshCw size={14} strokeWidth={1.5} />
            </button>

            <button
              type="button"
              className="page-header-btn"
              onClick={() => setCreating(true)}
              data-testid="new-employee-btn"
            >
              <Plus size={14} strokeWidth={1.5} />
              {t('employees.page.new')}
            </button>
          </>
        }
      />

      {error ? (
        <div
          className="mx-5 mt-3 break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-[12px] text-accent-error"
          data-testid="employees-error-banner"
        >
          {t('employees.page.loadFailed', { reason: error })}
        </div>
      ) : null}

      <div className="emp-workspace">
        {loading && !employees.length && !error ? (
          <p className="flex items-center gap-2 px-5 py-4 text-[13px] text-text-muted">
            <Loader2 size={14} className="cs-spin" />
            {t('common.loading')}
          </p>
        ) : !employees.length && !error ? (
          <div className="page-scroll">
            <EmptyState
              Icon={Briefcase}
              title={t('employees.page.empty')}
              description={t('employees.page.emptyDesc')}
            />
          </div>
        ) : !filteredEmployees.length ? (
          <div className="page-scroll">
            <EmptyState
              Icon={Briefcase}
              title={t('employees.page.emptyFiltered')}
              description={t('employees.page.emptyFilteredDesc')}
            />
          </div>
        ) : (
          <>
            <EmployeeCardDeck
              employees={filteredEmployees}
              activeId={selectedEmployee?.member_post_id ?? null}
              onSelect={handleSelectEmployee}
              onActivateCenter={handleActivateCenter}
              onChangeAvatar={(post) => setAvatarFor(post)}
              modalOpen={modalOpen}
            />

            <EmployeeSessionsPanel
              employee={selectedEmployee}
              sessions={sessionsState.sessions}
              total={sessionsState.total}
              activeCount={sessionsState.activeCount}
              completedCount={sessionsState.completedCount}
              hasMore={sessionsState.hasMore}
              filter={sessionFilter}
              onFilterChange={setSessionFilter}
              loading={sessionsState.loading}
              loadingMore={sessionsState.loadingMore}
              error={sessionsState.error}
              onRetry={sessionsState.reload}
              onLoadMore={sessionsState.loadMore}
              onEditEmployee={(post) => setDetailFor(post)}
              onChangeAvatar={(post) => setAvatarFor(post)}
              onLaunchSession={(post) => setLaunchFor(post)}
              onOpenSession={handleOpenSession}
              firstEnterButtonRef={firstEnterButtonRef}
            />
          </>
        )}
      </div>

      <LaunchEmployeeDialog
        post={launchFor}
        onClose={() => setLaunchFor(null)}
        onCreated={(launch, text) => {
          launchWorkbenchSession(launch, text);
        }}
      />

      <EmployeeDetailDialog
        post={detailFor}
        creating={creating}
        onClose={() => {
          setDetailFor(null);
          setCreating(false);
        }}
        onSaved={reloadAll}
        onChangeAvatar={(post) => setAvatarFor(post)}
        onCreated={(created) => {
          setCreating(false);
          setDetailFor(created);
          setEmpFilter('all');
          setSelectedId(created.member_post_id);
        }}
      />

      <EmployeeAvatarModal
        employee={avatarFor}
        onClose={() => setAvatarFor(null)}
        onSaved={() => {
          reloadAll();
        }}
      />
    </div>
  );
}
