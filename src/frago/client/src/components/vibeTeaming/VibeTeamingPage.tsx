/**
 * vibe teaming：我这一场会话，旁边是队友那一场。
 *
 * ## 这一页的骨架
 *
 * **连接码常驻顶部，随时可复制。** 它是队友进门的唯一凭证，也是这一页从头到尾都用得上
 * 的东西——一个人的时候要把它发出去，两个人之后要认出自己在哪个 team 里。
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

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy, Link2, LogOut, Plus, RefreshCw, Send, UserPlus, Users } from 'lucide-react';

import RecordStream from '@/components/sessionWorkbench/RecordStream';
import Composer from '@/components/sessionWorkbench/Composer';
import StartTeamPanel from '@/components/vibeTeaming/StartTeamPanel';
import { useWorkbenchRecords } from '@/hooks/useWorkbenchRecords';
import { useWorkbenchSessions } from '@/hooks/useWorkbenchSessions';
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
      <TeamBar teams={active} selected={selected} onSelect={setSelected} onChanged={reload} />
      {binding && <Paired binding={binding} prefix={state?.prefix ?? ''} />}
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

/** 顶上那条：连接码在左，动作在右。 */
function TeamBar({
  teams,
  selected,
  onSelect,
  onChanged,
}: {
  teams: TeamBinding[];
  selected: string | null;
  onSelect: (code: string) => void;
  onChanged: () => void;
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
      className={`${
        open ? 'flex min-h-0 basis-2/3 flex-col overflow-y-auto overscroll-contain' : 'shrink-0'
      } border-b border-border-color`}
    >
      <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
        {teams.map((one) => (
          <CodeBlock
            key={one.code}
            binding={one}
            selected={one.code === selected}
            onSelect={() => onSelect(one.code)}
          />
        ))}

        <div className="ml-auto flex items-center gap-1">
          <BarAction
            icon={<Plus {...ICON} />}
            label={t('team.open')}
            title={t('team.openHint')}
            active={panel === 'open'}
            onClick={() => setPanel(panel === 'open' ? null : 'open')}
          />
          <BarAction
            icon={<Link2 {...ICON} />}
            label={t('team.joinWithCode')}
            active={panel === 'join'}
            onClick={() => setPanel(panel === 'join' ? null : 'join')}
          />
          {selected && (
            <BarAction
              icon={<LogOut {...ICON} />}
              label={t('team.leave')}
              title={t('team.leaveHint')}
              onClick={() => void leave()}
              disabled={busy}
            />
          )}
        </div>
      </div>

      {panel === 'open' && (
        <div className="px-4 pb-3">
          <StartTeamPanel onDone={done} onCancel={() => setPanel(null)} />
        </div>
      )}
      {panel === 'join' && (
        <div className="px-4 pb-3">
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
      {error && <p className="px-4 pb-2 text-xs text-accent-error">{error}</p>}
      {notice && <p className="px-4 pb-2 text-xs text-text-muted">{notice}</p>}
    </div>
  );
}

/**
 * 顶栏上的连接码：明文摆着，一按就复制。
 *
 * 它是队友进门的唯一凭证，而这一页的人要做的第一件事就是把它发出去。藏起来、要点一下
 * 才露的做法，等于在最常用的那一步上加一道；这串码本来就要被念给人听、贴进聊天窗口。
 */
function CodeBlock({
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
      // 剪贴板不给用（没有安全上下文、被策略挡住）时码照样在屏幕上，人自己选中复制。
      // 这里不报错：复制失败不该让这一块看起来坏了。
      setCopied(false);
    }
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2500);
  };

  return (
    <button
      onClick={() => void copy()}
      aria-label={`${t('team.codeLabel')} ${binding.code} — ${t('team.codeCopy')}`}
      className={`rounded-lg border px-3 py-1.5 text-left transition-shadow ${
        selected
          ? 'border-border-accent bg-bg-hover ring-2 ring-accent-primary-20'
          : 'border-border-color hover:bg-bg-hover'
      }`}
    >
      <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-text-muted">
        {t('team.codeLabel')}
        <span className="normal-case tracking-normal">
          · {binding.side === 'A' ? t('team.sideA') : t('team.sideB')}
        </span>
      </span>
      <span className="mt-0.5 flex items-center gap-2">
        <span className="font-mono text-base font-semibold tracking-[0.2em]">{binding.code}</span>
        <span className="flex items-center gap-1 text-[11px] font-normal text-text-muted">
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? t('team.codeCopied') : t('team.codeCopy')}
        </span>
      </span>
    </button>
  );
}

function BarAction({
  icon,
  label,
  title,
  active,
  disabled,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  title?: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-pressed={active}
      className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs hover:bg-bg-hover disabled:opacity-40 ${
        active ? 'bg-bg-hover text-text-primary' : 'text-text-muted'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

/**
 * 正文：左边我自己那一场，右边队友那一场。
 *
 * 队友没进来时右边不立列——一列空白顶着他的名字看起来像坏了。那块地方说「他还没进来」，
 * 并把注意力送回顶上那串码。
 */
function Paired({ binding, prefix }: { binding: TeamBinding; prefix: string }) {
  const peer = usePeerRecords(binding.code);
  const here = !!peer.status?.peer_present;

  return (
    <div className="grid min-h-0 flex-1 auto-rows-fr gap-px overflow-hidden bg-border-color md:auto-rows-auto md:grid-cols-2">
      <MySide
        sessionId={binding.session_id}
        pushTrouble={binding.push_trouble ?? ''}
        pushTroubleTransient={!!binding.push_trouble_transient}
      />
      {here ? (
        <PeerSide binding={binding} prefix={prefix} peer={peer} />
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
 * 发言，跟我自己说的话排在一起。所以这一列必须能说话：队友让我的 agent 做了一件事，
 * 我要在同一个地方看见它、接着它往下说。
 */
function MySide({
  sessionId,
  pushTrouble,
  pushTroubleTransient,
}: {
  sessionId: string;
  pushTrouble: string;
  pushTroubleTransient: boolean;
}) {
  const { t } = useTranslation();
  const sessions = useWorkbenchSessions();
  const mine = useWorkbenchRecords(sessionId, { live: true });
  const quoteSeq = useRef(0);
  const [quote, setQuote] = useState<{ text: string; at: number } | null>(null);

  const session = sessions.sessions.find((s) => s.session_id === sessionId) ?? null;

  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-bg-card">
      <ColumnHeader title={t('team.mine')} note={session?.title ?? undefined} />
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
          <div className="mt-1 break-all font-mono">{pushTrouble}</div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <RecordStream
          sessionId={sessionId}
          records={mine.records}
          loading={mine.loading}
          loadingOlder={mine.loadingOlder}
          hasOlder={mine.hasOlder}
          error={mine.error}
          onLoadOlder={() => void mine.loadOlder()}
          awaitingAgent={mine.awaitingAgent}
          onQuote={(text) => setQuote({ text, at: (quoteSeq.current += 1) })}
        />
      </div>
      <Composer
        sessionId={sessionId}
        family={session?.family ?? null}
        running={session?.status === 'running' || mine.awaitingAgent}
        onSendStart={mine.markSent}
        onSendFailed={mine.clearSent}
        deliveredAt={mine.deliveredAt}
        outbound={mine.outbound}
        quote={quote}
        onSent={(outboundId) => {
          void mine.reload();
          void sessions.reload();
          mine.settleSent(outboundId);
        }}
      />
    </section>
  );
}

/** 队友还没进来时右边那块。 */
function PeerAway({ onRefresh }: { onRefresh: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-bg-card">
      <ColumnHeader
        title={t('team.peer')}
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

/** 队友进来之后右边那一列：他那一场的记录，加一个给他的 agent 下事情的入口。 */
function PeerSide({
  binding,
  prefix,
  peer,
}: {
  binding: TeamBinding;
  prefix: string;
  peer: ReturnType<typeof usePeerRecords>;
}) {
  const { t } = useTranslation();
  const silent = peer.records.length === 0;

  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-bg-card">
      <ColumnHeader
        title={t('team.peer')}
        note={silent ? t('team.peerSilent') : undefined}
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
        <RecordStream
          sessionId={binding.code}
          records={peer.records}
          loading={peer.loading}
          loadingOlder={false}
          hasOlder={false}
          error={peer.error}
          onLoadOlder={() => {}}
        />
      </div>
      <Instruct code={binding.code} prefix={prefix} onSent={() => void peer.reload()} />
    </section>
  );
}

/** 两列的列头。两边同一个高度、同一套字号，左右才对得齐。 */
function ColumnHeader({
  title,
  note,
  action,
}: {
  title: string;
  note?: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex h-9 shrink-0 items-center gap-2 border-b border-border-color px-3">
      <span className="shrink-0 text-xs font-medium">{title}</span>
      {note && <span className="min-w-0 truncate text-[11px] text-text-muted">· {note}</span>}
      <span className="flex-1" />
      {action}
    </header>
  );
}

/**
 * 给队友的 agent 下一件事。
 *
 * **这不是聊天框。** 打出去的话落在队友的会话里，成为他那边的一条用户发言，前面带一句
 * 说明它来自我。所以它有自己的标题、写明这句话去哪儿，和左边那个「跟我自己的 agent
 * 说话」长得不一样——两个框长同一个样子，人分不出自己此刻在跟谁说话。
 *
 * 那句前缀只在打了字之后作一次预览。它描述的是「我的话在队友屏幕上长什么样」，常驻在
 * 我眼前的话，读起来像有人在对我说话，而主语还是别人。
 */
function Instruct({
  code,
  prefix,
  onSent,
}: {
  code: string;
  prefix: string;
  onSent: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await sendToPeer(code, text.trim());
      setText('');
      onSent();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="shrink-0 border-t border-border-color bg-bg-subtle p-3">
      <p className="flex items-center gap-1.5 text-[11px] font-medium">
        <Send size={12} strokeWidth={1.5} />
        {t('team.instructTitle')}
      </p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">{t('team.instructWhy')}</p>

      <div className="mt-2 flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit();
          }}
          rows={2}
          placeholder={t('team.instructPlaceholder')}
          className="min-w-0 flex-1 resize-none rounded-md border border-border-color bg-bg-card px-2 py-1.5 text-sm"
        />
        <button
          onClick={() => void submit()}
          disabled={busy || !text.trim()}
          className="self-end rounded-md bg-accent-primary px-3 py-1.5 text-xs text-[var(--text-on-accent)] disabled:opacity-40"
        >
          {t('team.instructSend')}
        </button>
      </div>

      {/* 打了字才预览。空着的时候摆一行别人口气的话，读起来像有人在对我说话。 */}
      {text.trim() && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
          {t('team.instructPreview')}：
          <span className="italic">
            {prefix.replace('{code}', code)}
            {text.trim()}
          </span>
        </p>
      )}
      {error && <p className="mt-1.5 text-xs text-accent-error">{error}</p>}
    </div>
  );
}
