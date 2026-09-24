/**
 * vibe teaming：我这一场会话，旁边是队友那一场。
 *
 * ## 这一页的骨架
 *
 * **连接码常驻页头，随时可复制，但只露前 4 位。** 它是队友进门的唯一凭证，也是这一页
 * 从头到尾都用得上的东西——一个人的时候要把它发出去，两个人之后要认出自己在哪个 team
 * 里。前 4 位够认，完整的码按 Copy 拿；屏幕上的一切都可能随截图、录屏、同步带出去。
 *
 * **左边永远是我自己那一场，而且是一整张会话详情**：记录流加一个能说话的输入区，与
 * 会话页上那一场没有区别。队友在不在都不影响我在这一侧继续干活。
 *
 * 队友经中继投来的消息**也在这一列里**——它们落进我这场会话，是一条带前缀的用户发言，
 * 跟我自己说的话排在同一条流上。所以这一列必须是完整的会话详情，不能是只读的摘要：
 * 队友让我的 agent 做了一件事，我要在同一个地方看见它、接着它往下说。
 *
 * **右边只在队友进来之后才立起来。** 他没进来时不摆一列空白顶着他的名字——那看起来
 * 像坏了。那块地方说的是「他还没进来」，并把注意力送回顶上那串码。
 *
 * ## 两个输入区是两件事，NEVER 合成一个
 *
 * 左边那个是对**我自己的 agent** 说话，跟会话页上完全一样。
 *
 * 右边那个不是聊天框，是**给队友的 agent 下一件事**：它落到队友的会话里，是一条用户
 * 发言，前面带一句说明它来自我。所以它长得跟左边不一样、有自己的标题、写明这句话去
 * 哪儿，并且只在队友在场时才出现——没人可投的时候摆一个能打字的框，是在骗人。
 *
 * 那句前缀由**收的那一侧**按自己的设置加上。它描述的是「我的话在队友屏幕上长什么样」，
 * 所以只作发送前的一次预览，NEVER 常驻一行别人口气的话在我眼前。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  Copy,
  Eye,
  HelpCircle,
  Link2,
  LogOut,
  Plus,
  RefreshCw,
  Send,
  UserPlus,
  Users,
} from 'lucide-react';

import PageHeader from '@/components/layout/PageHeader';
import RecordStream from '@/components/sessionWorkbench/RecordStream';
import { RecordOverrideContext, RecordVoiceContext } from '@/components/sessionWorkbench/RecordCard';
import Composer from '@/components/sessionWorkbench/Composer';
import { DecisionCardContext } from '@/components/sessionWorkbench/DecisionCard';
import { useDecisionCards } from '@/hooks/useDecisionCards';
import StartTeamPanel from '@/components/vibeTeaming/StartTeamPanel';
import { useWorkbenchRecords, type WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import { FAMILY_LABEL_KEY, useWorkbenchSessions } from '@/hooks/useWorkbenchSessions';
import {
  TeamError,
  joinTeam,
  leaveTeam,
  sendToPeer,
  usePeerRecords,
  useTeamState,
  type TeamBinding,
  type TeamTrouble,
} from '@/hooks/useTeam';
import IncomingRequest from './IncomingRequest';
import MyRulesBar from './MyRulesBar';
import PeerTiers, { Prediction, type RulesSource } from './PeerTiers';
import RequestCard from './RequestCard';
import TeamAvatar from './TeamAvatar';
import TeamsGuide, { useTeamsGuide } from './TeamsGuide';
import {
  FRAGO_DEFAULT_RULES,
  classifyTier,
  maskCode,
  maskCodes,
  maskCodesIn,
  parseRelayed,
  stepsFor,
  stepsForRelayed,
  verdictOf,
  type RequestProgress,
  type RequestRules,
  type RequestStep,
  type SentRequest,
} from './teamRequest';

const ICON = { size: 16, strokeWidth: 1.5 } as const;

/** 连接码有多长、由哪些字符组成。
 *
 * 中继那边生成时去掉了 0 O 1 I L——这几个字念出来、抄下来最容易串。界面两头都按
 * 这张表挡：填不进去的字符当场进不来，好过填完了才被中继回一个统一的拒绝。
 *
 * 从前这个输入框限死 6 位而码是 10 位，粘进来被截断，永远对不上，而且不报错。
 */
const CODE_ALPHABET = '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
const CODE_LENGTH = 10;

/** 只留得进的那些字符，并截到长度上限。 */
function cleanCode(raw: string): string {
  return raw
    .toUpperCase()
    .split('')
    .filter((ch) => CODE_ALPHABET.includes(ch))
    .join('')
    .slice(0, CODE_LENGTH);
}

export default function VibeTeamingPage() {
  const { t } = useTranslation();
  const { state, error: stateError, loading, reload } = useTeamState();
  const [selected, setSelected] = useState<string | null>(null);
  const [guideOpen, toggleGuide] = useTeamsGuide();
  // 刚存下的设置先用上，等本机状态重读回来再以它为准——不然点完要等一轮才看得到变化。
  const [justSaved, setJustSaved] = useState<RequestRules | null>(null);
  const rules = justSaved ?? state?.request_rules ?? null;

  const active = useMemo(() => (state?.teams ?? []).filter((one) => one.active), [state]);

  // 没选或选的那个已经退出了，就落到第一个还在的上面。人退出一个 team 之后不该
  // 盯着一列空白发愣。
  useEffect(() => {
    if (active.length === 0) {
      setSelected(null);
      return;
    }
    if (!selected || !active.some((one) => one.code === selected)) {
      setSelected(active[0].code);
    }
  }, [active, selected]);

  const binding = active.find((one) => one.code === selected) ?? null;
  // 本机知道的全部完整码。记录里出现哪一个都遮——几个 team 并排时，另一个的码也可能
  // 被人贴进这一场里。
  const codes = useMemo(() => (state?.teams ?? []).map((one) => one.code), [state]);

  if (loading) {
    return <div className="p-6 text-sm text-text-muted">{t('team.loading')}</div>;
  }

  if (stateError) {
    return <div className="p-6 text-sm text-accent-error">{stateError}</div>;
  }

  // 一个 team 都没有时整页就是这张说明书，上面不再摆那条工具栏——两个动作已经
  // 是说明书里并排的两条路，再在顶上摆一遍就是同一件事说两遍。
  if (active.length === 0) {
    return <Intro onChanged={reload} />;
  }

  return (
    <div className="flex h-full flex-col">
      <TeamBar
        teams={active}
        selected={selected}
        onSelect={setSelected}
        onChanged={reload}
        guideOpen={guideOpen}
        onToggleGuide={toggleGuide}
      />
      {guideOpen && <TeamsGuide onHide={toggleGuide} />}
      {binding && (
        <Paired
          binding={binding}
          codes={codes}
          rules={rules}
          onRulesSaved={(next) => {
            setJustSaved(next);
            void reload().then(() => setJustSaved(null));
          }}
        />
      )}
    </div>
  );
}

/**
 * 一个 team 都没有时的整页说明书。
 *
 * 从前这里是一行居中的字，假定人已经知道 teaming 是什么、连接码是干什么的。人第一次
 * 打开这一页时恰恰什么都不知道，而这一页的两个动作一个要交出对话记录、一个要粘一串
 * 从别处拿来的凭证——两件都不该靠猜。
 */
function Intro({ onChanged }: { onChanged: () => void }) {
  const { t } = useTranslation();
  const [path, setPath] = useState<'open' | 'join' | null>(null);
  // 这一屏只在一个 team 都没有时出现，所以没有「已经在里面」这种情况。
  const joined: string[] = [];

  return (
    <div className="mx-auto h-full w-full max-w-2xl overflow-y-auto px-6 py-12">
      <div className="flex items-center gap-2 text-text-muted">
        <Users size={18} strokeWidth={1.5} />
        <h2 className="text-base font-semibold text-text-primary">{t('team.title')}</h2>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-text-muted">{t('team.pitch')}</p>
      <p className="mt-2 text-sm leading-relaxed text-text-muted">{t('team.pitchCode')}</p>

      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        <PathCard
          icon={<Plus {...ICON} />}
          title={t('team.pathOpen')}
          why={t('team.pathOpenWhy')}
          active={path === 'open'}
          onClick={() => setPath(path === 'open' ? null : 'open')}
        />
        <PathCard
          icon={<Link2 {...ICON} />}
          title={t('team.pathJoin')}
          why={t('team.pathJoinWhy')}
          active={path === 'join'}
          onClick={() => setPath(path === 'join' ? null : 'join')}
        />
      </div>

      {path === 'open' && (
        <div className="mt-4">
          <StartTeamPanel onDone={onChanged} onCancel={() => setPath(null)} />
        </div>
      )}
      {path === 'join' && (
        <div className="mt-4">
          <JoinFlow
            onDone={onChanged}
            onCancel={() => setPath(null)}
            joined={joined}
            onGoTo={() => setPath(null)}
          />
        </div>
      )}
    </div>
  );
}

function PathCard({
  icon,
  title,
  why,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  why: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-lg border p-4 text-left transition-shadow ${
        active
          ? 'border-border-accent bg-bg-hover ring-2 ring-accent-primary-20'
          : 'border-border-color hover:bg-bg-hover'
      }`}
    >
      <span className="flex items-center gap-2 text-sm font-medium">
        {icon}
        {title}
      </span>
      <span className="mt-1.5 block text-xs leading-relaxed text-text-muted">{why}</span>
    </button>
  );
}

/**
 * 加入：填码 → 挑一场会话带进去。**两步都在这一页里走完。**
 *
 * 从前这里要求人先去会话页把某一场"选中"，否则按钮点不动。那是把发起那一侧的老做法
 * 照搬过来的：发起时页面偷偷拿工作台停着的那一场，加入时同一份东西拿不到，就变成一句
 * 让人出门的提示。对着屏幕的人是这样的处境——他手里攥着队友刚发来的码，刚敲进去，被
 * 告知要先去另一个页面做一件没说清楚是什么的事，回来时码还在不在都不知道。
 *
 * 挑会话这件事发起那边已经有一整套（挑现成的、或者新开一场，连等编号都摆在明处），
 * 加入要的是同一样东西，直接共用。
 *
 * ## 三种收场，三条不同的下一步
 *
 * **这个码用不了。** 中继对「打错了」「已作废」「位置被别的机器占了」回的是逐字节
 * 相同的一句话——分开说等于给猜码的人一盏指示灯。所以这里也不猜是哪一种，只把码留在
 * 框里让人改。
 *
 * **够不着中继。** 跟码没关系，说清是那一侧不通，给一个重试，码原样留着。
 *
 * **被限流。** 说清还要等几秒，倒数到点按钮自己解禁——让人对着一个永远点不动的按钮
 * 猜要等多久，比不给按钮还糟。
 *
 * 还有一种在发请求之前就拦下：**本机已经在这个 team 里**。再 join 一次不会有新东西，
 * 只会让人以为自己进了个新的。当场说清，指向顶上那块。
 */
function JoinFlow({
  onDone,
  onCancel,
  joined,
  onGoTo,
}: {
  onDone: () => void;
  onCancel: () => void;
  /** 本机已经在里面的那些码。填到其中之一时不发请求。 */
  joined: string[];
  /** 人说「去看它」时把顶上那块切过去。 */
  onGoTo: (code: string) => void;
}) {
  const { t } = useTranslation();
  const [code, setCode] = useState('');
  const [locked, setLocked] = useState<string | null>(null);

  const full = code.length === CODE_LENGTH;
  const already = full && joined.includes(code);

  if (locked) {
    return (
      <JoinPick
        code={locked}
        onDone={onDone}
        onBackToCode={() => setLocked(null)}
      />
    );
  }

  return (
    <form
      className="rounded-lg border border-border-color p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (full && !already) setLocked(code);
      }}
    >
      <p className="text-sm font-medium">{t('team.joinCodeTitle')}</p>
      <div className="mt-2 flex items-center gap-2">
        <input
          autoFocus
          value={code}
          onChange={(e) => setCode(cleanCode(e.target.value))}
          placeholder={t('team.codePlaceholder')}
          maxLength={CODE_LENGTH}
          aria-invalid={already || undefined}
          className="w-44 rounded-md border border-border-color bg-bg-card px-2 py-1.5 font-mono text-sm tracking-widest"
        />
        <button
          type="submit"
          disabled={!full || already}
          className="rounded-md bg-accent-primary px-3 py-1.5 text-xs text-[var(--text-on-accent)] disabled:opacity-40"
        >
          {t('team.joinNext')}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-2 py-1 text-xs text-text-muted hover:underline"
        >
          {t('team.cancel')}
        </button>
      </div>

      {/* 差几位就说差几位。从前这里限死 6 位，粘进来被悄悄截断，人看不出为什么对不上。 */}
      {!full && code.length > 0 && (
        <p className="mt-1.5 text-xs text-text-muted">
          {t('team.joinNeedFull')}（{code.length}/{CODE_LENGTH}）
        </p>
      )}

      {/* 已经在里面了。在发请求之前就拦下——再 join 一次不会有新东西。 */}
      {already && (
        <div className="mt-2.5 rounded-md border border-border-color bg-bg-subtle p-3">
          <p className="text-xs font-medium">{t('team.joinAlready')}</p>
          <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
            {t('team.joinAlreadyWhy')}
          </p>
          <button
            type="button"
            onClick={() => onGoTo(code)}
            className="mt-2 text-[11px] text-accent-primary hover:underline"
          >
            {t('team.joinAlreadyGo')}
          </button>
        </div>
      )}
    </form>
  );
}

/** 第二步：拿这个码，挑一场会话进去。三类失败各自一套说法。 */
function JoinPick({
  code,
  onDone,
  onBackToCode,
}: {
  code: string;
  onDone: () => void;
  onBackToCode: () => void;
}) {
  const { t } = useTranslation();
  const [trouble, setTrouble] = useState<TeamTrouble | null>(null);
  const [said, setSaid] = useState<string>('');
  const [waitSecs, setWaitSecs] = useState(0);

  // 被限流时倒数。让人对着一个永远点不动的按钮猜要等多久，比不给按钮还糟。
  useEffect(() => {
    if (trouble !== 'busy' || waitSecs <= 0) return;
    const timer = window.setTimeout(() => setWaitSecs((n) => n - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [trouble, waitSecs]);

  const go = async (sessionId: string) => {
    setTrouble(null);
    try {
      await joinTeam(code, sessionId);
    } catch (err) {
      const kind = err instanceof TeamError ? err.trouble : 'relay_down';
      setTrouble(kind);
      setSaid(err instanceof Error ? err.message : String(err));
      if (kind === 'busy') setWaitSecs(RELAY_BUSY_WAIT_SECS);
      throw err;
    }
  };

  if (trouble) {
    return (
      <JoinTroubleCard
        trouble={trouble}
        said={said}
        waitSecs={waitSecs}
        onRetry={() => setTrouble(null)}
        onBackToCode={onBackToCode}
      />
    );
  }

  return (
    <StartTeamPanel
      title={t('team.joinPickTitle')}
      hint={t('team.joinPickHint')}
      confirmLabel={t('team.joinConfirm')}
      lastStepLabel={t('team.joinStepCode')}
      commit={go}
      onDone={onDone}
      onCancel={onBackToCode}
    />
  );
}

/** 被限流之后让人等几秒。与中继那一侧的退避节奏对齐。 */
const RELAY_BUSY_WAIT_SECS = 10;

function JoinTroubleCard({
  trouble,
  said,
  waitSecs,
  onRetry,
  onBackToCode,
}: {
  trouble: TeamTrouble;
  said: string;
  waitSecs: number;
  onRetry: () => void;
  onBackToCode: () => void;
}) {
  const { t } = useTranslation();
  const copy = {
    bad_code: { title: t('team.joinBadCode'), why: t('team.joinBadCodeWhy') },
    relay_down: { title: t('team.joinRelayDown'), why: t('team.joinRelayDownWhy') },
    busy: { title: t('team.joinBusy'), why: t('team.joinBusyCount', { secs: waitSecs }) },
  }[trouble];

  // 码这一类唯一该做的是改那串码，别的两类码没问题，重试才对。
  const canRetry = trouble !== 'bad_code' && !(trouble === 'busy' && waitSecs > 0);

  return (
    <div className="rounded-lg border border-border-color p-4">
      <p className="text-sm font-medium text-accent-error">{copy.title}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-text-muted">{copy.why}</p>

      {/* 中继原话只在「够不着」那一类摆出来——那一句带着地址和底层的网络错误，是排查
          时真用得上的东西。另外两类它只是把上面那句用另一种语言又说了一遍，而它出自
          服务端、恒为中文，摆在英文界面上就是一段没人要的中文。 */}
      {trouble === 'relay_down' && said && (
        <p className="mt-2 font-mono text-[11px] leading-relaxed text-text-dim">{said}</p>
      )}

      <div className="mt-3 flex items-center gap-2">
        {canRetry && (
          <button
            onClick={onRetry}
            className="rounded-md bg-accent-primary px-3 py-1.5 text-xs text-[var(--text-on-accent)]"
          >
            {t('team.joinRetry')}
          </button>
        )}
        <button
          onClick={onBackToCode}
          className="px-2 py-1 text-xs text-text-muted hover:underline"
        >
          {t('team.joinBackToCode')}
        </button>
      </div>
    </div>
  );
}

/** 顶上那条：统一页头。标题、连接码标签，右边「?」与三个中性动作。 */
function TeamBar({
  teams,
  selected,
  onSelect,
  onChanged,
  guideOpen,
  onToggleGuide,
}: {
  teams: TeamBinding[];
  selected: string | null;
  onSelect: (code: string) => void;
  onChanged: () => void;
  guideOpen: boolean;
  onToggleGuide: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [panel, setPanel] = useState<'open' | 'join' | null>(null);

  const leave = async () => {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const reach = await leaveTeam(selected);
      // 没通知到中继也是退出成功——这一句是知会，不是报错，所以不走红字那一档。
      if (reach === 'local-only') setNotice(t('team.leftLocalOnly'));
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const done = () => {
    setPanel(null);
    onChanged();
  };

  const open = panel !== null;
  const btn = (pressed: boolean) => `page-header-btn ${pressed ? 'page-header-btn--pressed' : ''}`;

  return (
    // 展开发起／加入那块之后，这条带可能比它能占的地方还高——小屏上尤其明显，确认
    // 按钮掉在下边缘外面，而外层是 overflow:hidden，怎么划都划不到。所以这里自己
    // 能滚，并且封一个上限，剩下的留给下面两列：把两列挤没，人就看不见自己正在哪
    // 一场会话里挑，而那正是这一步要他判断的东西。
    //
    // 上限按**这一页实际有多高**算（`basis` + `min-h-0`），NEVER 按视口的百分比：
    // 这一页嵌在外壳里，它拿到的高度比视口小，按视口算出来的上限永远够不着，于是
    // 这条规则形同虚设——而且只在小屏上现形。
    <div
      className={
        open ? 'flex min-h-0 basis-2/3 flex-col overflow-y-auto overscroll-contain' : 'shrink-0'
      }
    >
      {/* 这一页没有实心绿的主动作：真正的动作是发送，那一枚绿留给左下的 Send。 */}
      <PageHeader
        title={t('sidebar.nav.teams')}
        meta={
          <span className="inline-flex min-w-0 items-center gap-1.5">
            {teams.map((one) => (
              <CodeChip
                key={one.code}
                binding={one}
                selected={teams.length > 1 && one.code === selected}
                onSelect={() => onSelect(one.code)}
              />
            ))}
          </span>
        }
        secondary={
          <>
            <button
              type="button"
              onClick={onToggleGuide}
              aria-pressed={guideOpen}
              title={t('team.help')}
              aria-label={t('team.help')}
              data-testid="teams-help"
              className={`${btn(guideOpen)} page-header-btn--icon page-header-btn--ghost`}
            >
              <HelpCircle size={14} />
            </button>
            <button
              type="button"
              onClick={() => setPanel(panel === 'open' ? null : 'open')}
              aria-pressed={panel === 'open'}
              title={t('team.openHint')}
              className={`${btn(panel === 'open')} page-header-btn--ghost`}
            >
              <Plus size={14} />
              {t('team.open')}
            </button>
            <button
              type="button"
              onClick={() => setPanel(panel === 'join' ? null : 'join')}
              aria-pressed={panel === 'join'}
              className={`${btn(panel === 'join')} page-header-btn--ghost`}
            >
              <Link2 size={14} />
              {t('team.joinWithCode')}
            </button>
            {selected && (
              <button
                type="button"
                onClick={() => void leave()}
                disabled={busy}
                title={t('team.leaveHint')}
                className={`${btn(false)} page-header-btn--ghost`}
              >
                <LogOut size={14} />
                {t('team.leave')}
              </button>
            )}
          </>
        }
      />

      {panel === 'open' && (
        <div className="border-b border-border-color px-4 py-3">
          <StartTeamPanel onDone={done} onCancel={() => setPanel(null)} />
        </div>
      )}
      {panel === 'join' && (
        <div className="border-b border-border-color px-4 py-3">
          <JoinFlow
            onDone={done}
            onCancel={() => setPanel(null)}
            joined={teams.map((one) => one.code)}
            onGoTo={(code) => {
              onSelect(code);
              setPanel(null);
            }}
          />
        </div>
      )}
      {error && <p className="px-4 py-2 text-xs text-accent-error">{error}</p>}
      {notice && <p className="px-4 py-2 text-xs text-text-muted">{notice}</p>}
    </div>
  );
}

/**
 * 页头上的连接码：一枚中性标签，只露前 4 位，Copy 复制完整码。
 *
 * 码是队友进门的凭证。这一页左栏的内容每 15 秒同步给队友，截图、录屏、投屏也会把屏幕
 * 上的东西一起带走——所以屏幕上NEVER 摆完整码。要把码给人，按 Copy 贴进聊天窗口；
 * 这一步从前靠「码明着摆出来、照着念」，现在靠复制，最常用的那一步仍然只要一下。
 *
 * 几个 team 并排时，点标签切到那一个；选中态整枚换中性底加描边。
 */
function CodeChip({
  binding,
  selected,
  onSelect,
}: {
  binding: TeamBinding;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current) window.clearTimeout(timer.current);
    },
    [],
  );

  const copy = async () => {
    onSelect();
    try {
      await navigator.clipboard.writeText(binding.code);
      setCopied(true);
    } catch {
      // 剪贴板不给用（没有安全上下文、被策略挡住）时不报错：复制失败不该让这一块
      // 看起来坏了。人可以从左栏跑 frago team list 拿到完整码。
      setCopied(false);
    }
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2500);
  };

  return (
    <span
      data-testid="team-code-chip"
      className={`inline-flex h-7 shrink-0 items-center gap-2 rounded-[7px] border pl-2.5 pr-0.5 text-[12px] text-text-muted ${
        selected
          ? 'border-[var(--sel-border)] bg-[var(--sel-bg)]'
          : 'border-border-color'
      }`}
    >
      <button type="button" onClick={onSelect} className="inline-flex items-center gap-2">
        {t('team.codeLabel')}
        <b
          data-testid="team-code"
          className="font-mono text-[12px] font-medium tracking-[0.14em] text-text-primary"
        >
          {maskCode(binding.code)}
        </b>
        <span>· {binding.side === 'A' ? t('team.sideA') : t('team.sideB')}</span>
      </button>
      <button
        type="button"
        onClick={() => void copy()}
        aria-label={`${t('team.codeLabel')} — ${t('team.codeCopy')}`}
        data-testid="team-code-copy"
        className="inline-flex h-[22px] items-center gap-1 rounded-[5px] px-[7px] text-[11px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
      >
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {copied ? t('team.codeCopied') : t('team.codeCopy')}
      </button>
    </span>
  );
}

/**
 * 正文：左边我自己那一场，右边队友那一场。
 *
 * 队友没进来时右边不立列——一列空白顶着他的名字看起来像坏了。那块地方说「他还没进来」，
 * 并把注意力送回顶上那串码。
 *
 * **归属靠整块，不靠边线。** 左栏页面本色、实心中性头像、「You」；右栏整栏冷色底、冷色
 * 头像、「Read-only」。身份头、头像、底色、说话人叫法四处同时说同一件事，NEVER 用单边
 * 竖条或横条区分。
 */
function Paired({
  binding,
  codes,
  rules,
  onRulesSaved,
}: {
  binding: TeamBinding;
  codes: string[];
  rules: RequestRules | null;
  onRulesSaved: (rules: RequestRules) => void;
}) {
  const peer = usePeerRecords(binding.code);
  const here = !!peer.status?.peer_present;

  return (
    <div className="grid min-h-0 flex-1 auto-rows-fr overflow-hidden md:auto-rows-auto md:grid-cols-2">
      <MySide
        binding={binding}
        codes={codes}
        rules={rules}
        onRulesSaved={onRulesSaved}
        pushTrouble={binding.push_trouble ?? ''}
        pushTroubleTransient={!!binding.push_trouble_transient}
      />
      {here ? (
        <PeerSide binding={binding} codes={codes} peer={peer} />
      ) : (
        <PeerAway onRefresh={() => void peer.reload()} />
      )}
    </div>
  );
}

/**
 * 我自己那一场，一整张会话详情。
 *
 * 与会话页上的那一场没有区别：记录流加一个能说话的输入区。从前这一列是只读的，于是
 * 整页唯一能打字的地方在对方那一列底下，人只能在写着别人名字的那半边说话。
 *
 * **队友投来的消息也在这条流里。** 它们经中继落进我这场会话，成为一条带前缀的用户
 * 发言，跟我自己说的话排在一起——画成冷色底的队友请求块，一眼分得出不是我说的。所以
 * 这一列必须能说话：队友让我的 agent 做了一件事，我要在同一个地方看见它、接着它往下说。
 */
function MySide({
  binding,
  codes,
  rules,
  onRulesSaved,
  pushTrouble,
  pushTroubleTransient,
}: {
  binding: TeamBinding;
  codes: string[];
  rules: RequestRules | null;
  onRulesSaved: (rules: RequestRules) => void;
  pushTrouble: string;
  pushTroubleTransient: boolean;
}) {
  const { t } = useTranslation();
  const sessionId = binding.session_id;
  const sessions = useWorkbenchSessions();
  const mine = useWorkbenchRecords(sessionId, { live: true });
  const quoteSeq = useRef(0);
  const [quote, setQuote] = useState<{ text: string; at: number } | null>(null);

  const session = sessions.sessions.find((s) => s.session_id === sessionId) ?? null;
  const familyKey = session?.family ? FAMILY_LABEL_KEY[session.family] : undefined;
  const family = familyKey ? t(familyKey) : '';
  const records = useMemo(() => maskCodes(mine.records, codes), [mine.records, codes]);
  const voice = useMemo(
    () => ({ user: t('team.voice.mineUser'), agent: t('team.voice.mineAgent') }),
    [t],
  );

  // 左栏里带核实行的用户发言画成队友请求块。核实拿本机参加的那个完整码去问，显示
  // 用的是正文里拆出来的原文——前缀、设置行与核实行是给 agent 看的。
  const override = useCallback(
    (record: WorkbenchRecord) => {
      const relayed = parseRelayed(record);
      if (!relayed) return null;
      return (
        <IncomingRequest
          body={relayed.body}
          code={binding.code}
          messageId={relayed.messageId}
          ts={record.ts}
          rules={rules}
        />
      );
    },
    [binding.code, rules],
  );

  // 决定卡片与会话页同一套：答过没有按记录判，点了交给左下输入区。右栏不提供，卡片只读。
  // 左栏总绑着一场会话，输入区没有发不出去的时候，卡片也就没有「不能答」的原因。
  const cards = useDecisionCards({
    sessionId,
    records,
    blockedReason: null,
    onSendStart: mine.markSent,
    onSendFailed: mine.clearSent,
  });

  return (
    <section data-testid="teams-mine" className="flex min-h-0 min-w-0 flex-col bg-bg-primary">
      <IdentityHeader
        who="me"
        title={t('team.you')}
        note={family ? t('team.youWho', { family }) : t('team.youWhoPlain')}
      />
      {/* 推不上去时这一侧照常收消息、看起来一切正常，只有队友那边是空的——他看不到
          原因，所以原因只能摆在这里。服务端只在连续一阵推不上去之后才交出原因。
          没够着中继（网络、握手、限流）会自己好，一行灰字说在重试；中继不收才是要人
          管的，红底附原话。 */}
      {pushTrouble && pushTroubleTransient && (
        <p role="status" className="px-4 pt-2 text-xs text-text-muted" title={pushTrouble}>
          {t('team.pushRetrying')}
        </p>
      )}
      {pushTrouble && !pushTroubleTransient && (
        <div role="alert" className="mx-3 mt-2 rounded-md bg-red-500/10 px-3 py-2 text-xs leading-relaxed text-accent-error">
          <span className="font-medium">{t('team.pushTroubleTitle')}</span>
          <span className="text-text-muted">{t('team.pushTroubleWhy')}</span>
          <div className="mt-1 break-all font-mono">{maskCodesIn(pushTrouble, codes)}</div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <RecordVoiceContext.Provider value={voice}>
          <RecordOverrideContext.Provider value={override}>
            <DecisionCardContext.Provider value={cards.host}>
              <RecordStream
                sessionId={sessionId}
                records={records}
                loading={mine.loading}
                loadingOlder={mine.loadingOlder}
                hasOlder={mine.hasOlder}
                error={mine.error}
                onLoadOlder={() => void mine.loadOlder()}
                awaitingAgent={mine.awaitingAgent}
                onQuote={(text) => setQuote({ text, at: (quoteSeq.current += 1) })}
              />
            </DecisionCardContext.Provider>
          </RecordOverrideContext.Provider>
        </RecordVoiceContext.Provider>
      </div>
      {rules && <MyRulesBar rules={rules} onSaved={onRulesSaved} />}
      <div className="shrink-0 border-t border-border-color">
        <p className="flex min-w-0 items-center gap-[7px] whitespace-nowrap px-[14px] pt-2.5 text-[12px] font-semibold">
          <TeamAvatar who="me" size="sm" />
          {t('team.talkTitle')}
          <span className="min-w-0 truncate text-[11px] font-normal text-text-muted">
            {family ? t('team.talkWho', { family }) : t('team.talkWhoPlain')}
          </span>
        </p>
        <Composer
          sessionId={sessionId}
          family={session?.family ?? null}
          running={session?.status === 'running' || mine.awaitingAgent}
          onSendStart={cards.onSendStart}
          onSendFailed={cards.onSendFailed}
          deliveredAt={mine.deliveredAt}
          outbound={mine.outbound}
          quote={quote}
          answer={cards.answer}
          onSent={(outboundId) => {
            void mine.reload();
            void sessions.reload();
            mine.settleSent(outboundId);
          }}
        />
        <p
          data-testid="teams-leak-note"
          className="flex items-start gap-1.5 px-[14px] pb-2.5 text-[11px] leading-[1.45] text-text-muted"
        >
          <Eye size={13} className="mt-px shrink-0 text-accent-warning" />
          <span>{t('team.leakNote')}</span>
        </p>
      </div>
    </section>
  );
}

/** 队友还没进来时右边那块。 */
function PeerAway({ onRefresh }: { onRefresh: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="flex min-h-0 min-w-0 flex-col border-l border-border-color bg-[var(--peer-bg)]">
      <IdentityHeader
        who="peer"
        title={t('team.peer')}
        note={t('team.peerWho')}
        action={
          <button
            onClick={onRefresh}
            className="rounded-md p-1 text-text-muted hover:bg-bg-hover"
            title={t('team.refresh')}
          >
            <RefreshCw {...ICON} />
          </button>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-8 text-center">
        <UserPlus size={22} strokeWidth={1.5} className="text-text-muted" />
        <p className="text-sm font-medium">{t('team.peerAwayTitle')}</p>
        <p className="max-w-xs text-xs leading-relaxed text-text-muted">{t('team.peerAwayWhy')}</p>
      </div>
    </section>
  );
}

/** 发出 10 分钟仍未见送达，卡片加一句「还没进对方的会话」。 */
const STALE_AFTER_MS = 10 * 60_000;

/** 我发出、还没在对方记录里找到的请求，挂在右栏流末尾时用的记录编号前缀。 */
const PENDING_PREFIX = 'team-pending:';

/**
 * 队友进来之后右边那一列：他那一场的记录，加一个给他的 agent 下事情的入口。
 *
 * 他会话里那条带核实行的用户发言（我发过去的请求）画成「Your request」卡，步骤从两侧
 * 已有的记录推。本页刚发出、对方记录还没带回来的那几条挂在流末尾，同一张卡、停在 Sent；
 * 这份待核对清单只活在这一页的内存里，刷新就丢——丢了以后那条请求等对方记录带回来时
 * 从 Delivered 起画，发出记录没有别处可存，而对方记录迟早会带回来。
 */
function PeerSide({
  binding,
  codes,
  peer,
}: {
  binding: TeamBinding;
  codes: string[];
  peer: ReturnType<typeof usePeerRecords>;
}) {
  const { t } = useTranslation();
  const silent = peer.records.length === 0;
  const [sent, setSent] = useState<SentRequest[]>([]);
  const sentSeq = useRef(0);
  const [now, setNow] = useState(() => Date.now());

  // 换 team 时清掉上一个 team 的待核对清单。
  useEffect(() => setSent([]), [binding.code]);

  // 有还没送达的请求时每分钟看一眼钟，让「还没进对方的会话」那一句按时出现。
  const waiting = sent.length > 0;
  useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [waiting]);

  const peerRules = peer.status?.peer_rules ?? null;
  const rules = peerRules ?? FRAGO_DEFAULT_RULES;
  const source: RulesSource = peerRules ? 'teammate' : 'frago';

  const records = useMemo(() => maskCodes(peer.records, codes), [peer.records, codes]);

  // 每条本页发出的请求此刻走到哪；已经在对方记录里找到的，按那条记录的编号挂上去。
  const progress = useMemo(() => {
    const byRecord = new Map<string, { request: SentRequest; steps: RequestProgress['steps'] }>();
    const pending: { request: SentRequest; steps: RequestProgress['steps'] }[] = [];
    for (const request of sent) {
      const got = stepsFor(request, records);
      if (got.deliveredRecordId) byRecord.set(got.deliveredRecordId, { request, steps: got.steps });
      else pending.push({ request, steps: got.steps });
    }
    return { byRecord, pending };
  }, [sent, records]);

  // 还没送达的挂在流末尾。给它们一条假的用户发言占位，这样它们跟真实记录走同一条
  // 渲染与跟到底的路，不必在记录流组件里另开一个口子。
  const shown = useMemo(() => {
    if (!progress.pending.length) return records;
    const tail = progress.pending.map(({ request }, i): WorkbenchRecord => ({
      id: `${PENDING_PREFIX}${request.key}`,
      session_id: binding.code,
      group_id: null,
      seq: Number.MAX_SAFE_INTEGER - progress.pending.length + i,
      ts: request.sentAt,
      kind: 'user.say',
      agent_path: [],
      payload: { text: request.text },
      raw_available: false,
    }));
    return [...records, ...tail];
  }, [records, progress.pending, binding.code]);

  const footFor = (text: string, step: RequestStep, sentAt: number | null): string | null => {
    const guess = classifyTier(text);
    const tier = guess.tier === 'idle' ? 'read' : guess.tier;
    const verdict = verdictOf(tier, rules);
    if (step === 'sent' && sentAt !== null && now - sentAt > STALE_AFTER_MS) {
      return t('team.request.stale');
    }
    if (step === 'replied') return null;
    if (step === 'waiting_owner') return t('team.request.footWaiting');
    if (verdict === 'refuse') {
      return tier === 'never' ? t('team.request.footNever') : t('team.request.footRefuse');
    }
    return step === 'on_it' ? t('team.request.footOnIt') : null;
  };

  const override = useCallback(
    (record: WorkbenchRecord) => {
      if (record.id.startsWith(PENDING_PREFIX)) {
        const key = record.id.slice(PENDING_PREFIX.length);
        const hit = progress.pending.find((one) => one.request.key === key);
        if (!hit) return null;
        return (
          <RequestCard
            text={hit.request.text}
            steps={hit.steps}
            foot={footFor(hit.request.text, 'sent', hit.request.sentAt)}
          />
        );
      }
      const relayed = parseRelayed(record);
      if (!relayed) return null;
      const mineHit = progress.byRecord.get(record.id);
      const index = records.findIndex((one) => one.id === record.id);
      const steps = mineHit?.steps ?? stepsForRelayed(records, index, null);
      const current = steps[steps.length - 1].step;
      return (
        <RequestCard text={relayed.body} steps={steps} foot={footFor(relayed.body, current, null)} />
      );
    },
    // footFor 只读 rules、now 与 t，已经列在下面
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [progress, records, rules, now, t],
  );

  const voice = useMemo(
    () => ({ user: t('team.voice.peerUser'), agent: t('team.voice.peerAgent') }),
    [t],
  );

  return (
    <section
      data-testid="teams-peer"
      className="flex min-h-0 min-w-0 flex-col border-l border-border-color bg-[var(--peer-bg)]"
    >
      <IdentityHeader
        who="peer"
        title={t('team.peer')}
        tag={t('team.readOnly')}
        note={silent ? t('team.peerSilent') : t('team.peerWho')}
        action={
          <button
            onClick={() => void peer.reload()}
            className="rounded-md p-1 text-text-muted hover:bg-bg-hover"
            title={t('team.refresh')}
          >
            <RefreshCw {...ICON} />
          </button>
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <RecordVoiceContext.Provider value={voice}>
          <RecordOverrideContext.Provider value={override}>
            <RecordStream
              sessionId={binding.code}
              records={shown}
              loading={peer.loading}
              loadingOlder={false}
              hasOlder={false}
              error={peer.error}
              onLoadOlder={() => {}}
            />
          </RecordOverrideContext.Provider>
        </RecordVoiceContext.Provider>
      </div>
      <Instruct
        code={binding.code}
        rules={rules}
        source={source}
        onSent={(text, messageId) => {
          sentSeq.current += 1;
          setSent((was) => [
            ...was,
            { key: String(sentSeq.current), text, sentAt: Date.now(), messageId: messageId || undefined },
          ]);
          void peer.reload();
        }}
      />
    </section>
  );
}

/**
 * 两列的身份头。两边同一个高度、同一套字号，左右才对得齐。
 *
 * 左「You · Your agent · Claude Code · this machine」配实心中性头像；右「Teammate」配冷色
 * 头像与「Read-only」标签、「Their agent's session · synced every 15 s」。
 */
function IdentityHeader({
  who,
  title,
  tag,
  note,
  action,
}: {
  who: 'me' | 'peer';
  title: string;
  tag?: string;
  note?: string;
  action?: React.ReactNode;
}) {
  return (
    <header
      data-testid={`identity-${who}`}
      className="flex h-[52px] shrink-0 items-center gap-[9px] border-b border-border-color px-[14px]"
    >
      <TeamAvatar who={who} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-[7px] text-[13px] font-semibold leading-[1.35]">
          {title}
          {tag ? (
            <span className="inline-flex h-[18px] items-center gap-1 rounded-full bg-[var(--peer-chip)] px-[7px] text-[11px] font-medium text-[var(--peer-ink)]">
              <Eye size={11} />
              {tag}
            </span>
          ) : null}
        </div>
        {note ? <div className="truncate text-[11px] leading-[1.35] text-text-muted">{note}</div> : null}
      </div>
      {action}
    </header>
  );
}

/**
 * 给队友的 agent 下一件事。
 *
 * **这不是聊天框。** 打出去的话落在队友的会话里，成为他那边的一条用户发言，前面带一句
 * 说明它来自我。所以它有自己的标题（带冷色小头像，写明「约 15 秒后落进去」），和左边
 * 那个「跟我自己的 agent 说话」长得不一样——两个框长同一个样子，人分不出自己此刻在跟
 * 谁说话。
 *
 * **发之前就告诉人会发生什么。** 输入框上方三格是对方主人定的处理方式，按正在写的这句
 * 点亮一格；发送键左边一句话说依据。从前这里是一行「他那边看到的是」前缀预览——三格与
 * 那句预判已经交代了对方会怎么看待这句话，前缀预览再占一行，删了。
 *
 * 这一屏唯一的实心绿给左下的 Send，这里的 Send 是中性的。
 */
function Instruct({
  code,
  rules,
  source,
  onSent,
}: {
  code: string;
  rules: RequestRules;
  source: RulesSource;
  onSent: (text: string, messageId: string) => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const guess = useMemo(() => classifyTier(text), [text]);

  const submit = async () => {
    const body = text.trim();
    if (!body || busy) return;
    setBusy(true);
    setError(null);
    try {
      const messageId = await sendToPeer(code, body);
      setText('');
      onSent(body, messageId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="teams-instruct" className="shrink-0 border-t border-border-color px-[14px] pb-3 pt-2.5">
      <p className="flex min-w-0 items-center gap-[7px] whitespace-nowrap text-[12px] font-semibold">
        <TeamAvatar who="peer" size="sm" />
        {t('team.instructTitle')}
        <span className="min-w-0 truncate text-[11px] font-normal text-text-muted">
          {t('team.instructWhen')}
        </span>
      </p>
      <PeerTiers rules={rules} source={source} guess={guess} />
      <div className="mt-[7px] rounded-lg border border-border-color bg-bg-primary px-2.5 py-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit();
          }}
          rows={2}
          placeholder={t('team.instructPlaceholder')}
          className="block w-full resize-none border-0 bg-transparent text-[13px] leading-[1.5] text-text-primary outline-none placeholder:text-text-muted"
        />
        <div className="mt-1.5 flex items-center gap-2.5">
          <Prediction guess={guess} rules={rules} />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy || !text.trim()}
            data-testid="teams-instruct-send"
            className="page-header-btn shrink-0 self-end"
          >
            <Send size={13} />
            {t('team.instructSend')}
          </button>
        </div>
      </div>
      {error && <p className="mt-1.5 text-xs text-accent-error">{maskCodesIn(error, [code])}</p>}
    </div>
  );
}
