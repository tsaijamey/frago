/**
 * 一次配方运行的结局，读成人该看到的那句话。
 *
 * 配方「没做成」有两种，而且不是一回事：
 * - **失败**：跑崩了、超时了。运行记录的状态就是失败，界面报错。
 * - **拒绝**：配方看过之后说不——还有一局没打完、账户里没钱。运行本身是成功的，
 *   结果里写着 `refused`（原因代号）和 `message`（给人看的话）。
 *
 * 从前界面只看状态，于是拒绝一律被报成「执行成功」，人看到的是按钮按下去、屏幕上
 * 什么都没发生。拒绝的写法是配方基类 `refuse()` 给出的约定，这里是它在界面这头的
 * 读法。
 */

export interface RecipeRefusal {
  code: string;
  message: string;
}

/** 结果里有拒绝就拿出来；没有、或者形状不对，都当没有。 */
export function refusalOf(data: unknown): RecipeRefusal | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const { refused, message } = data as { refused?: unknown; message?: unknown };
  if (typeof refused !== 'string' || !refused.trim()) return null;
  return {
    code: refused,
    // 配方没写原因时也要让人知道是被拒了，不能退回「执行成功」
    message: typeof message === 'string' && message.trim() ? message : refused,
  };
}

/** 运行记录到了这几个状态就不会再变。 */
export const TERMINAL_EXECUTION_STATUSES = new Set(['succeeded', 'failed', 'timeout', 'cancelled']);
