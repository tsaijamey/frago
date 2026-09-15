/**
 * 两个标记的判据。
 *
 * 绿圈答「agent 说完话停下了、你还没回去看」，以一小时为界。流光答「此刻开在 tmux
 * 里」，只看服务端给的 `in_tmux`，与时间无关。
 */

import { describe, expect, it } from 'vitest';

import { isInTmux, isUnreadAt, RECENT_MS } from '../useSessionViews';
import type { WorkbenchSession } from '../useWorkbenchSessions';

const NOW = 1_800_000_000_000;

function session(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: '00a02979-7eb4-5c70-94ae-867c8281e3f6',
    family: 'claude-code',
    title: '会话页左栏分页',
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 10 * RECENT_MS,
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

describe('绿圈：说完了话、你还没回去看', () => {
  it('十分钟前停下、从没点开过 → 亮', () => {
    expect(isUnreadAt(session(), undefined, NOW)).toBe(true);
  });

  it('十分钟前停下、你在那之前点开的 → 亮', () => {
    expect(isUnreadAt(session(), NOW - 30 * 60_000, NOW)).toBe(true);
  });

  it('十分钟前停下、你在那之后点开过 → 灭', () => {
    expect(isUnreadAt(session(), NOW - 60_000, NOW)).toBe(false);
  });

  it('停下来超过一小时 → 灭，哪怕一次都没点开过', () => {
    // 本机六百多场旧会话就是这一档：它们停在几天前，不该在第一天全部亮起来。
    const old = session({ last_reply_at: NOW - 3 * RECENT_MS, last_active_at: NOW - 3 * RECENT_MS });
    expect(isUnreadAt(old, undefined, NOW)).toBe(false);
  });

  it('还在跑 → 灭：它还没停下，没有「说完了」这回事', () => {
    expect(isUnreadAt(session({ status: 'running' }), undefined, NOW)).toBe(false);
  });

  it('按最后一句回复算，不按文件最后被动过算', () => {
    // hook 每拦一次工具、模型每改一次标题都会推进「文件最后被动过」，那些都不是有人说了话。
    const touched = session({ last_reply_at: NOW - 3 * RECENT_MS, last_active_at: NOW - 60_000 });
    expect(isUnreadAt(touched, undefined, NOW)).toBe(false);
  });
});

describe('流光：此刻开在 tmux 里', () => {
  it('服务端说开着 → 亮', () => {
    expect(isInTmux(session({ in_tmux: true }))).toBe(true);
  });

  it('开着但几天没动过 → 照样亮，不再看时间', () => {
    const old = session({ in_tmux: true, last_reply_at: NOW - 72 * RECENT_MS, last_active_at: NOW - 72 * RECENT_MS });
    expect(isInTmux(old)).toBe(true);
  });

  it('十分钟前刚动过、但 tmux 没开着 → 灭', () => {
    expect(isInTmux(session({ in_tmux: false }))).toBe(false);
  });

  it('旧服务端不给这个字段 → 当没开着', () => {
    expect(isInTmux(session())).toBe(false);
  });
});
