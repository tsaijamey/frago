/**
 * useSessionLaunch — 新建会话从「点了创建」到「它在界面上真的存在」之间的那段路。
 *
 * 这段路从前是一片空白：对话框一关就什么都没有了，人要等将近十秒才看见左栏多出一行。
 * 那十秒里界面纹丝不动，人分不出是没建成、还是在起——只好再点一次，于是起了两场。
 *
 * 路上有两个真实的档，它们不是同一件事：
 *
 * | 档 | 此刻在等什么 | 谁会经过 |
 * |---|---|---|
 * | 正在认领编号 | 会话进程刚起，还没报出自己的编号 | codex / opencode |
 * | 正在启动 | 编号有了，但它还没往档案里写下第一笔 | 三家都要经过 |
 *
 * claude 的编号是页面这边定的，点完创建当场就有，所以它直接从第二档起步。
 *
 * 走完的判据有两条，谁先到算谁：**它出现在会话清单里**（左栏那一行长出来了），或者
 * **记录流里有它写的东西了**（中栏有内容了）。任一成立，这块启动状态就该消失——它的
 * 全部意义就是替一场还看不见的会话站着，会话看得见了它就该让位。
 *
 * **这两条 NEVER 换成"等 agent 开口"。** 换过一次，代价是这块卡会挂死：新起的那一场
 * 在清单里还不算"在跑"，记录流因此既不轮询也没人推，agent 说没说话这件事这一侧根本
 * 问不到，卡就一直站在中栏挡着不走。判据只能挂在这一侧自己看得见的事实上——清单里有
 * 没有那一行、手上有没有记录——不能挂在一条可能整场沉默的通道上。
 *
 * 没起来那一档不自己消失：原因要留在人眼前，连同他刚打的那句话，由人自己收掉。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import i18n from '@/i18n';
import { waitForSession, type PendingLaunch } from '@/hooks/useAgentClients';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

/**
 * 编号有了之后，隔多久重取一次会话清单。
 *
 * 新会话的档案是 agent 自己写的，写完才扫得到，所以第一次重取多半扫了个空。间隔越拉
 * 越长：起得快的一两秒就进清单，起得慢的（冷启动、装载大目录）要十几秒。
 */
const LAUNCH_RELOAD_STEPS = [1500, 3000, 6000, 12000];

/**
 * 「正在启动」最多挂多久。
 *
 * 到点还没在清单里也没写下第一笔就撤掉——挂着一个永远在启动的东西，比不提示还糟：
 * 人分不出是它还在起，还是这块提示自己坏了。会话本身不受影响，它该在的时候还是会
 * 出现在左栏。
 */
export const LAUNCH_CEILING_MS = 90_000;

/** 这场新会话此刻走到哪一档。 */
export type LaunchPhase = 'claiming' | 'warming' | 'failed';

/** 一场正在起的会话。界面照着它画启动卡。 */
export interface SessionLaunch {
  /** 这次新建的把手。问「编号报出来没有」用的就是它。 */
  handle: string;
  /** 哪一家起的，用显示名（codex / opencode / Claude Code）。 */
  agentName: string;
  /** 在哪个目录起的。 */
  cwd: string;
  /** 建它时打的第一句话。这句已经发出去了，摆出来人才知道自己等的是什么。 */
  text: string;
  /** 认到编号没有。null = 还在认领那一档。 */
  sessionId: string | null;
  phase: LaunchPhase;
  /** 没起来的原因，照抄服务端的说法。 */
  error: string | null;
  at: number;
}

export interface SessionLaunchState {
  /** 正在起的那一场；没有就是 null。 */
  launch: SessionLaunch | null;
  /** 对话框建完那一刻调它，把这次新建接过来。 */
  begin: (pending: PendingLaunch, text: string) => void;
  /** 人把没起来的那张卡收掉。 */
  dismiss: () => void;
}

export interface UseSessionLaunchOptions {
  /** 全量会话清单（不是筛过的那一份）。新会话在这里露面就说明它进左栏了。 */
  sessions: WorkbenchSession[];
  /** 重取清单。 */
  reload: () => void | Promise<void>;
  /** 认到编号那一刻。页面据此把中栏切到这一场。 */
  onReady: (sessionId: string) => void;
  /**
   * 中栏手上这批记录是哪一场的，以及有几条。两者一起答"它写下第一笔了没有"。
   *
   * NEVER 换成"中栏此刻开着哪一场"。中栏切到新编号的那一次渲染里，手上还是上一场的记录，
   * 清空要等下一拍——拿"开着哪一场"配上一场的条数，卡一挂上就被当成"已经写下第一笔"撤掉，
   * 人从一场有内容的会话里点新建，永远看不见这块卡。
   */
  recordsSessionId?: string | null;
  recordCount?: number;
}

export function useSessionLaunch({
  sessions,
  reload,
  onReady,
  recordsSessionId = null,
  recordCount = 0,
}: UseSessionLaunchOptions): SessionLaunchState {
  const [launch, setLaunch] = useState<SessionLaunch | null>(null);
  // 这两个回调每渲染都是新的，放进 ref 让效应不必跟着它们重跑。
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  const begin = useCallback((pending: PendingLaunch, text: string) => {
    setLaunch({
      handle: pending.handle,
      agentName: pending.display_name,
      cwd: pending.cwd,
      text: text.trim(),
      sessionId: pending.session_id,
      // 编号当场就有的（claude）直接进第二档：它没有"认领"这一段可等。
      phase: pending.session_id ? 'warming' : 'claiming',
      error: null,
      at: Date.now(),
    });
    if (pending.session_id) onReadyRef.current(pending.session_id);
  }, []);

  const dismiss = useCallback(() => setLaunch(null), []);

  // 认领编号那一档：问到编号就转进「正在启动」，问不到就照实说没起来。
  useEffect(() => {
    if (!launch || launch.phase !== 'claiming') return;
    const handle = launch.handle;
    let cancelled = false;
    const controller = new AbortController();

    void (async () => {
      try {
        const sid = await waitForSession(handle, { signal: controller.signal });
        if (cancelled) return;
        setLaunch((cur) =>
          cur && cur.handle === handle ? { ...cur, sessionId: sid, phase: 'warming' } : cur
        );
        onReadyRef.current(sid);
      } catch (e) {
        if (cancelled) return;
        const reason = e instanceof Error ? e.message : i18n.t('workbench.errors.launchFailed');
        setLaunch((cur) =>
          cur && cur.handle === handle ? { ...cur, phase: 'failed', error: reason } : cur
        );
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [launch]);

  // 编号有了就反复重取清单：新会话的档案是 agent 自己写的，写完才扫得到。
  useEffect(() => {
    if (!launch || launch.phase !== 'warming') return;
    let cancelled = false;

    void (async () => {
      for (const delay of LAUNCH_RELOAD_STEPS) {
        await new Promise((r) => setTimeout(r, delay));
        if (cancelled) return;
        await reloadRef.current();
      }
    })();

    return () => {
      cancelled = true;
    };
    // 这一串重取只在转进「正在启动」那一刻起跑一次：这一档里 launch 本身不再变，
    // 盯着整个对象不会把它重启。
  }, [launch]);

  // 它在界面上真的存在了（进了清单，或写下了第一笔），这块启动状态就让位。
  useEffect(() => {
    if (!launch || launch.phase !== 'warming' || !launch.sessionId) return;
    const inList = sessions.some((s) => s.session_id === launch.sessionId);
    const wrote = recordsSessionId === launch.sessionId && recordCount > 0;
    if (inList || wrote) setLaunch(null);
  }, [launch, sessions, recordsSessionId, recordCount]);

  // 等太久就撤。会话本身不受影响，该出现时还是会出现在左栏。
  useEffect(() => {
    if (!launch || launch.phase === 'failed') return;
    const timer = setTimeout(
      () => setLaunch((cur) => (cur && cur.handle === launch.handle ? null : cur)),
      Math.max(0, launch.at + LAUNCH_CEILING_MS - Date.now())
    );
    return () => clearTimeout(timer);
  }, [launch]);

  return { launch, begin, dismiss };
}
