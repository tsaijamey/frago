/**
 * SessionWorkbenchPage — 会话页的页面壳，三栏布局。
 *
 * 它是 webUI 里**唯一**的会话入口。旧的单栏会话页已经下线，那一页上还值钱的五件事
 * （搜索、时间范围、新建会话、复制恢复命令、用量月历）整个搬了进来，其余的按来源筛、
 * 重新扫描、PA 列表、未读徽章、后台保活一并去掉。导航上这一项叫「会话」，
 * `workbench` 只是内部代号，界面上不出现。
 *
 * | 栏 | 本质 | 本次做到哪 |
 * |---|---|---|
 * | 左 | 索引 | 真数据。两家会话都出现 |
 * | 中 | 流 | 真数据。十五种形态无损呈现 |
 * | 右 | 面 | 真数据。旁路 AI 每轮在服务端填，切换会话打断不了它 |
 *
 * 中栏走 `minmax(0, …)`、三栏各自 `min-w-0`。这两条是页面不横向滚的地基——少任何一条，
 * 一条长命令就能把整个版面顶宽。
 */

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ChevronLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import SessionRail from './SessionRail';
import RecordStream from './RecordStream';
import ReportPanel from './ReportPanel';
import StackPanel, { marksAboard, quotesAboard, type LocateState } from './StackPanel';
import Composer, { blockReason, type ComposerNotice } from './Composer';
import { squeeze, type MarkAnchor } from './SelectionQuote';
import { DecisionCardContext } from './DecisionCard';
import { useDecisionCards } from '@/hooks/useDecisionCards';
import SessionLaunchPanel from './SessionLaunchPanel';
import SessionMenu from './SessionMenu';
import { useSessionPins } from '@/hooks/useSessionPins';
import { useWorkbenchSessions } from '@/hooks/useWorkbenchSessions';
import { trailSettled, useWorkbenchRecords } from '@/hooks/useWorkbenchRecords';
import { useSessionViews } from '@/hooks/useSessionViews';
import { useForYou } from '@/hooks/useForYou';
import { formatClock, formatDuration } from './RecordCard';
import { shortAge } from './SessionItem';
import { loadYaml, trailingDecision, yamlNow } from '@/utils/decisionBlock';
import { useSessionLaunch } from '@/hooks/useSessionLaunch';
import { useReportWidth } from '@/hooks/useReportLayout';
import { useSessionMarks, type WorkbenchMark } from '@/hooks/useSessionMarks';
import { usePageStore } from '@/stores/pageStore';
import { useAppStore } from '@/stores/appStore';
import { fetchPending, handoffSession, waitForSession } from '@/hooks/useAgentClients';
import { closeBranch, startBranch } from '@/api';

/**
 * 起分支之后输入框上方那一行说到哪一步了。只属于起分支的那场会话（`parent`），切走就撤。
 *
 * - starting：请求在路上，或者分支会话的编号还在等认领；
 * - ready：起来了，关联也记上了，给「打开」；
 * - unrecorded：分支起来了，但编号没认到（或关系账没写上），关联没记上；
 * - failed：没起来，换成失败原因。
 */
interface BranchNotice {
  parent: string;
  state: 'starting' | 'ready' | 'unrecorded' | 'failed';
  title?: string;
  child?: string | null;
  reason?: string;
  /** 分支起来了、关联记上了，但这场主线存不了标注（CoreAgent 那一家），原文上不画线。 */
  markNotSaved?: boolean;
}

/** 分支会话里「带回主线」要带走的那一份：切回哪一场、哪一条分支、最后一段回复。 */
interface BringBack {
  parent: string;
  child: string;
  text: string;
}

export default function SessionWorkbenchPage() {
  // 选中记在页面导航状态里，切去别的菜单再回来还停在那一场上。
  const selectedId = usePageStore((s) => s.workbenchSessionId);
  const setWorkbenchSessionId = usePageStore((s) => s.setWorkbenchSessionId);
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);
  /**
   * 「For you」要会话清单才判得出，清单的「For you N」档又要那份判定——两头互相要。
   * 判定先经一格状态交给清单（晚一拍，15 秒一轮的东西不在乎这一拍）。
   */
  const [isForYou, setIsForYou] = useState<(id: string) => boolean>(() => () => false);
  const sessions = useWorkbenchSessions(isForYou);
  const views = useSessionViews();
  const pins = useSessionPins();
  /**
   * 选中那场最后一条 agent 回复末尾留了一张合法的「要人拍板」卡片：左栏那一条的预览换成
   * 卡片的问题（第五轮起不再加重）。解析与校验用 decision-cards 那边的同一个函数，这里不另写。
   * 区块写坏的不换（`result.ok` 为假）。只判选中那一场——别的会话手上没有记录。
   */
  const [yamlReady, setYamlReady] = useState(() => yamlNow() !== null);
  useEffect(() => {
    if (yamlReady) return;
    let alive = true;
    void loadYaml().then(() => alive && setYamlReady(true));
    return () => {
      alive = false;
    };
  }, [yamlReady]);
  const [cardQuestion, setCardQuestion] = useState<{ sid: string; question: string } | null>(null);
  const decisionCardOf = useCallback(
    (sid: string) => (cardQuestion && cardQuestion.sid === sid ? cardQuestion.question : null),
    [cardQuestion]
  );
  const forYou = useForYou(sessions.sessions, views.viewedAt, decisionCardOf);
  useEffect(() => {
    setIsForYou(() => (id: string) => forYou.infoOf(id) !== null);
  }, [forYou]);
  // 右栏多宽由人拖出来，记在这个浏览器里；没拖过就用下面网格里写的默认列宽。
  const report = useReportWidth();
  const selected = sessions.sessions.find((s) => s.session_id === selectedId) ?? null;
  // 还在跑的会话让中栏自己活起来：文件一动服务端就推增量，轮询只是断连时的兜底。
  const {
    records,
    recordsSessionId,
    loading,
    loadingOlder,
    hasOlder,
    error,
    loadOlder,
    reload,
    awaitingAgent,
    outbound,
    deliveredAt,
    markSent,
    clearSent,
    settleSent,
    trails,
  } = useWorkbenchRecords(selectedId, { live: selected?.status === 'running' });

  useEffect(() => {
    if (!selectedId || recordsSessionId !== selectedId || !yamlReady) {
      setCardQuestion(null);
      return;
    }
    let last: string | null = null;
    for (let i = records.length - 1; i >= 0; i -= 1) {
      const r = records[i];
      if (r.agent_path.length) continue;
      if (r.kind === 'user.say') break;
      if (r.kind === 'agent.say') {
        last = typeof r.payload.text === 'string' ? r.payload.text : '';
        break;
      }
    }
    const card = last ? trailingDecision(last) : null;
    setCardQuestion(card && card.result.ok ? { sid: selectedId, question: card.result.block.question } : null);
  }, [records, recordsSessionId, selectedId, yamlReady]);

  /** 输入区「Show」要把记录流滚到的那一条。 */
  const [scrollTarget, setScrollTarget] = useState<{ recordId: string; at: number } | null>(null);
  useEffect(() => setScrollTarget(null), [selectedId]);

  /**
   * 页头第二行与左栏跟着这一句话本地先变，不等清单那 15 秒一刷：
   * 「Sending your message」→「● Agent on it · 41 s」→「Answered 13:05:38」。
   * 这一场挂着 For you 时前面加「For you ·」，没有进行中的话就是「For you · waiting 44 min」。
   */
  const latestTrail = useMemo(() => {
    for (let i = trails.length - 1; i >= 0; i -= 1) if (!trails[i].expired) return trails[i];
    return null;
  }, [trails]);
  const inFlight = latestTrail !== null && !trailSettled(latestTrail);
  const sendingId =
    selectedId && outbound.some((m) => m.state === 'sent') ? selectedId : null;
  const busyId = selectedId && inFlight ? selectedId : null;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!inFlight) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(id);
  }, [inFlight]);
  const selectedForYou = selectedId ? forYou.infoOf(selectedId) : null;
  const headStatus = useMemo(() => {
    const prefix = selectedForYou ? `${t('workbench.forYou.label')} · ` : '';
    if (latestTrail && inFlight) {
      const landed =
        latestTrail.steps.in_the_session !== undefined || latestTrail.steps.queued !== undefined;
      if (!landed) return { live: false, text: t('workbench.page.sending') };
      const since = latestTrail.steps.on_its_way ?? now;
      return {
        live: true,
        text: t('workbench.page.agentOnIt', { duration: formatDuration(Math.max(0, now - since)) }),
      };
    }
    const answered = latestTrail?.steps.answered;
    if (answered !== undefined && !(selectedForYou && selectedForYou.waitingSince > answered + 5_000)) {
      return {
        live: false,
        text: prefix
          ? `${prefix}${t('workbench.page.answeredAt', { time: formatClock(answered) })}`
          : t('workbench.page.answeredAtStart', { time: formatClock(answered) }),
      };
    }
    if (selectedForYou) {
      return {
        live: false,
        text: `${prefix}${t('workbench.page.waiting', { age: shortAge(selectedForYou.waitingSince, now) })}`,
      };
    }
    return null;
  }, [latestTrail, inFlight, now, selectedForYou, t]);

  /**
   * 这场会话的标注：引用过、暂存过的那些文字。存在服务端的会话备份目录里，记录流按它
   * 着色，右栏下半按它列暂存。
   */
  const marks = useSessionMarks(selectedId);
  const marksRef = useRef<WorkbenchMark[]>(marks.marks);
  marksRef.current = marks.marks;

  /**
   * 暂存条目「用过了」的判定：点了「填入」只算**待发出**（只在内存里）；随后这场会话从
   * 输入框发出成功一次，才把那几条标成用过。填了不发、切走会话，都不算。
   *
   * 出门那一刻再核一遍：只有发出去的那句话里**确实还带着这条原文**的才算用上——填进去
   * 之后又删掉、改填了别的，那条就没用上，留在待发出里。一次发出之前填了好几条，这几条
   * 都带着就都算。
   */
  const [pendingUse, setPendingUse] = useState<string[]>([]);
  const pendingUseRef = useRef<string[]>([]);
  pendingUseRef.current = pendingUse;
  /**
   * 信封编号 → 这一单是哪一场发的、带出去了哪几条暂存。接口回来成功才标用过，失败退回
   * 待发出。换会话**不清**这份：接口要等整整一轮才回来，人发完就切去别处是常事，回来时
   * 照样要把那一场的那几条标上。
   */
  const riding = useRef(new Map<string, { sid: string; ids: string[] }>());
  // 换会话只清待发出：填了还没发的，切走就不算。
  useEffect(() => setPendingUse([]), [selectedId]);

  /**
   * 引用的留痕时机与暂存「用过了」同一个道理：点「引用」只把原文填进输入框，那一刻
   * **不**记标注——填进去之后删掉、改写、或者干脆没发，那段话就没被回应过，涂上「回应过
   * 了」的底色是在说假话，而且刷新也撤不掉。点了只记成待发出（只在内存里）；这场会话发出
   * 成功、发出去的那句话里还带着那段原文，才落成引用标注。
   */
  const [pendingQuotes, setPendingQuotes] = useState<MarkAnchor[]>([]);
  const pendingQuotesRef = useRef<MarkAnchor[]>([]);
  pendingQuotesRef.current = pendingQuotes;
  /** 信封编号 → 这一单是哪一场发的、带出去了哪几段引用。与 `riding` 同一个道理。 */
  const ridingQuotes = useRef(new Map<string, { sid: string; anchors: MarkAnchor[] }>());
  useEffect(() => setPendingQuotes([]), [selectedId]);

  /** 这一单带出去的引用落成标注。同一单只落一次——见下面 `landOutbound`。 */
  const { addMarks, markUsed } = marks;
  const landQuotes = useCallback(
    (outboundId: string) => {
      const quoted = ridingQuotes.current.get(outboundId);
      if (!quoted) return;
      ridingQuotes.current.delete(outboundId);
      addMarks(
        quoted.anchors.map((a) => ({ kind: 'quote' as const, ...a })),
        quoted.sid
      );
    },
    [addMarks]
  );

  /**
   * 带回主线那一份（见下面 `bringBack`）：切过去之前先记在这里，到了原会话再填进输入框；
   * 填进去之后转成「待收口」，那一句发出成功才收口。
   */
  const bringBackRef = useRef<BringBack | null>(null);
  const [pendingClose, setPendingClose] = useState<BringBack | null>(null);
  const pendingCloseRef = useRef<BringBack | null>(null);
  pendingCloseRef.current = pendingClose;
  /** 信封编号 → 这一单发出成功后要收口的那条分支。与暂存的 `riding` 同一个道理。 */
  const ridingBranch = useRef(new Map<string, BringBack>());

  /**
   * 原位保留哪一场：人在选中的那张卡上发出了消息。切到别的会话那一刻放开，它回到该在的
   * 位置（见 `SessionRail` 的 `HeldSlot`）。
   */
  const [holdId, setHoldId] = useState<string | null>(null);
  useEffect(() => setHoldId(null), [selectedId]);

  /**
   * 发出那一刻这一场离开 For you——这是它唯一由人触发的出口。左栏那张卡原位不动，状态行
   * 换成 Sending → Agent on it，切走才归位。
   */
  const onSendStart = useCallback(
    (text: string, attachments: number) => {
      if (selectedId) {
        forYou.suppress(selectedId);
        setHoldId(selectedId);
      }
      const id = markSent(text, attachments);
      const aboard = marksAboard(text, pendingUseRef.current, marksRef.current);
      if (id && selectedId && aboard.length) {
        riding.current.set(id, { sid: selectedId, ids: aboard });
        setPendingUse((prev) => prev.filter((mid) => !aboard.includes(mid)));
      }
      const quoted = quotesAboard(text, pendingQuotesRef.current);
      if (id && selectedId && quoted.length) {
        ridingQuotes.current.set(id, { sid: selectedId, anchors: quoted });
        setPendingQuotes((prev) => prev.filter((q) => !quoted.includes(q)));
      }
      // 带回主线的那段回复还在这句话里，这一单发出成功就收口。
      const back = pendingCloseRef.current;
      if (id && back && back.parent === selectedId && squeeze(text).includes(squeeze(back.text))) {
        ridingBranch.current.set(id, back);
        setPendingClose(null);
      }
      return id;
    },
    [selectedId, forYou, markSent]
  );

  /** 没发出去：这一单带着的暂存退回待发出，重试时照样算。 */
  const onSendFailed = useCallback(
    (outboundId?: string) => {
      const aboard = outboundId ? riding.current.get(outboundId) : undefined;
      if (outboundId && aboard) {
        riding.current.delete(outboundId);
        // 人已经切去别的会话就不退了：待发出只在当前这一场里有意义。
        if (aboard.sid === selectedId) {
          setPendingUse((prev) => [...prev, ...aboard.ids.filter((mid) => !prev.includes(mid))]);
        }
      }
      // 带出去的引用也退回待发出。
      const quoted = outboundId ? ridingQuotes.current.get(outboundId) : undefined;
      if (outboundId && quoted) {
        ridingQuotes.current.delete(outboundId);
        if (quoted.sid === selectedId) {
          setPendingQuotes((prev) => [...prev, ...quoted.anchors.filter((q) => !prev.includes(q))]);
        }
      }
      // 带回主线的那一单没发出去：退回待收口，重试发出照样收。
      const back = outboundId ? ridingBranch.current.get(outboundId) : undefined;
      if (outboundId && back) {
        ridingBranch.current.delete(outboundId);
        if (back.parent === selectedId) setPendingClose(back);
      }
      clearSent(outboundId);
    },
    [clearSent, selectedId]
  );

  /**
   * 决定卡片：答过没有按记录判；点了就把那句答复交给输入区，跟「发送」走同一条路。
   * 包过的出门、失败两处要替代原来那两处接给输入区——卡片凭它们认出是哪一单发失败了。
   */
  const cards = useDecisionCards({
    sessionId: selectedId,
    records: recordsSessionId === selectedId ? records : [],
    blockedReason: blockReason(selectedId),
    onSendStart,
    onSendFailed,
  });

  /**
   * 人从记录流里引过来的那段话，等着落进输入框。
   *
   * 编号用自增的次数而不是时间：同一段话连引两次，时间戳可能一模一样，输入区会以为
   * 是同一件事而把第二次吃掉。
   */
  const [quote, setQuote] = useState<{ text: string; note?: string; at: number } | null>(null);
  const quoteSeq = useRef(0);
  // 换会话把没落地的引用收掉——那段话是从上一场的记录里圈的。
  useEffect(() => setQuote(null), [selectedId]);

  /** 暂存列表「填入」：按引用格式落进输入框，想法接在后面；这一条进入待发出。 */
  const fillFromStack = useCallback((mark: WorkbenchMark) => {
    setQuote({ text: mark.text, note: mark.note, at: (quoteSeq.current += 1) });
    setPendingUse((prev) => (prev.includes(mark.id) ? prev : [...prev, mark.id]));
  }, []);

  /**
   * 暂存列表「点原文」：让记录流滚回那段文字。原处还没加载就往前翻页找，找到之前条目上
   * 写「正在往前找」，翻到开头也找不到就写「没找到原处」，NEVER 跳去别的地方。
   */
  const [locateTarget, setLocateTarget] = useState<{ mark: WorkbenchMark; at: number } | null>(null);
  const [locateState, setLocateState] = useState<Record<string, LocateState>>({});
  useEffect(() => {
    setLocateTarget(null);
    setLocateState({});
  }, [selectedId]);
  const onLocateResult = useCallback((id: string, result: LocateState | 'found') => {
    setLocateState((prev) => {
      const next = { ...prev };
      if (result === 'found') delete next[id];
      else next[id] = result;
      return next;
    });
  }, []);

  /**
   * 新建那一场从「点了创建」到「界面上真的有它」之间的那段路。
   *
   * 从前这段路上什么都没有：对话框一关，人要盯着一片空白等将近十秒。现在它有两个去处——
   * 左栏清单上方一行，中栏一块启动面板，两处说的是同一件事的同一档。
   *
   * 接过来那一刻先把中栏腾空（`setWorkbenchSessionId(null)`），启动面板才占得住位置；编号一到
   * 就切进那一场，但**人这中间自己挑了别的会话就不抢**——他已经改看别处了。
   */
  const { launch, begin, dismiss } = useSessionLaunch({
    sessions: sessions.sessions,
    reload: sessions.reload,
    onReady: (sid) => {
      if (usePageStore.getState().workbenchSessionId === null) setWorkbenchSessionId(sid);
    },
    recordsSessionId,
    recordCount: records.length,
  });

  // 中栏此刻该让给启动面板：正在起，而且人没有把中栏切到别的会话上去。
  const showLaunch = Boolean(launch) && (selectedId === null || selectedId === launch?.sessionId);

  /**
   * 这场此刻的上下文水位：主会话最后一道用量刻度报的提示词大小。
   *
   * 只认主会话的刻度——子 agent 各有各的上下文，它们的水位说的不是这一场。手上这批记录
   * 是别的会话的（切换那一拍）就当还没读到。
   */
  const contextTokens = useMemo(() => {
    if (recordsSessionId !== selectedId) return null;
    for (let i = records.length - 1; i >= 0; i -= 1) {
      const r = records[i];
      if (r.kind !== 'usage.tick' || r.agent_path.length) continue;
      const v = r.payload.context_tokens;
      return typeof v === 'number' ? v : null;
    }
    return null;
  }, [records, recordsSessionId, selectedId]);

  /**
   * 起分支（spec 20260928-webui-session-branch）：圈一段原文、写一句话，服务端起一场新会话
   * 专门处理这个旁支问题。**页面不跳走**——主线接着谈，输入框上方一行说分支去了哪，点「打开」
   * 才过去。切走会话或点关闭，这一行就撤。
   */
  const [branchNotice, setBranchNotice] = useState<BranchNotice | null>(null);
  useEffect(() => setBranchNotice(null), [selectedId]);
  /** 每起一次分支加一：回来晚的那次不许盖掉后来那次的提示。 */
  const branchSeq = useRef(0);
  const onBranch = useCallback(
    async (anchor: MarkAnchor, note: string) => {
      const parent = selectedId;
      if (!parent) return;
      const seq = (branchSeq.current += 1);
      // 人已经切走、或者又起了一次：这一次的下场不再往那一行上写。
      const current = () =>
        branchSeq.current === seq && usePageStore.getState().workbenchSessionId === parent;
      const show = (next: Omit<BranchNotice, 'parent'>) => {
        if (current()) setBranchNotice({ parent, ...next });
      };
      show({ state: 'starting' });
      let launch;
      try {
        launch = await startBranch(parent, { ...anchor, note });
      } catch (e) {
        show({ state: 'failed', reason: e instanceof Error ? e.message : String(e) });
        return;
      }
      const title = launch.title;
      if (launch.session_id) {
        show({
          state: launch.recorded === false ? 'unrecorded' : 'ready',
          title,
          child: launch.session_id,
          markNotSaved: launch.mark_saved === false,
        });
        if (current()) void marks.syncBranches();
        void sessions.reload();
        return;
      }
      // 编号要等认领的那两家：先说「正在起」，认到了再给「打开」。服务端认到编号才记账，
      // 所以标注比编号晚到一拍，隔一会儿再取一次。
      show({ state: 'starting', title });
      try {
        const child = await waitForSession(launch.handle);
        show({ state: 'ready', title, child });
        void sessions.reload();
        if (current()) {
          void marks.syncBranches();
          setTimeout(() => {
            if (current()) void marks.syncBranches();
          }, 2_000);
        }
      } catch (e) {
        // 首轮跑完仍没认到编号：分支是起了的，只是关联记不上——与「没起来」分开说。
        const last = await fetchPending(launch.handle).catch(() => null);
        if (last && last.finished && !last.session_id && !last.error) {
          show({ state: 'unrecorded', title, child: null });
        } else {
          show({ state: 'failed', reason: e instanceof Error ? e.message : String(e) });
        }
      }
    },
    [selectedId, marks, sessions]
  );

  const openSession = useCallback(
    (sid: string) => {
      setWorkbenchSessionId(sid);
      void sessions.reload();
    },
    [setWorkbenchSessionId, sessions]
  );

  const composerNotice = useMemo<ComposerNotice | null>(() => {
    if (!branchNotice || branchNotice.parent !== selectedId) return null;
    const dismiss = () => setBranchNotice(null);
    const child = branchNotice.child;
    const open = child
      ? { actionLabel: t('workbench.branch.open'), onAction: () => openSession(child) }
      : {};
    switch (branchNotice.state) {
      case 'starting':
        return {
          text: branchNotice.title
            ? t('workbench.branch.startingTitled', { title: branchNotice.title })
            : t('workbench.branch.starting'),
          onDismiss: dismiss,
        };
      case 'ready':
        return {
          text: branchNotice.markNotSaved
            ? `${t('workbench.branch.started', { title: branchNotice.title ?? '' })} ${t('workbench.branch.markNotSaved')}`
            : t('workbench.branch.started', { title: branchNotice.title ?? '' }),
          ...open,
          onDismiss: dismiss,
        };
      case 'unrecorded':
        return { text: t('workbench.branch.notRecorded'), ...open, onDismiss: dismiss };
      default:
        return {
          text: t('workbench.branch.failed', { reason: branchNotice.reason ?? '' }),
          tone: 'error',
          onDismiss: dismiss,
        };
    }
  }, [branchNotice, selectedId, t, openSession]);

  /**
   * 带回主线：分支会话里点了，切回原会话，把分支最后一段代理回复按引用格式落进输入框，
   * 不自动发出。主线那一句**发出成功**才算这条分支收口；填了没发、切走、或者发出去的话里
   * 已经没有这段回复了，都不算——与暂存「用过了」同一个判法。
   */
  // 必须排在上面「换会话把引用收掉」那条之后：同一拍里先清、再填，填进去的才留得住。
  useEffect(() => {
    const back = bringBackRef.current;
    bringBackRef.current = null;
    if (back && selectedId === back.parent) {
      setQuote({ text: back.text, at: (quoteSeq.current += 1) });
      setPendingClose(back);
    } else {
      setPendingClose(null);
    }
  }, [selectedId]);

  const branchParent =
    selected?.relation?.kind === 'branch' && selected.parent_session_id
      ? selected.parent_session_id
      : null;
  // 原会话被删了、或者不在清单里：「带回主线」不出现（spec 边界情况）。
  const canBringBack =
    Boolean(branchParent) && sessions.sessions.some((s) => s.session_id === branchParent);
  const bringBack = useCallback(() => {
    if (!selectedId || !branchParent) return;
    let reply = '';
    if (recordsSessionId === selectedId) {
      for (let i = records.length - 1; i >= 0; i -= 1) {
        const r = records[i];
        if (r.kind !== 'agent.say' || r.agent_path.length) continue;
        const text = typeof r.payload.text === 'string' ? r.payload.text.trim() : '';
        if (text) {
          reply = text;
          break;
        }
      }
    }
    if (!reply) {
      showToast(t('workbench.branch.noReply'), 'error');
      return;
    }
    bringBackRef.current = { parent: branchParent, child: selectedId, text: reply };
    setWorkbenchSessionId(branchParent);
  }, [selectedId, branchParent, records, recordsSessionId, setWorkbenchSessionId, showToast, t]);

  /** 关系账与主线标注由服务端一起改；改完把主线的虚线换成中性底、左栏跟着刷新。 */
  const settleBranch = useCallback(
    async (parent: string, child: string, by: 'bring-back' | 'manual') => {
      try {
        await closeBranch(parent, child, by);
        if (usePageStore.getState().workbenchSessionId === parent) await marks.syncBranches();
        void sessions.reload();
      } catch (e) {
        showToast(
          t('workbench.branch.closeFailed', { reason: e instanceof Error ? e.message : String(e) }),
          'error'
        );
      }
    },
    [marks, sessions, showToast, t]
  );

  /**
   * 一单发出成功之后该发生的三件事：带出去的引用落成标注、带出去的暂存标用过、带回主线
   * 的那条分支收口。三张账各自按信封编号取、取完即删，所以同一单每件事只做一次，谁先到
   * 谁做。
   *
   * **「发出成功」认的是这句话落进会话，不是发送接口回来。** 那条接口要等整整一轮说完
   * 才回来，上限 180 秒；这一轮跑得比它久（常事），它就以超时收场，而那时话早已在会话
   * 里，页面按「已送达」悄悄收掉、不再走成功那条路——症状是发出去了、引用不上色、暂存
   * 不转用过、分支不收口。所以主路是进度里「进了会话 / 进了插话队列」那一步，接口回来
   * 那条留着兜底（人早切走了、进度认不出落地时靠它）。
   */
  const landOutbound = useCallback(
    (outboundId: string) => {
      landQuotes(outboundId);
      const aboard = riding.current.get(outboundId);
      if (aboard) {
        riding.current.delete(outboundId);
        markUsed(aboard.ids, aboard.sid);
      }
      const back = ridingBranch.current.get(outboundId);
      if (back) {
        ridingBranch.current.delete(outboundId);
        void settleBranch(back.parent, back.child, 'bring-back');
      }
    },
    [landQuotes, markUsed, settleBranch]
  );
  useEffect(() => {
    for (const tr of trails) {
      if (tr.steps.failed !== undefined) continue;
      if (tr.steps.in_the_session !== undefined || tr.steps.queued !== undefined) landOutbound(tr.id);
    }
  }, [trails, landOutbound]);

  /**
   * 交接到新会话。拼第一句话、起名都在服务端；这里只把回执当成一次普通的新建接过去——
   * 左栏「正在启动」、认到编号自动切过去，都走新建会话那一条路。
   */
  const [handingOff, setHandingOff] = useState(false);
  const handoff = async () => {
    if (!selectedId || handingOff) return;
    setHandingOff(true);
    try {
      const pending = await handoffSession(selectedId);
      setWorkbenchSessionId(null);
      begin(pending, t('workbench.composer.handoffLaunchText', { title: pending.old_title }));
      void sessions.reload();
      showToast(
        t('workbench.composer.handoffDone', { old: pending.old_title, new: pending.new_title }),
        'success'
      );
    } catch (e) {
      showToast(
        t('workbench.composer.handoffFailed', { reason: e instanceof Error ? e.message : String(e) }),
        'error'
      );
    } finally {
      setHandingOff(false);
    }
  };

  return (
    /* 默认列宽照原型：清单 288 · 记录 · 观察者 228（清单 09-24 定 256，09-29 第五轮卡片改成三行、
       状态行要摆 For you · 时长 · 终端 · 子会话数 · 「…」，放不下，改 288）。人拖过的右栏宽度
       照旧优先（记在浏览器里）；平板档照旧藏起观察者栏，断点不动。 */
    <div data-session-menu-page className="grid h-full min-h-0 w-full flex-1 grid-cols-[288px_minmax(0,1fr)_var(--report-w,228px)] tablet:grid-cols-[288px_minmax(0,1fr)] phone:grid-cols-1"
      style={report.width ? ({ '--report-w': `${report.width}px` } as CSSProperties) : undefined}
    >
      {/* 手机上一次只放得下一栏：没选会话时给清单，选了就整屏让给记录流。 */}
      <div className={`min-h-0 min-w-0 ${selectedId || showLaunch ? 'phone:hidden' : ''}`}>
        <SessionRail
          state={sessions}
          selectedId={selectedId}
          onSelect={setWorkbenchSessionId}
          launch={launch}
          onDismissLaunch={dismiss}
          onCreated={(pending, text) => {
            setWorkbenchSessionId(null);
            begin(pending, text);
          }}
          views={views}
          forYou={forYou}
          sendingId={sendingId}
          busyId={busyId}
          pins={pins}
          holdId={holdId}
          decisionCardOf={decisionCardOf}
          onSessionDeleted={(sid) => {
            if (sid === selectedId) setWorkbenchSessionId(null);
          }}
        />
      </div>

      <div
        className={`flex min-h-0 min-w-0 flex-col bg-bg-primary ${
          selectedId || showLaunch ? '' : 'phone:hidden'
        }`}
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-border-color px-5 py-2.5">
          {selectedId ? (
            <button
              type="button"
              onClick={() => setWorkbenchSessionId(null)}
              className="hidden shrink-0 text-text-muted hover:text-text-primary phone:block"
              aria-label={t('workbench.page.backToList')}
            >
              <ChevronLeft size={16} />
            </button>
          ) : null}
          <h1 className="min-w-0 truncate text-[14px] font-semibold text-text-primary">
            {selected
              ? selected.title
              : showLaunch
                ? t('workbench.launch.railTitle')
                : t('workbench.page.title')}
          </h1>
          {selected ? (
            <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[11px] text-text-muted">
              {headStatus ? (
                <span
                  data-testid="head-status"
                  className={`flex shrink-0 items-center gap-1 ${
                    headStatus.live ? 'text-accent-primary' : 'text-text-secondary'
                  }`}
                >
                  {headStatus.live ? (
                    <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-accent-primary" />
                  ) : null}
                  {headStatus.text}
                  <span aria-hidden className="text-text-dim">·</span>
                </span>
              ) : null}
              <span className="min-w-0 truncate font-mono">{selected.directory}</span>
            </span>
          ) : (
            // 没选会话时标题后面留空：全局第 2 条删掉页头里开发者口吻的说明
            <span className="min-w-0 flex-1" />
          )}
          {/* 用量月历的入口搬去了左栏底部：那里是「我还剩多少」的位置，与额度条并排。
              它本来就不是会话页专属的东西，挂在这一页的标题栏上只是它当初落脚的地方。 */}
          {/* 这一行的最右是一个「…」，与左栏会话卡上的是同一份菜单：Pin / Unpin、Put in group ｜
              Close tmux session（只在开在 tmux 里时出现，在干活先确认）｜ Delete session（先确认）。
              关掉之后清单重取；删掉之后中栏退回清单态——再停在那一场上，记录流对着一个已经
              不存在的编号接着问。 */}
          {selected ? (
            <SessionMenu
              session={selected}
              variant="header"
              pinned={pins.isPinned(selected.session_id)}
              onTogglePin={(s) => void pins.toggle(s.session_id).catch((e: unknown) =>
                showToast(e instanceof Error ? e.message : t('workbench.errors.pinSaveFailedPlain'), 'error')
              )}
              inTmux={
                selected.in_tmux === true || forYou.rows.some((r) => r.session_id === selected.session_id)
              }
              busyTurn={inFlight}
              onStopped={() => {
                forYou.refresh();
                void sessions.reload();
              }}
              onDeleted={() => {
                setWorkbenchSessionId(null);
                void sessions.reload();
              }}
              boundSelector="[data-session-menu-page]"
            />
          ) : null}
        </header>

        <div className="min-h-0 flex-1">
          {showLaunch && launch ? (
            <SessionLaunchPanel launch={launch} onDismiss={dismiss} />
          ) : (
            <DecisionCardContext.Provider value={cards.host}>
            <RecordStream
              sessionId={selectedId}
              records={records}
              loading={loading}
              loadingOlder={loadingOlder}
              hasOlder={hasOlder}
              error={error}
              onLoadOlder={loadOlder}
              awaitingAgent={awaitingAgent}
              trails={trails}
              scrollTarget={scrollTarget}
              onQuote={(text, anchor) => {
                setQuote({ text, at: (quoteSeq.current += 1) });
                // 这一刻只记成待发出，发出成功才留痕——见 `pendingQuotes`。
                if (anchor) setPendingQuotes((prev) => [...prev, anchor]);
              }}
              onStack={(anchor, note) => marks.addMark({ kind: 'stack', ...anchor, note })}
              onBranch={(anchor, note) => void onBranch(anchor, note)}
              onOpenBranch={openSession}
              onCloseBranch={(mark) => {
                if (selectedId && mark.child_session_id) {
                  void settleBranch(selectedId, mark.child_session_id, 'manual');
                }
              }}
              marks={marks.marks}
              minimap
              locateTarget={locateTarget}
              onLocateResult={onLocateResult}
            />
            </DecisionCardContext.Provider>
          )}
        </div>

        {/* 分两刻做两件事。
            **出门那一刻**举起"在等 agent 开口"、给那句话开一个信封并转入快节拍
            （markSent）——发送这条接口要等整整一轮才回来，挂在回来那一刻等于整轮之内
            中栏一动不动。
            **回来那一刻**把自己刚说的那句拉进流里（reload），并让左栏状态跟着从"已完成"
            转成"在跑"、升到顶部。
            信封由记录流照着真记录判档：还找不到它就是"已发送"，找到的是一张还在队列上的
            插话卡就是"已入队列"。输入区只管画，不自己猜。 */}
        {showLaunch ? null : (
        <Composer
          sessionId={selectedId}
          family={selected?.family ?? null}
          // 上沿那条线上的小人跟着这一场走：会话在跑、或者刚发出去还没等到 agent 开口，
          // 他就在线上踱步；两样都落下他才坐下。
          running={selected?.status === 'running' || awaitingAgent}
          onSendStart={cards.onSendStart}
          onSendFailed={cards.onSendFailed}
          answer={cards.answer}
          deliveredAt={deliveredAt}
          outbound={outbound}
          trails={trails}
          onShowInStream={(recordId) => setScrollTarget({ recordId, at: Date.now() })}
          quote={quote}
          contextTokens={contextTokens}
          onHandoff={() => void handoff()}
          handingOff={handingOff}
          notice={composerNotice}
          onBringBack={canBringBack ? bringBack : undefined}
          onSent={(outboundId) => {
            void reload();
            void sessions.reload();
            // 兜底：进度里没认出落地（比如人早切走了），接口回来这一刻照样落。
            if (outboundId) landOutbound(outboundId);
            // 接口回来了就说明这一轮已经说完，那句话必定在会话里了：信封该收，
            // 不必等记录流认出它长什么样。
            settleSent(outboundId);
          }}
        />
        )}
      </div>

      <div className="min-h-0 min-w-0 tablet:hidden phone:hidden">
        {/* 右栏下半是这场会话的暂存列表。没选会话时右栏只有一句说明，不分上下。 */}
        <ReportPanel
          sessionId={selectedId}
          width={report.width}
          onWidthChange={report.setWidth}
          lowerEmpty={!marks.marks.some((m) => m.kind === 'stack')}
          lower={
            selectedId ? (
              <StackPanel
                marks={marks.marks}
                pendingIds={pendingUse}
                locate={locateState}
                onFill={fillFromStack}
                onLocate={(mark) => {
                  onLocateResult(mark.id, 'found');
                  setLocateTarget({ mark, at: Date.now() });
                }}
                onDelete={marks.remove}
                onMove={marks.move}
                onNoteChange={marks.setNote}
              />
            ) : undefined
          }
        />
      </div>
    </div>
  );
}
