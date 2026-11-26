import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Info,
  Loader2,
  Sparkles,
  TriangleAlert,
  UserCheck,
} from 'lucide-react';
import * as api from '@/api';
import type {
  ScheduleComposeResponse,
  ScheduleItem,
  SchedulePreviewRun,
  ScheduleWritePayload,
} from '@/api';
import type { EmployeeItem } from '@/types/api';
import type { RecipeItem } from '@/types/pywebview';
import ScheduleEmployeePicker from './ScheduleEmployeePicker';
import {
  DEFAULT_EMPLOYEE_TITLE_TEMPLATE,
  TEMPLATE_VARIABLES,
  cronText,
  empColorToken,
  employeeInitials,
  renderTitleTemplatePreview,
} from './scheduleMeta';

type ScheduleKind = 'employee' | 'recipe' | 'command' | 'prompt';

interface ScheduleEditPaneProps {
  /** null 表示新建模式；非 null 表示编辑已有定时任务 */
  schedule: ScheduleItem | null;
  employees: EmployeeItem[];
  recipes: RecipeItem[];
  onSaved: (saved: ScheduleItem) => void;
  onCancel: () => void;
  onPreviewDetail?: () => void;
  onNlComposed?: (scheduleId: string | null) => Promise<void> | void;
}

export default function ScheduleEditPane({
  schedule,
  employees,
  recipes,
  onSaved,
  onCancel,
  onPreviewDetail,
  onNlComposed,
}: ScheduleEditPaneProps) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');
  const isEdit = schedule !== null;

  const [name, setName] = useState(schedule?.name ?? '');
  const [kind, setKind] = useState<ScheduleKind>(
    (schedule?.kind as ScheduleKind) || 'employee'
  );
  const [triggerMode, setTriggerMode] = useState<'cron' | 'interval'>(
    schedule?.interval_seconds && !schedule?.cron ? 'interval' : 'cron'
  );
  const [cron, setCron] = useState(
    schedule?.cron ?? (schedule?.interval_seconds ? '' : '0 9 * * 1-5')
  );
  const [intervalSeconds, setIntervalSeconds] = useState(
    schedule?.interval_seconds ? String(schedule.interval_seconds) : '3600'
  );
  const [timeoutMin, setTimeoutMin] = useState(
    schedule?.timeout ? String(Math.max(1, Math.round(schedule.timeout / 60))) : '120'
  );
  const [notifyOn, setNotifyOn] = useState(schedule?.notify?.on ?? 'change');
  const [notifyTo, setNotifyTo] = useState(schedule?.notify?.to ?? '');
  const [enabled, setEnabled] = useState(schedule ? schedule.enabled : true);

  // Employee binding state
  const [employeeId, setEmployeeId] = useState(
    schedule?.employee_id ?? (employees[0]?.member_post_id ?? '')
  );
  const [pickerOpen, setPickerOpen] = useState(
    !schedule || !schedule.employee_id || Boolean(schedule.employee_missing)
  );
  const [empPrompt, setEmpPrompt] = useState(
    schedule?.kind === 'employee' ? schedule.prompt ?? '' : ''
  );

  // Recipe / Command / Prompt primitive states
  const [recipeName, setRecipeName] = useState(
    schedule?.recipe ?? recipes[0]?.name ?? ''
  );
  const [recipeParams, setRecipeParams] = useState(() =>
    schedule?.params && Object.keys(schedule.params).length > 0
      ? JSON.stringify(schedule.params, null, 2)
      : '{}'
  );
  const [commandText, setCommandText] = useState(schedule?.command ?? '');
  const [cwd, setCwd] = useState(schedule?.cwd ?? '');
  const [promptText, setPromptText] = useState(
    schedule?.kind === 'prompt' ? schedule.prompt ?? '' : ''
  );
  const [allowedToolsText, setAllowedToolsText] = useState(
    (schedule?.allowed_tools ?? []).join(', ')
  );

  // Dynamic session title template & preview
  const [titleTemplate, setTitleTemplate] = useState(
    schedule?.session_title_template || DEFAULT_EMPLOYEE_TITLE_TEMPLATE
  );
  const [remotePreviewRuns, setRemotePreviewRuns] = useState<SchedulePreviewRun[] | null>(
    null
  );

  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Optional NL 1-sentence composer toggle inside create view
  const [nlOpen, setNlOpen] = useState(false);
  const [nlDraft, setNlDraft] = useState('');
  const [nlBusy, setNlBusy] = useState(false);
  const [nlError, setNlError] = useState<string | null>(null);
  const [nlResult, setNlResult] = useState<ScheduleComposeResponse | null>(null);

  // Sync default employee / recipe when async lists load in create mode
  useEffect(() => {
    if (!schedule && kind === 'employee' && !employeeId && employees.length > 0) {
      setEmployeeId(employees[0].member_post_id);
    }
  }, [employees, employeeId, kind, schedule]);

  useEffect(() => {
    if (!schedule && !recipeName && recipes.length > 0) {
      setRecipeName(recipes[0].name);
    }
  }, [recipes, recipeName, schedule]);

  const selectedEmployee = useMemo(
    () => employees.find((e) => e.member_post_id === employeeId) ?? null,
    [employees, employeeId]
  );
  const isEmployeeMissing =
    kind === 'employee' &&
    Boolean(employeeId) &&
    (Boolean(schedule?.employee_missing && schedule.employee_id === employeeId) ||
      (employees.length > 0 && !selectedEmployee));

  const cronHuman = useMemo(
    () => (triggerMode === 'cron' && cron.trim() ? cronText(cron, t) : null),
    [triggerMode, cron, t]
  );

  const localPreviewRuns = useMemo(() => {
    const empLabel = selectedEmployee?.member_post_id || employeeId || 'employee';
    return renderTitleTemplatePreview({
      template: titleTemplate,
      scheduleName: name.trim() || (isZh ? '未命名任务' : 'untitled'),
      employeeLabel: kind === 'employee' ? empLabel : 'coreagent',
      cron: triggerMode === 'cron' ? cron.trim() || '0 9 * * 1-5' : null,
      intervalSeconds:
        triggerMode === 'interval' ? Number(intervalSeconds) || 3600 : null,
      runCount: schedule?.run_count ?? 0,
      count: 3,
      isZh,
    });
  }, [
    titleTemplate,
    name,
    selectedEmployee,
    employeeId,
    kind,
    triggerMode,
    cron,
    intervalSeconds,
    schedule?.run_count,
    isZh,
  ]);

  useEffect(() => {
    if (kind !== 'employee' && kind !== 'prompt') {
      setRemotePreviewRuns(null);
      return;
    }
    if (
      !Object.keys(api).includes('previewScheduleRuns') ||
      typeof api.previewScheduleRuns !== 'function'
    ) {
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void api
        .previewScheduleRuns({
          name: name.trim() || 'untitled',
          kind,
          employee_id: kind === 'employee' ? employeeId || null : null,
          session_title_template: titleTemplate.trim() || null,
          cron: triggerMode === 'cron' ? cron.trim() || null : null,
          interval_seconds:
            triggerMode === 'interval' ? Number(intervalSeconds) || null : null,
          run_count: schedule?.run_count ?? 0,
          count: 3,
        })
        .then((res) => {
          if (!cancelled && Array.isArray(res?.runs) && res.runs.length > 0) {
            setRemotePreviewRuns(res.runs);
          }
        })
        .catch(() => {
          if (!cancelled) setRemotePreviewRuns(null);
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    kind,
    name,
    employeeId,
    titleTemplate,
    triggerMode,
    cron,
    intervalSeconds,
    schedule?.run_count,
  ]);

  const previewRuns = remotePreviewRuns ?? localPreviewRuns;

  const insertTemplateVar = (token: string) => {
    setTitleTemplate((prev) => {
      const trimmed = prev.trimEnd();
      if (!trimmed) return token;
      return `${trimmed} ${token}`;
    });
  };

  const handleSave = async () => {
    if (saving) return;
    setFormError(null);

    const cleanName = name.trim();
    if (!cleanName) {
      setFormError(t('schedules.form.errNameRequired'));
      return;
    }

    const minutes = Number(timeoutMin);
    if (!Number.isFinite(minutes) || minutes < 1) {
      setFormError(t('schedules.form.errTimeoutInvalid'));
      return;
    }

    let cronVal: string | null = null;
    let intervalVal: number | null = null;
    if (triggerMode === 'cron') {
      cronVal = cron.trim();
      if (!cronVal) {
        setFormError(t('schedules.form.errCronRequired'));
        return;
      }
    } else {
      const sec = Number(intervalSeconds);
      if (!Number.isInteger(sec) || sec <= 0) {
        setFormError(t('schedules.form.errIntervalInvalid'));
        return;
      }
      intervalVal = sec;
    }

    let parsedParams: Record<string, unknown> = {};
    if (kind === 'recipe') {
      if (!recipeName.trim()) {
        setFormError(t('schedules.form.errRecipeRequired'));
        return;
      }
      const rawParams = recipeParams.trim();
      if (rawParams) {
        try {
          const obj = JSON.parse(rawParams);
          if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
            setFormError(t('schedules.form.errParamsJson'));
            return;
          }
          parsedParams = obj as Record<string, unknown>;
        } catch {
          setFormError(t('schedules.form.errParamsJson'));
          return;
        }
      }
    }

    if (kind === 'employee' && (!employeeId.trim() || isEmployeeMissing)) {
      setFormError(t('schedules.form.errEmpRequired'));
      return;
    }
    if (kind === 'command' && !commandText.trim()) {
      setFormError(t('schedules.form.errCommandRequired'));
      return;
    }
    if (kind === 'prompt' && !promptText.trim()) {
      setFormError(t('schedules.form.errPromptRequired'));
      return;
    }

    const allowedTools = allowedToolsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    const payload: ScheduleWritePayload = {
      name: cleanName,
      kind,
      employee_id: kind === 'employee' ? employeeId.trim() : null,
      session_title_template:
        kind === 'employee' || kind === 'prompt'
          ? titleTemplate.trim() || DEFAULT_EMPLOYEE_TITLE_TEMPLATE
          : null,
      prompt:
        kind === 'employee'
          ? empPrompt.trim() || null
          : kind === 'prompt'
            ? promptText.trim()
            : null,
      recipe: kind === 'recipe' ? recipeName.trim() : null,
      command: kind === 'command' ? commandText.trim() : null,
      cwd: kind === 'command' || kind === 'prompt' ? cwd.trim() || null : null,
      instructions: schedule?.instructions ?? null,
      allowed_tools: kind === 'prompt' ? allowedTools : [],
      disallowed_tools: schedule?.disallowed_tools ?? [],
      params: kind === 'recipe' ? parsedParams : {},
      cron: cronVal,
      interval_seconds: intervalVal,
      overlap: schedule?.overlap ?? 'skip',
      timeout: Math.round(minutes * 60),
      start_at: schedule?.start_at ?? null,
      end_at: schedule?.end_at ?? null,
      notify: {
        on: notifyOn,
        to: notifyOn === 'never' ? null : notifyTo.trim() || null,
        context: schedule?.notify?.context ?? {},
      },
      enabled,
    };

    setSaving(true);
    try {
      const saved = isEdit
        ? await api.updateSchedule(schedule.id, payload)
        : await api.createSchedule(payload);
      onSaved(saved);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleNlCompose = async () => {
    const text = nlDraft.trim();
    if (!text || nlBusy) return;
    setNlBusy(true);
    setNlError(null);
    setNlResult(null);
    try {
      const res = await api.composeSchedule(text);
      setNlResult(res);
      setNlDraft('');
      await onNlComposed?.(res.schedule_id);
    } catch (e) {
      setNlError(e instanceof Error ? e.message : String(e));
    } finally {
      setNlBusy(false);
    }
  };

  const empDisplayTitle =
    selectedEmployee?.title ||
    (schedule?.employee_id === employeeId ? schedule?.employee_title : null) ||
    employeeId;
  const empDisplayKernel =
    selectedEmployee?.agent_kernel ||
    (schedule?.employee_id === employeeId ? schedule?.employee_kernel : null) ||
    'claude';
  const empDisplayCwd =
    selectedEmployee?.cwd ||
    (schedule?.employee_id === employeeId ? schedule?.employee_cwd : null);
  const empColor = empColorToken(employeeId, selectedEmployee?.color);

  return (
    <div className="sc-work-pane" data-testid="sc-edit-pane">
      <div className="sc-work-in">
        {!isEdit && (
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              className="sc-btn sm"
              onClick={() => setNlOpen((v) => !v)}
              data-testid="sc-nl-compose-toggle"
            >
              <Sparkles size={12} />
              {t('schedules.views.nlComposeToggle')}
            </button>
          </div>
        )}

        {nlOpen && !isEdit && (
          <div className="td-composer m-0" data-testid="sc-nl-composer">
            <textarea
              className="td-composer-input"
              rows={3}
              value={nlDraft}
              onChange={(e) => setNlDraft(e.target.value)}
              placeholder={t('schedules.compose.placeholder')}
              disabled={nlBusy}
            />
            <div className="td-composer-foot">
              <span className="td-composer-hint">{t('schedules.compose.hint')}</span>
              <button
                type="button"
                className="td-composer-submit"
                onClick={() => void handleNlCompose()}
                disabled={nlBusy || nlDraft.trim() === ''}
              >
                {nlBusy && <Loader2 size={14} className="animate-spin" />}
                {nlBusy ? t('schedules.compose.working') : t('schedules.compose.submit')}
              </button>
            </div>
            {nlError && (
              <div className="td-error">{t('schedules.compose.failed', { message: nlError })}</div>
            )}
            {nlResult && (
              <div className="td-composer-result">
                <p className="td-composer-verdict">
                  {nlResult.schedule_id
                    ? t('schedules.compose.created', { id: nlResult.schedule_id })
                    : t('schedules.compose.nothingCreated')}
                </p>
                {nlResult.message && <p className="td-composer-message">{nlResult.message}</p>}
              </div>
            )}
          </div>
        )}

        {/* 1. 任务基础与触发节奏 */}
        <section className="sc-sec-card">
          <div className="sc-sec-hd">
            <h3>{t('schedules.form.sec1Title')}</h3>
            <span className="sub">{t('schedules.form.sec1Sub')}</span>
          </div>
          <div className="sc-sec-bd">
            <div className="sc-form-grid">
              <div className="sc-field">
                <label htmlFor="sc-inp-name">{t('schedules.form.nameLabel')}</label>
                <input
                  id="sc-inp-name"
                  type="text"
                  className="sc-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('schedules.form.namePlaceholder')}
                  data-testid="sc-inp-name"
                />
              </div>

              <div className="sc-field">
                <label htmlFor="sc-inp-trigger-mode">
                  {t('schedules.form.triggerMode')}
                  <span className="hint">
                    {triggerMode === 'cron'
                      ? cronHuman ?? t('schedules.form.cronUnrecognized')
                      : t('schedules.freq.seconds', { count: Number(intervalSeconds) || 0 })}
                  </span>
                </label>
                <div className="flex gap-2">
                  <select
                    id="sc-inp-trigger-mode"
                    className="sc-select w-[140px] shrink-0"
                    value={triggerMode}
                    onChange={(e) => setTriggerMode(e.target.value as 'cron' | 'interval')}
                    data-testid="sc-select-trigger-mode"
                  >
                    <option value="cron">{t('schedules.form.triggerCron')}</option>
                    <option value="interval">{t('schedules.form.triggerInterval')}</option>
                  </select>
                  {triggerMode === 'cron' ? (
                    <input
                      type="text"
                      className="sc-input font-mono"
                      value={cron}
                      onChange={(e) => setCron(e.target.value)}
                      aria-label={t('schedules.form.cronLabel')}
                      data-testid="sc-inp-cron"
                    />
                  ) : (
                    <input
                      type="number"
                      min={1}
                      className="sc-input font-mono"
                      value={intervalSeconds}
                      onChange={(e) => setIntervalSeconds(e.target.value)}
                      aria-label={t('schedules.form.intervalLabel')}
                      data-testid="sc-inp-interval"
                    />
                  )}
                </div>
              </div>

              <div className="sc-field">
                <label htmlFor="sc-inp-timeout">{t('schedules.form.timeoutLabel')}</label>
                <input
                  id="sc-inp-timeout"
                  type="number"
                  min={1}
                  className="sc-input"
                  value={timeoutMin}
                  onChange={(e) => setTimeoutMin(e.target.value)}
                  data-testid="sc-inp-timeout"
                />
              </div>

              <div className="sc-field">
                <label htmlFor="sc-inp-notify-on">{t('schedules.form.notifyOnLabel')}</label>
                <div className="flex gap-2">
                  <select
                    id="sc-inp-notify-on"
                    className="sc-select"
                    value={notifyOn}
                    onChange={(e) => setNotifyOn(e.target.value)}
                    data-testid="sc-select-notify-on"
                  >
                    <option value="change">{t('schedules.notify.on.change')}</option>
                    <option value="always">{t('schedules.notify.on.always')}</option>
                    <option value="failure">{t('schedules.notify.on.failure')}</option>
                    <option value="never">{t('schedules.notify.never')}</option>
                  </select>
                  {notifyOn !== 'never' && (
                    <input
                      type="text"
                      className="sc-input"
                      value={notifyTo}
                      onChange={(e) => setNotifyTo(e.target.value)}
                      placeholder={t('schedules.form.notifyToPlaceholder')}
                      aria-label={t('schedules.form.notifyToLabel')}
                      data-testid="sc-inp-notify-to"
                    />
                  )}
                </div>
              </div>
            </div>

            <label className="inline-flex items-center gap-2 text-[12.5px] text-[var(--text-secondary)] cursor-pointer w-fit">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                data-testid="sc-chk-enabled"
              />
              <span>{t('schedules.form.enabledLabel')}</span>
            </label>
          </div>
        </section>

        {/* 2. 执行形态两层分流 */}
        <section className="sc-sec-card">
          <div className="sc-sec-hd">
            <h3>{t('schedules.form.sec2Title')}</h3>
            <span className="sub">{t('schedules.form.sec2Sub')}</span>
          </div>
          <div className="sc-sec-bd">
            <div className="sc-kind-wrap">
              <div className="sc-kind-tier">{t('schedules.form.tier1Header')}</div>
              <button
                type="button"
                className={`sc-kind-opt ${kind === 'employee' ? 'on' : ''}`}
                onClick={() => setKind('employee')}
                data-testid="sc-kind-employee"
                aria-pressed={kind === 'employee'}
              >
                <div className="sc-kind-opt-top">
                  <span className="sc-kind-opt-name flex items-center gap-1.5">
                    <UserCheck size={14} />
                    {t('schedules.form.empTitle')}
                  </span>
                  <span className="sc-chip ok">{t('schedules.form.empBadge')}</span>
                </div>
                <div className="sc-kind-opt-desc">{t('schedules.form.empDesc')}</div>
              </button>

              <div className="sc-kind-tier">{t('schedules.form.tier2Header')}</div>
              <div className="sc-kind-grid">
                <button
                  type="button"
                  className={`sc-kind-opt ${kind === 'recipe' ? 'on' : ''}`}
                  onClick={() => setKind('recipe')}
                  data-testid="sc-kind-recipe"
                  aria-pressed={kind === 'recipe'}
                >
                  <div className="sc-kind-opt-top">
                    <span className="sc-kind-opt-name">{t('schedules.kind.recipe')}</span>
                  </div>
                  <div className="sc-kind-opt-desc">{t('schedules.form.recipeDesc')}</div>
                </button>
                <button
                  type="button"
                  className={`sc-kind-opt ${kind === 'command' ? 'on' : ''}`}
                  onClick={() => setKind('command')}
                  data-testid="sc-kind-command"
                  aria-pressed={kind === 'command'}
                >
                  <div className="sc-kind-opt-top">
                    <span className="sc-kind-opt-name">{t('schedules.kind.command')}</span>
                  </div>
                  <div className="sc-kind-opt-desc">{t('schedules.form.commandDesc')}</div>
                </button>
                <button
                  type="button"
                  className={`sc-kind-opt ${kind === 'prompt' ? 'on' : ''}`}
                  onClick={() => setKind('prompt')}
                  data-testid="sc-kind-prompt"
                  aria-pressed={kind === 'prompt'}
                >
                  <div className="sc-kind-opt-top">
                    <span className="sc-kind-opt-name">{t('schedules.kind.prompt')}</span>
                  </div>
                  <div className="sc-kind-opt-desc">{t('schedules.form.promptDesc')}</div>
                </button>
              </div>
            </div>

            {kind === 'employee' && (
              <div className="flex flex-col gap-3 mt-1">
                {isEmployeeMissing && (
                  <div className="sc-notice warn" data-testid="sc-emp-missing-warn">
                    <TriangleAlert size={15} />
                    <span>{t('schedules.detail.employeeMissing', { id: employeeId })}</span>
                  </div>
                )}

                <div className="sc-emp-box" data-testid="sc-selected-emp-box">
                  <span className="sc-emp-av" data-emp-color={empColor}>
                    {employeeInitials(employeeId, empDisplayTitle)}
                  </span>
                  <div className="sc-emp-info">
                    <div className="sc-emp-info-top">
                      <span className="sc-chip emp" data-emp-color={empColor}>
                        @{employeeId || '—'}
                      </span>
                      <span className="sc-emp-info-name">
                        {empDisplayTitle || t('schedules.form.pickEmpPrompt')}
                      </span>
                      {employeeId && <span className="sc-chip">{empDisplayKernel}</span>}
                    </div>
                    {selectedEmployee?.description && (
                      <div className="sc-emp-info-duty">{selectedEmployee.description}</div>
                    )}
                    <div className="sc-emp-info-meta">
                      {empDisplayCwd && <span>cwd: {empDisplayCwd}</span>}
                      {selectedEmployee?.recipes?.slice(0, 3).map((r) => (
                        <span key={r} className="sc-chip">
                          {r}
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="sc-btn"
                    onClick={() => setPickerOpen((v) => !v)}
                    data-testid="sc-toggle-picker-btn"
                  >
                    {pickerOpen ? t('schedules.form.collapsePicker') : t('schedules.form.changeEmp')}
                  </button>
                </div>

                {pickerOpen && (
                  <ScheduleEmployeePicker
                    employees={employees}
                    selectedId={employeeId}
                    onSelect={(emp) => {
                      setEmployeeId(emp.member_post_id);
                      setPickerOpen(false);
                    }}
                  />
                )}

                <div className="sc-field">
                  <label htmlFor="sc-inp-emp-prompt">{t('schedules.form.empPromptLabel')}</label>
                  <textarea
                    id="sc-inp-emp-prompt"
                    className="sc-textarea"
                    value={empPrompt}
                    onChange={(e) => setEmpPrompt(e.target.value)}
                    placeholder={t('schedules.form.empPromptPlaceholder')}
                    data-testid="sc-inp-emp-prompt"
                  />
                </div>

                <div className="sc-notice info">
                  <Info size={15} />
                  <span>{t('schedules.form.empSafetyNotice')}</span>
                </div>
              </div>
            )}

            {kind === 'recipe' && (
              <div className="flex flex-col gap-3 mt-1">
                <div className="sc-field">
                  <label htmlFor="sc-select-recipe">{t('schedules.form.recipeSelectLabel')}</label>
                  {recipes.length > 0 ? (
                    <select
                      id="sc-select-recipe"
                      className="sc-select"
                      value={recipeName}
                      onChange={(e) => setRecipeName(e.target.value)}
                      data-testid="sc-select-recipe"
                    >
                      {recipeName && !recipes.some((r) => r.name === recipeName) && (
                        <option value={recipeName}>{recipeName}</option>
                      )}
                      {recipes.map((r) => (
                        <option key={r.name} value={r.name}>
                          {r.name}
                          {r.description ? ` — ${r.description}` : ''}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      id="sc-select-recipe"
                      type="text"
                      className="sc-input"
                      value={recipeName}
                      onChange={(e) => setRecipeName(e.target.value)}
                      data-testid="sc-select-recipe"
                    />
                  )}
                </div>
                <div className="sc-field">
                  <label htmlFor="sc-inp-recipe-params">{t('schedules.form.recipeParamsLabel')}</label>
                  <textarea
                    id="sc-inp-recipe-params"
                    className="sc-textarea font-mono"
                    value={recipeParams}
                    onChange={(e) => setRecipeParams(e.target.value)}
                    data-testid="sc-inp-recipe-params"
                  />
                </div>
              </div>
            )}

            {kind === 'command' && (
              <div className="flex flex-col gap-3 mt-1">
                <div className="sc-notice warn" data-testid="sc-command-warn">
                  <TriangleAlert size={15} />
                  <span>{t('schedules.form.commandWarn')}</span>
                </div>
                <div className="sc-form-grid">
                  <div className="sc-field">
                    <label htmlFor="sc-inp-command">{t('schedules.form.commandLabel')}</label>
                    <input
                      id="sc-inp-command"
                      type="text"
                      className="sc-input font-mono"
                      value={commandText}
                      onChange={(e) => setCommandText(e.target.value)}
                      placeholder={t('schedules.form.commandPlaceholder')}
                      data-testid="sc-inp-command"
                    />
                  </div>
                  <div className="sc-field">
                    <label htmlFor="sc-inp-cmd-cwd">{t('schedules.form.cwdLabel')}</label>
                    <input
                      id="sc-inp-cmd-cwd"
                      type="text"
                      className="sc-input font-mono"
                      value={cwd}
                      onChange={(e) => setCwd(e.target.value)}
                    />
                  </div>
                </div>
              </div>
            )}

            {kind === 'prompt' && (
              <div className="flex flex-col gap-3 mt-1">
                <div className="sc-field">
                  <label htmlFor="sc-inp-prompt">{t('schedules.form.promptLabel')}</label>
                  <textarea
                    id="sc-inp-prompt"
                    className="sc-textarea"
                    value={promptText}
                    onChange={(e) => setPromptText(e.target.value)}
                    placeholder={t('schedules.form.promptPlaceholder')}
                    data-testid="sc-inp-prompt"
                  />
                </div>
                <div className="sc-form-grid">
                  <div className="sc-field">
                    <label htmlFor="sc-inp-allowed-tools">{t('schedules.form.allowedToolsLabel')}</label>
                    <input
                      id="sc-inp-allowed-tools"
                      type="text"
                      className="sc-input font-mono"
                      value={allowedToolsText}
                      onChange={(e) => setAllowedToolsText(e.target.value)}
                      placeholder={t('schedules.form.allowedToolsPlaceholder')}
                      data-testid="sc-inp-allowed-tools"
                    />
                  </div>
                  <div className="sc-field">
                    <label htmlFor="sc-inp-prompt-cwd">{t('schedules.form.cwdLabel')}</label>
                    <input
                      id="sc-inp-prompt-cwd"
                      type="text"
                      className="sc-input font-mono"
                      value={cwd}
                      onChange={(e) => setCwd(e.target.value)}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* 3. 动态会话标题模板与预览 */}
        <section className="sc-sec-card">
          <div className="sc-sec-hd">
            <h3>{t('schedules.form.sec3Title')}</h3>
            <span className="sub">{t('schedules.form.sec3Sub')}</span>
          </div>
          <div className="sc-sec-bd">
            {kind === 'employee' || kind === 'prompt' ? (
              <>
                <div className="sc-field">
                  <label htmlFor="sc-tpl-input">
                    {t('schedules.form.tplLabel')}
                    <span className="hint">{t('schedules.form.tplDefaultHint')}</span>
                  </label>
                  <input
                    id="sc-tpl-input"
                    type="text"
                    className="sc-input font-mono"
                    value={titleTemplate}
                    onChange={(e) => setTitleTemplate(e.target.value)}
                    data-testid="sc-tpl-input"
                  />
                </div>
                <div className="sc-tpl-chips">
                  {TEMPLATE_VARIABLES.map((token) => (
                    <button
                      key={token}
                      type="button"
                      className="sc-vchip"
                      onClick={() => insertTemplateVar(token)}
                      data-testid={`sc-vchip-${token.replace(/[^a-z_]/gi, '')}`}
                    >
                      {token}
                    </button>
                  ))}
                </div>
                <div className="sc-preview-box" data-testid="sc-title-preview-list">
                  <div className="sc-preview-hd">
                    <span>{t('schedules.form.previewHeading')}</span>
                    <span className="sc-chip ok">{t('schedules.form.previewDynamic')}</span>
                  </div>
                  {previewRuns.map((run) => (
                    <div key={run.seq} className="sc-preview-item">
                      <span className="tm">{run.triggered_at}</span>
                      <span className="tt">{run.session_title}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="sc-notice">
                <Info size={15} />
                <span>{t('schedules.form.previewNoSession')}</span>
              </div>
            )}
          </div>

          {formError && <div className="td-error mx-4 mb-3">{formError}</div>}

          <div className="sc-form-foot">
            <span className="text-[12px] text-[var(--text-muted)]">
              {kind === 'employee' && employeeId
                ? `@${employeeId} · ${triggerMode === 'cron' ? cron : `${intervalSeconds}s`}`
                : `${t(`schedules.kind.${kind}`)} · ${triggerMode === 'cron' ? cron : `${intervalSeconds}s`}`}
            </span>
            <div className="flex items-center gap-2">
              <button type="button" className="sc-btn" onClick={onCancel} disabled={saving}>
                {t('common.cancel')}
              </button>
              {isEdit && onPreviewDetail && (
                <button type="button" className="sc-btn" onClick={onPreviewDetail} disabled={saving}>
                  {t('schedules.form.previewDetail')}
                </button>
              )}
              <button
                type="button"
                className="sc-btn primary"
                onClick={() => void handleSave()}
                disabled={saving}
                data-testid="sc-save-btn"
              >
                {saving && <Loader2 size={13} className="animate-spin" />}
                {isEdit
                  ? t('schedules.form.saveUpdate')
                  : enabled
                    ? t('schedules.form.saveCreate')
                    : t('schedules.form.saveCreateDisabled')}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
