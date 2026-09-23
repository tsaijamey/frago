/**
 * 发起一个 team 的那几步。
 *
 * ## 为什么是「几步」而不是一个按钮
 *
 * 发起要交出一整场对话的记录，而交出去收不回来——退出 team 只是本机不再往上推，已经
 * 上去的仍在中继上。这么重的动作不能靠按钮名暗示，所以：挑一场 → 看清交的是什么 →
 * 确认，默认一场都不选。
 *
 * ## 两条来路
 *
 * **用一场现成的**：队友从你已经做到的地方接上。
 *
 * **新开一场**：从零一起做一件新的事。这条路上「空会话」是建不出来的——会话是 agent
 * 写下第一笔时才真正存在，平台不收没有第一句话的新建。所以这里给一句可改的开场白，
 * 而不是假装能建一个空壳。
 *
 * ## 等编号这件事必须摆在明处
 *
 * 新开一场之后不能立刻朝中继要码：Claude Code 的编号是页面这边定的，当场就有；codex
 * 和 opencode 的编号由它们自己分配，frago 要等会话起来后认领，通常 3–15 秒。
 *
 * 编号没到手就先把码摆出来，队友拿着它进来会撞上一场还不存在的会话——两个人同时看到
 * 一段谁也说不清的状态，而这功能的两侧本来就靠对方看得见才成立。所以这里等，而等的
 * 时候把「在等什么、等了多久、为什么不能跳过」三件事都写在人眼前，并留一个不等了的出口。
 *
 * 进度按**真实阶段**推进，NEVER 做假动画：三档各自对应一件确实在发生的事，条子填到
 * 哪一档就是走到哪一档。等编号那一档内部按已过时间在本档区间里爬，爬到头就停在档尾
 * ——它说的是「还在这一档里」，不是「马上就好了」。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Loader2, Plus } from 'lucide-react';

import {
  useWorkbenchSessions,
  activityTs,
  type WorkbenchSession,
} from '@/hooks/useWorkbenchSessions';
import {
  useAgentClients,
  createSession,
  waitForSession,
  pickDefaultAgent,
  rememberLastAgent,
  agentReasonText,
  type AgentClient,
} from '@/hooks/useAgentClients';
import { openTeam } from '@/hooks/useTeam';

/** 等编号最长等多久。与轮询那条链的总时长对齐，用来画进度。 */
const ID_WAIT_CEILING_MS = 30_000;

type Source = 'existing' | 'fresh';

/** 这一次发起走到哪一档。三档都对应一件确实在发生的事。 */
type Phase = 'idle' | 'creating' | 'awaitingId' | 'askingCode';

const STEPS: Phase[] = ['creating', 'awaitingId', 'askingCode'];

export interface StartTeamPanelProps {
  onDone: () => void;
  onCancel: () => void;
  /**
   * 挑好会话之后拿它去做什么。**发起和加入在这一步之前是同一件事**：两边都要一场
   * 本机的会话，挑法、新开法、要交出什么、等编号那一段，一模一样。
   *
   * 不给就是发起。加入那一侧给一个「拿这个码进去」。
   */
  commit?: (sessionId: string) => Promise<unknown>;
  /** 标题与说明。加入那一侧要说的是「拿哪一场进去」，不是「拿哪一场发起」。 */
  title?: string;
  hint?: string;
  /** 确认按钮上写什么。 */
  confirmLabel?: string;
}

export default function StartTeamPanel({
  onDone,
  onCancel,
  commit,
  title,
  hint,
  confirmLabel,
}: StartTeamPanelProps) {
  const { t } = useTranslation();
  const [source, setSource] = useState<Source>('existing');
  const take = commit ?? openTeam;
  const shared = { onDone, onCancel, commit: take, confirmLabel };

  return (
    <div className="rounded-lg border border-border">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-sm font-medium">{title ?? t('team.pickTitle')}</h3>
        <p className="mt-1 text-xs text-fg-muted">{hint ?? t('team.pickHint')}</p>
      </div>

      <div className="flex gap-2 border-b border-border px-4 py-2.5">
        <SourceTab
          label={t('team.startFromExisting')}
          why={t('team.startFromExistingWhy')}
          active={source === 'existing'}
          onClick={() => setSource('existing')}
        />
        <SourceTab
          label={t('team.startFresh')}
          why={t('team.startFreshWhy')}
          active={source === 'fresh'}
          onClick={() => setSource('fresh')}
        />
      </div>

      {source === 'existing' ? <ExistingSource {...shared} /> : <FreshSource {...shared} />}
    </div>
  );
}

/** 选中态做成整块的柔光，不用单边竖条。 */
function SourceTab({
  label,
  why,
  active,
  onClick,
}: {
  label: string;
  why: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`flex-1 rounded-lg border px-3 py-2 text-left transition-shadow ${
        active
          ? 'border-accent bg-surface-2 shadow-[0_0_0_3px_var(--accent-primary-10,rgba(139,124,255,0.18))]'
          : 'border-border hover:bg-surface-2'
      }`}
    >
      <span className="block text-xs font-medium">{label}</span>
      <span className="mt-0.5 block text-[11px] leading-relaxed text-fg-muted">{why}</span>
    </button>
  );
}

/* ── 用一场现成的 ─────────────────────────────────────────────────────────── */

interface SourceProps {
  onDone: () => void;
  onCancel: () => void;
  commit: (sessionId: string) => Promise<unknown>;
  confirmLabel?: string;
}

function ExistingSource({ onDone, onCancel, commit, confirmLabel }: SourceProps) {
  const { t } = useTranslation();
  const { sessions, loading } = useWorkbenchSessions();
  const [chosen, setChosen] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matched = needle
      ? sessions.filter(
          (s) =>
            s.title.toLowerCase().includes(needle) ||
            s.directory.toLowerCase().includes(needle),
        )
      : sessions;
    return [...matched].sort((a, b) => activityTs(b) - activityTs(a)).slice(0, 40);
  }, [sessions, query]);

  const confirm = async () => {
    if (!chosen || busy) return;
    setBusy(true);
    setError(null);
    try {
      await commit(chosen);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="border-b border-border px-4 py-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('team.pickSearch')}
          className="w-full rounded-md border border-border bg-surface px-2 py-1 text-xs"
        />
      </div>

      <div className="max-h-64 overflow-auto">
        {loading && <p className="px-4 py-6 text-xs text-fg-muted">{t('team.loading')}</p>}
        {!loading && rows.length === 0 && (
          <p className="px-4 py-6 text-xs text-fg-muted">{t('team.pickNone')}</p>
        )}
        {rows.map((s) => (
          <SessionRow
            key={s.session_id}
            session={s}
            chosen={s.session_id === chosen}
            onChoose={() => setChosen(s.session_id)}
          />
        ))}
      </div>

      {/* 后果写在确认按钮旁边，不写在别处：人读完这句才按得下去。 */}
      {chosen && (
        <div className="border-t border-border px-4 py-3">
          <p className="text-xs leading-relaxed text-warning">{t('team.pickConfirmWarn')}</p>
          {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
        </div>
      )}

      <Footer
        onCancel={onCancel}
        confirmLabel={confirmLabel ?? t('team.pickConfirm')}
        disabled={!chosen || busy}
        onConfirm={() => void confirm()}
      />
    </>
  );
}

function SessionRow({
  session,
  chosen,
  onChoose,
}: {
  session: WorkbenchSession;
  chosen: boolean;
  onChoose: () => void;
}) {
  return (
    <button
      onClick={onChoose}
      aria-pressed={chosen}
      className={`flex w-full items-start gap-2 border-b border-border px-4 py-2.5 text-left last:border-b-0 ${
        chosen ? 'bg-surface-2' : 'hover:bg-surface-2'
      }`}
    >
      <span className="mt-0.5 w-4 shrink-0 text-accent">{chosen && <Check size={14} />}</span>
      <span className="min-w-0 flex-1">
        {/* 会话名是人认得出来的那个东西。会话号不摆在脸上——它长到读不了，而人从来
            不是靠它认一场对话。 */}
        <span className="block truncate text-xs font-medium">{session.title}</span>
        <span className="mt-0.5 block truncate text-[11px] text-fg-muted">
          {session.directory}
        </span>
      </span>
      <span className="shrink-0 text-[11px] text-fg-muted">{whenShort(activityTs(session))}</span>
    </button>
  );
}

/** 最后活动多久以前。清单按它倒序，所以它必须出现在行上。 */
function whenShort(ms: number): string {
  const mins = Math.max(0, Math.round((Date.now() - ms) / 60000));
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/* ── 新开一场 ─────────────────────────────────────────────────────────────── */

function FreshSource({ onDone, onCancel, commit, confirmLabel }: SourceProps) {
  const { t } = useTranslation();
  const { agents, fallbackDefault, loading: agentsLoading, error: agentsError } =
    useAgentClients(true);
  const { sessions } = useWorkbenchSessions();

  const [agent, setAgent] = useState<string>('');
  const [cwd, setCwd] = useState('');
  const [opening, setOpening] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);

  // 默认挑哪一家走已有的那条判断：上次用的优先，它现在挑不了就退到服务端建议的。
  useEffect(() => {
    if (agent || agentsLoading || agents.length === 0) return;
    setAgent(pickDefaultAgent(agents, fallbackDefault) ?? '');
  }, [agent, agents, agentsLoading, fallbackDefault]);

  // 默认目录取最近一场会话的目录：人最近在哪儿干活是这台机器上现成的事实，比写死一个
  // 路径强——写死的那个在别人机器上根本不存在。
  useEffect(() => {
    if (cwd || sessions.length === 0) return;
    const recent = [...sessions].sort((a, b) => activityTs(b) - activityTs(a))[0];
    if (recent?.directory) setCwd(recent.directory);
  }, [cwd, sessions]);

  // 开场白给一句可改的默认。语言切换后还没动过它就跟着换——人没写过的东西不算他的输入。
  const defaultOpening = t('team.freshOpeningDefault');
  const touched = useRef(false);
  useEffect(() => {
    if (!touched.current) setOpening(defaultOpening);
  }, [defaultOpening]);

  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  const chosenAgent = agents.find((a) => a.agent_type === agent) ?? null;
  const idIsInstant = chosenAgent?.id_origin === 'caller';

  const go = async () => {
    if (!agent || !cwd.trim() || !opening.trim() || phase !== 'idle') return;
    setError(null);
    setCancelled(false);
    setStartedAt(Date.now());
    const controller = new AbortController();
    abort.current = controller;

    try {
      setPhase('creating');
      const pending = await createSession({ agent, cwd: cwd.trim(), text: opening.trim() });
      rememberLastAgent(agent);

      // 编号当场就有的那一家直接过；要认领的那一家在这里等，等的全过程摆在人眼前。
      let sessionId = pending.session_id;
      if (!sessionId) {
        setPhase('awaitingId');
        sessionId = await waitForSession(pending.handle, { signal: controller.signal });
      }

      setPhase('askingCode');
      await commit(sessionId);
      onDone();
    } catch (err) {
      if (controller.signal.aborted) {
        // 取消的是「等」，不是那场会话——它已经起来了，说清楚它在哪，别让人以为白费了。
        setCancelled(true);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
      setPhase('idle');
      setStartedAt(null);
    } finally {
      abort.current = null;
    }
  };

  if (phase !== 'idle') {
    return (
      <WaitingView
        phase={phase}
        agentName={chosenAgent?.display_name ?? agent}
        idIsInstant={!!idIsInstant}
        startedAt={startedAt}
        onCancel={() => abort.current?.abort()}
      />
    );
  }

  return (
    <>
      <div className="space-y-3 px-4 py-3">
        <Field label={t('team.freshAgent')}>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((a) => (
              <AgentChip
                key={a.agent_type}
                agent={a}
                active={a.agent_type === agent}
                onClick={() => setAgent(a.agent_type)}
              />
            ))}
            {agentsLoading && <span className="text-xs text-fg-muted">{t('team.loading')}</span>}
            {agentsError && <span className="text-xs text-danger">{agentsError}</span>}
          </div>
        </Field>

        <Field label={t('team.freshCwd')}>
          <input
            value={cwd}
            onChange={(e) => setCwd(e.target.value)}
            spellCheck={false}
            className="w-full rounded-md border border-border bg-surface px-2 py-1.5 font-mono text-xs"
          />
          {!cwd.trim() && <Hint text={t('team.freshNeedCwd')} />}
        </Field>

        <Field label={t('team.freshOpening')} why={t('team.freshOpeningWhy')}>
          <textarea
            value={opening}
            onChange={(e) => {
              touched.current = true;
              setOpening(e.target.value);
            }}
            rows={2}
            className="w-full resize-none rounded-md border border-border bg-surface px-2 py-1.5 text-xs"
          />
          {!opening.trim() && <Hint text={t('team.freshNeedOpening')} />}
        </Field>

        {/* 新开一场也要交出记录，这句和挑现成的那条路上说的是同一件事。 */}
        <p className="text-xs leading-relaxed text-warning">{t('team.pickConfirmWarn')}</p>

        {/* 慢的那一家在按下去之前就把等待说在前面，不等人按完才发现。 */}
        {chosenAgent && (
          <p className="text-[11px] text-fg-muted">
            {idIsInstant ? t('team.waitIdFast') : t('team.waitIdSlow')}
          </p>
        )}

        {cancelled && <p className="text-xs text-fg-muted">{t('team.waitCancelled')}</p>}
        {error && <p className="text-xs text-danger">{error}</p>}
      </div>

      <Footer
        onCancel={onCancel}
        confirmLabel={confirmLabel ?? t('team.freshGo')}
        disabled={!agent || !cwd.trim() || !opening.trim()}
        onConfirm={() => void go()}
      />
    </>
  );
}

function Hint({ text }: { text: string }) {
  return <span className="mt-1 block text-[11px] text-fg-muted">{text}</span>;
}

function Field({
  label,
  why,
  children,
}: {
  label: string;
  why?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-[11px] font-medium text-fg-muted">{label}</span>
      {why && <span className="mb-1 block text-[11px] text-fg-muted">{why}</span>}
      <span className="mt-1 block">{children}</span>
    </label>
  );
}

/** 挑不了的那一家照样摆出来，连同理由——整个藏掉，人只会以为 frago 不支持它。 */
function AgentChip({
  agent,
  active,
  onClick,
}: {
  agent: AgentClient;
  active: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      disabled={!agent.selectable}
      onClick={onClick}
      aria-pressed={active}
      title={agentReasonText(agent.reason) ?? undefined}
      className={`rounded-lg border px-2.5 py-1 text-xs transition-shadow disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? 'border-accent bg-surface-2 shadow-[0_0_0_3px_var(--accent-primary-10,rgba(139,124,255,0.18))]'
          : 'border-border hover:bg-surface-2'
      }`}
    >
      {agent.display_name}
      {!agent.selectable && (
        <span className="ml-1 text-[10px] text-fg-muted">
          · {agentReasonText(agent.reason) ?? t('team.freshAgentUnavailable')}
        </span>
      )}
    </button>
  );
}

/**
 * 等的时候摆什么。
 *
 * 三档各自对应一件确实在发生的事，所以进度条不是动画——它填到哪儿就是走到哪一档。
 * 等编号那一档内部按已过时间在本档区间里爬，到头停住：它说的是「还在这一档」，
 * 不是「马上就好」。
 */
export function WaitingView({
  phase,
  agentName,
  idIsInstant,
  startedAt,
  onCancel,
}: {
  phase: Phase;
  agentName: string;
  idIsInstant: boolean;
  startedAt: number | null;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const elapsed = useElapsed(startedAt);

  // 三档各占三分之一。中间那档按已过时间在自己的区间里爬，封顶不越界。
  const progress = useMemo(() => {
    if (phase === 'creating') return 1 / 6;
    if (phase === 'askingCode') return 5 / 6;
    const within = Math.min(1, elapsed / ID_WAIT_CEILING_MS);
    return 1 / 3 + within * (1 / 3);
  }, [phase, elapsed]);

  const stepState = (own: Phase): 'waiting' | 'active' | 'done' => {
    const here = STEPS.indexOf(phase);
    const mine = STEPS.indexOf(own);
    if (mine < here) return 'done';
    if (mine === here) return 'active';
    return 'waiting';
  };

  const percent = Math.round(progress * 100);

  return (
    <div className="px-4 py-4">
      <p className="text-sm font-medium">{t('team.waitTitle')}</p>

      <div
        className="mt-3 h-1 overflow-hidden rounded-full bg-surface-2"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-label={t('team.waitTitle')}
      >
        <div
          data-testid="team-start-progress"
          className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out"
          style={{ width: `${percent}%` }}
        />
      </div>

      <div className="mt-3 space-y-1.5">
        <Step state={stepState('creating')} label={t('team.waitStepCreate', { name: agentName })} />
        <Step state={stepState('awaitingId')} label={t('team.waitStepId')} />
        <Step state={stepState('askingCode')} label={t('team.waitStepCode')} />
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-fg-muted">
        {idIsInstant ? t('team.waitIdFast') : t('team.waitIdSlow')}
        {' · '}
        {t('team.waitElapsed', { secs: Math.floor(elapsed / 1000) })}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-fg-muted">{t('team.waitWhyNoCode')}</p>

      <div className="mt-3">
        <button onClick={onCancel} className="text-xs text-fg-muted hover:underline">
          {t('team.waitCancel')}
        </button>
      </div>
    </div>
  );
}

/** 每秒推一次已过时间。没在等的时候不跑计时器。 */
function useElapsed(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);
  return startedAt === null ? 0 : Math.max(0, now - startedAt);
}

function Step({
  state,
  label,
}: {
  state: 'waiting' | 'active' | 'done';
  label: string;
}) {
  return (
    <div
      data-testid="team-start-step"
      data-state={state}
      className={`flex items-center gap-2 text-xs text-fg-muted ${
        state === 'waiting' ? 'opacity-60' : ''
      }`}
    >
      <span className="flex h-4 w-4 shrink-0 items-center justify-center">
        {state === 'done' ? (
          <Check size={13} className="text-accent" />
        ) : state === 'active' ? (
          <Loader2 size={13} className="animate-spin text-accent" />
        ) : (
          <span className="h-1.5 w-1.5 rounded-full bg-fg-muted" />
        )}
      </span>
      <span>{label}</span>
    </div>
  );
}

function Footer({
  onCancel,
  confirmLabel,
  disabled,
  onConfirm,
}: {
  onCancel: () => void;
  confirmLabel: string;
  disabled: boolean;
  onConfirm: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-2.5">
      <button onClick={onCancel} className="px-2 py-1 text-xs text-fg-muted hover:underline">
        {t('team.cancel')}
      </button>
      <button
        disabled={disabled}
        onClick={onConfirm}
        className="flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-xs text-on-accent disabled:opacity-40"
      >
        <Plus size={13} strokeWidth={1.5} />
        {confirmLabel}
      </button>
    </div>
  );
}
