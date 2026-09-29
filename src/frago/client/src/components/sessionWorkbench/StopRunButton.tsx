/**
 * StopRunButton — 「关闭 tmux 会话」的流程。入口在「…」菜单（`SessionMenu`）第二段。
 *
 * 09-29 第五轮四改：页头的终端图标按钮与弹窗退场，关 tmux 收进卡片与页头共用的「…」菜单，
 * 确认画在菜单里。这里留下的是菜单要调的那段流程：什么时候先问、什么时候直接关、服务端
 * 判出还在干活时再问一次。接口与结局的判读在 `useStopSessionRun`，这里不另写。
 *
 * 它关的是这场会话此刻在 tmux 里的那个会话，不是把会话删掉：记录还在，还能翻；之后再
 * 发消息，服务端会按续接命令重新拉起一个，上下文接得上。
 *
 * **在干活先确认，不在干活直接关。** 本页知道的（这一场有没答完的一句）当场问「Still
 * working — closing ends this turn」；本页不知道的先不带 force 出门，服务端说屏上还在干活、
 * 那一下什么都没动时（`busy`），换成同一句确认再问一次。人确认了才带 force。
 */

import { useCallback } from 'react';
import { useStopSessionRun, type StopPhase } from '@/hooks/useStopSessionRun';

/** 点了一下之后菜单该怎么办：`done` 收起菜单，`ask` 换到确认那一段。 */
export type CloseStep = 'done' | 'ask';

export interface CloseTmuxState {
  phase: StopPhase;
  error: string | null;
  /** 点菜单项那一下。 */
  begin: () => Promise<CloseStep>;
  /** 确认段里点「Close」那一下：带 force。 */
  confirm: () => Promise<CloseStep>;
  reset: () => void;
}

export function useCloseTmux(
  sessionId: string | null,
  {
    busyTurn = false,
    onStopped,
  }: {
    /** 本页刚发出的一句还没答完。 */
    busyTurn?: boolean;
    /** tmux 里这一场没了（关掉了，或本来就没了）之后调它——清单重取，这一项随之消失。 */
    onStopped?: () => void;
  } = {}
): CloseTmuxState {
  const { phase, error, run, reset } = useStopSessionRun(sessionId);
  const settle = useCallback(
    (next: StopPhase): CloseStep => {
      if (next === 'stopped') {
        reset();
        onStopped?.();
        return 'done';
      }
      // 清单那份旧了一轮：确认段留着把话说完，清单照样重取。
      if (next === 'absent') onStopped?.();
      return 'ask';
    },
    [reset, onStopped]
  );

  const begin = useCallback(async (): Promise<CloseStep> => {
    if (busyTurn) return 'ask';
    return settle(await run(false));
  }, [busyTurn, run, settle]);

  const confirm = useCallback(async (): Promise<CloseStep> => settle(await run(true)), [run, settle]);

  return { phase, error, begin, confirm, reset };
}
