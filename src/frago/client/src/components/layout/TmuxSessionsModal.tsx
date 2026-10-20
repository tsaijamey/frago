/**
 * TmuxSessionsModal —— 本机 tmux 会话的清点与手动清理。
 *
 * **每一行的主角是「上次说了什么」，不是会话编号。** 一屏十几行 uuid 谁也认不出来，
 * 而人来这个浮窗是要决定「这场还要不要」——那个判断只能靠它最后说的那句话。所以正文
 * 截取占据一行里最宽的位置，编号退到角落当把手用。
 *
 * **闲置时长的口径是「自最后一次把话说完起」。** 不是 tmux 的活动时间：claude 的
 * 状态栏一直在刷 token 计数，pane 上有字变化 tmux 就把活动时间往前推，实测同一批
 * 会话两个口径能差出四个多小时——照那个数字清理，等于什么都清不掉。
 *
 * **正在干活的不给勾。** 从工作台点开一场昨天的会话时，它记录里最后一条本来就是
 * 昨天的，闲置时长天然超过任何门槛，而那一刻它正在重建、马上要接着干。这个坑后台
 * 自动回收踩过，注释记在服务端。所以勾选框认的是「屏上真的停着」，不是时间。
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw, X } from 'lucide-react';
import type { TFunction } from 'i18next';
import { useTmuxSessions } from '@/hooks/useTmuxSessions';
import { usePageStore } from '@/stores/appStore';
import type { TmuxSessionItem } from '@/types/api';

interface Props {
  onClose: () => void;
}

/* 正文截多长。一行给到 160 个字，中文差不多两句话——够认出「这是哪一场」，
   再长就把闲置时长和内存挤出视野了。 */
const EXCERPT_CHARS = 160;

/* 门槛预设。最短那档 0.5 小时对齐服务端自动回收的 30 分钟线，人一眼能对上；
   往上是「今天早些时候」和「昨天以前」两个尺度。 */
const PRESET_HOURS = [0.5, 1, 4, 24];

function formatIdle(secs: number | null, t: TFunction): string {
  // 判不出闲置时长时写明白，不摆一条看不懂的短横线：这一场可能还没把这一轮说完，
  // 也可能认不出它对应哪份记录。
  if (secs === null) return t('tmuxSessions.idle.unknown');
  if (secs < 60) return t('tmuxSessions.idle.justNow');
  if (secs < 3600) return t('tmuxSessions.idle.minutes', { n: Math.floor(secs / 60) });
  if (secs < 86400) return t('tmuxSessions.idle.hours', { n: (secs / 3600).toFixed(1) });
  return t('tmuxSessions.idle.days', { n: (secs / 86400).toFixed(1) });
}

function formatStopAt(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * 能不能关：正在干活的一律不许，剩下的都可以。
 *
 * CoreAgent 行不在关闭范围内：停掉它的一轮不等于销毁这场会话，跟「关掉 tmux 会话、
 * 上下文不再保留」不是同一个动作，所以只给「打开」。
 */
function isSelectable(session: TmuxSessionItem): boolean {
  return session.kind !== 'coreagent' && !session.busy;
}

/** CoreAgent 的三档状态；tmux 行没有这一格。 */
function stateLabel(session: TmuxSessionItem, t: TFunction): string | null {
  if (session.kind !== 'coreagent') return null;
  switch (session.state) {
    case 'starting':
      return t('tmuxSessions.state.starting');
    case 'busy':
      return t('tmuxSessions.state.busy');
    case 'idle':
      return t('tmuxSessions.state.idle');
    default:
      return null;
  }
}

export default function TmuxSessionsModal({ onClose }: Props) {
  const { t } = useTranslation();
  const { data, loading, error, titles, reload, close, saveThreshold } =
    useTmuxSessions(EXCERPT_CHARS);
  // 当前正在对话的那一场。放在全局状态里，不随页面切换清掉；浮窗据此标出对应行。
  const currentId = usePageStore((s) => s.workbenchSessionId);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);
  const switchPage = usePageStore((s) => s.switchPage);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [hours, setHours] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [closing, setClosing] = useState(false);
  const [report, setReport] = useState<string | null>(null);

  // Esc 关窗。它盖住半屏，不该只有一个叉能收。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (confirming) setConfirming(false);
      else onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [confirming, onClose]);

  // 门槛的初值来自服务端存着的那个值，人没动过就一直是它。
  useEffect(() => {
    if (hours === null && data) setHours(data.cleanup_idle_hours);
  }, [data, hours]);

  // 空数组每次渲染都是新对象，直接写在 render 里会让下面那个 useMemo 每轮都重算。
  const sessions = useMemo(() => data?.sessions ?? [], [data]);
  const threshold = hours ?? 1;

  /** 超过门槛、且此刻没在干活的那些——「批量选中」按钮点下去就是它们。 */
  const overThreshold = useMemo(
    () =>
      sessions.filter(
        (s) => isSelectable(s) && s.idle_secs !== null && s.idle_secs >= threshold * 3600
      ),
    [sessions, threshold]
  );

  const selectedSessions = sessions.filter((s) => selected.has(s.name));
  const selectedMemory = selectedSessions.reduce((sum, s) => sum + s.memory_mb, 0);

  // 当前会话在这份清单里对不上时要把原因说出来：它可能已经结束，也可能是一个
  // 认不出所属会话的 tmux 行——两种情况人都得知道，而不是以为标记丢了。
  const currentMissing =
    currentId !== null && data !== null && !sessions.some((s) => s.session_id === currentId);

  /** 这一行在清单里的名字：人在左栏认得的那句标题，取不到才退回把手名。 */
  const titleOf = (session: TmuxSessionItem): string =>
    (session.session_id && titles[session.session_id]) || session.label;

  /** 从浮窗跳进那一场会话。跟着一起收窗：清单只是路过的门口。 */
  const openSession = (sessionId: string) => {
    setWorkbenchSessionId(sessionId);
    switchPage('session_workbench');
    onClose();
  };

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const selectOverThreshold = () => {
    setSelected(new Set(overThreshold.map((s) => s.name)));
    setReport(null);
  };

  const applyThreshold = (value: number) => {
    setHours(value);
    setReport(null);
    void saveThreshold(value);
  };

  const doClose = async () => {
    setClosing(true);
    try {
      const result = await close(selectedSessions.map((s) => s.name));
      setSelected(new Set());
      setConfirming(false);
      setReport(
        result.failed === 0
          ? t('tmuxSessions.report.allClosed', { n: result.closed })
          : t('tmuxSessions.report.partial', { n: result.closed, failed: result.failed })
      );
    } catch (e) {
      setReport(e instanceof Error ? e.message : String(e));
    } finally {
      setClosing(false);
    }
  };

  return (
    <div className="tmux-overlay" onClick={onClose}>
      <div
        className="tmux-card"
        role="dialog"
        aria-label={t('tmuxSessions.title')}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="tmux-header">
          <div className="tmux-title">
            {t('tmuxSessions.title')}
            <span className="tmux-summary">
              {t('tmuxSessions.summary', {
                total: data?.total ?? 0,
                memory: data?.total_memory_mb ?? 0,
              })}
            </span>
          </div>
          <div className="tmux-header-actions">
            <button
              type="button"
              className="tmux-icon-btn"
              onClick={reload}
              disabled={loading}
              title={t('tmuxSessions.refresh')}
              aria-label={t('tmuxSessions.refresh')}
            >
              <RefreshCw size={14} className={loading ? 'cs-spin' : ''} />
            </button>
            <button
              type="button"
              className="tmux-icon-btn"
              onClick={onClose}
              aria-label={t('tmuxSessions.close')}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="tmux-filter">
          <span className="tmux-filter-label">{t('tmuxSessions.threshold.label')}</span>
          {PRESET_HOURS.map((h) => (
            <button
              key={h}
              type="button"
              className={`tmux-chip ${threshold === h ? 'tmux-chip--on' : ''}`}
              onClick={() => applyThreshold(h)}
            >
              {t('tmuxSessions.threshold.preset', { n: h })}
            </button>
          ))}
          <input
            type="number"
            className="tmux-threshold-input"
            min={0}
            max={720}
            step={0.5}
            value={threshold}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v)) setHours(v);
            }}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v)) applyThreshold(v);
            }}
            aria-label={t('tmuxSessions.threshold.custom')}
          />
          <button
            type="button"
            className="tmux-select-btn"
            onClick={selectOverThreshold}
            disabled={overThreshold.length === 0}
          >
            {t('tmuxSessions.threshold.selectMatching', { n: overThreshold.length })}
          </button>
        </div>

        {currentMissing ? (
          <div className="tmux-note">{t('tmuxSessions.currentMissing')}</div>
        ) : null}
        {error && <div className="tmux-error">{error}</div>}
        {report && <div className="tmux-report">{report}</div>}

        <div className="tmux-list">
          {sessions.length === 0 && !loading ? (
            <div className="tmux-empty">{t('tmuxSessions.empty')}</div>
          ) : null}

          {sessions.map((s) => {
            const selectable = isSelectable(s);
            const stale = s.idle_secs !== null && s.idle_secs >= threshold * 3600;
            const core = s.kind === 'coreagent';
            const current = currentId !== null && s.session_id === currentId;
            const state = stateLabel(s, t);
            return (
              <label
                key={s.name}
                className={`tmux-row ${selected.has(s.name) ? 'tmux-row--on' : ''} ${
                  selectable ? '' : core ? 'tmux-row--core' : 'tmux-row--locked'
                } ${current ? 'tmux-row--current' : ''}`}
              >
                {core ? null : (
                  <input
                    type="checkbox"
                    className="tmux-check"
                    checked={selected.has(s.name)}
                    disabled={!selectable}
                    onChange={() => toggle(s.name)}
                  />
                )}
                <div className="tmux-row-body">
                  <div className="tmux-row-main">
                    <span
                      className="tmux-title"
                      title={s.directory ? `${titleOf(s)}\n${s.directory}` : titleOf(s)}
                    >
                      {titleOf(s)}
                    </span>
                    {current ? (
                      <span className="tmux-badge tmux-badge--current">
                        {t('tmuxSessions.badge.current')}
                      </span>
                    ) : null}
                    {core ? (
                      <span className="tmux-badge tmux-badge--core">
                        {t('tmuxSessions.badge.coreAgent')}
                      </span>
                    ) : null}
                    {s.busy && !core ? (
                      <span className="tmux-badge tmux-badge--busy">
                        {t('tmuxSessions.badge.busy')}
                      </span>
                    ) : null}
                    {state ? <span className="tmux-badge tmux-badge--state">{state}</span> : null}
                    {s.session_id ? (
                      <button
                        type="button"
                        className="tmux-open-btn"
                        // 这一行是个 label，不显式起名，按钮的可读名字会把整行文字吞进去。
                        aria-label={t('tmuxSessions.openWith', { name: titleOf(s) })}
                        // 同样是因为 label：不拦住点击会把复选框一起切了。
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          openSession(s.session_id as string);
                        }}
                      >
                        {t('tmuxSessions.open')}
                      </button>
                    ) : null}
                  </div>
                  <div className="tmux-row-meta">
                    <span className={`tmux-idle ${stale ? 'tmux-idle--stale' : ''}`}>
                      {formatIdle(s.idle_secs, t)}
                    </span>
                    {s.last_stop_at ? (
                      <span className="tmux-stop-at">{formatStopAt(s.last_stop_at)}</span>
                    ) : null}
                    <span className="tmux-mem">{s.memory_mb} MB</span>
                    {s.session_id ? (
                      <span className="tmux-sid" title={s.session_id}>
                        {s.session_id}
                      </span>
                    ) : null}
                  </div>
                  <div className="tmux-excerpt">
                    {s.excerpt || t('tmuxSessions.noExcerpt')}
                  </div>
                </div>
              </label>
            );
          })}
        </div>

        <div className="tmux-foot">
          {confirming ? (
            <>
              <span className="tmux-confirm-text">
                {t('tmuxSessions.confirm', {
                  n: selectedSessions.length,
                  memory: selectedMemory,
                })}
              </span>
              <button
                type="button"
                className="tmux-btn"
                onClick={() => setConfirming(false)}
                disabled={closing}
              >
                {t('tmuxSessions.cancel')}
              </button>
              <button
                type="button"
                className="tmux-btn tmux-btn--danger"
                onClick={doClose}
                disabled={closing}
              >
                {closing ? <Loader2 size={14} className="cs-spin" /> : null}
                {t('tmuxSessions.confirmClose')}
              </button>
            </>
          ) : (
            <>
              <span className="tmux-foot-note">
                {t('tmuxSessions.selectedNote', {
                  n: selectedSessions.length,
                  memory: selectedMemory,
                })}
              </span>
              <button
                type="button"
                className="tmux-btn tmux-btn--danger"
                onClick={() => setConfirming(true)}
                disabled={selectedSessions.length === 0}
              >
                {t('tmuxSessions.closeSelected')}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
