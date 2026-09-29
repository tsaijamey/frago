/**
 * 流光的判据：此刻开在 tmux 里，只看服务端给的 `in_tmux`，与时间无关。
 *
 * 从前这里还有一个绿圈（停下一小时内、之后没点开过），随「For you」上线退场——
 * 要不要你来改由 `useForYou` 从终端读，见 `useForYou.test.ts`。
 */

import { describe, expect, it } from 'vitest';

import { isInTmux } from '../useSessionViews';
import type { WorkbenchSession } from '../useWorkbenchSessions';

const NOW = 1_800_000_000_000;
const HOUR = 60 * 60_000;

function session(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: '00a02979-7eb4-5c70-94ae-867c8281e3f6',
    family: 'claude-code',
    title: '会话页左栏分页',
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 10 * HOUR,
    last_active_at: NOW - 10 * 60_000,
    last_reply_at: NOW - 10 * 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

describe('流光：此刻开在 tmux 里', () => {
  it('服务端说开着 → 亮', () => {
    expect(isInTmux(session({ in_tmux: true }))).toBe(true);
  });

  it('开着但几天没动过 → 照样亮，不再看时间', () => {
    const old = session({ in_tmux: true, last_reply_at: NOW - 72 * HOUR, last_active_at: NOW - 72 * HOUR });
    expect(isInTmux(old)).toBe(true);
  });

  it('十分钟前刚动过、但 tmux 没开着 → 灭', () => {
    expect(isInTmux(session({ in_tmux: false }))).toBe(false);
  });

  it('旧服务端不给这个字段 → 当没开着', () => {
    expect(isInTmux(session())).toBe(false);
  });
});
