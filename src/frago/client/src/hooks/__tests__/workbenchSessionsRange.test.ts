/**
 * 时间范围那一道筛选：自己到点的留下，子会话跟着父会话走。
 *
 * 子会话那一条是 2026-10-15 加的：父会话在范围内时，它派出去的子会话一律留下，不看
 * 子会话自己多久没动过。不这么做的话，一场主会话的子会话会随时间线一条条漏掉，展开
 * 看到的是半组。
 */

import { describe, expect, it } from 'vitest';

import { withinRange, type WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const HOUR = 3600_000;
const NOW = 1_800_000_000_000;

function card(over: Partial<WorkbenchSession> & { session_id: string }): WorkbenchSession {
  return {
    family: 'claude-code',
    title: '',
    directory: '/tmp',
    created_at: NOW,
    last_active_at: NOW,
    // 判「多久没动过」用的是最后一句回复（见 activityTs），取不到才退回文件修改时刻。
    // 这些用例都在说"多久没动过"，所以默认不给回复时刻，由各条自己设 last_active_at。
    last_reply_at: null,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

describe('withinRange', () => {
  it('不设上限时原样返回', () => {
    const a = card({ session_id: 'a', last_active_at: NOW - 100 * HOUR });
    expect(withinRange([a], 0, NOW)).toEqual([a]);
  });

  it('超出范围的会话被筛掉', () => {
    const fresh = card({ session_id: 'fresh', last_active_at: NOW - HOUR });
    const old = card({ session_id: 'old', last_active_at: NOW - 30 * HOUR });
    expect(withinRange([fresh, old], 1, NOW).map((s) => s.session_id)).toEqual(['fresh']);
  });

  it('子会话跟着父会话走', () => {
    const parent = card({ session_id: 'p', last_active_at: NOW - HOUR });
    const kid = card({
      session_id: 'k',
      parent_session_id: 'p',
      origin: 'worker',
      last_active_at: NOW - 30 * HOUR,
    });
    expect(withinRange([parent, kid], 1, NOW).map((s) => s.session_id)).toEqual(['p', 'k']);
  });

  it('父会话自己也被筛掉时，子会话不留', () => {
    const parent = card({ session_id: 'p', last_active_at: NOW - 40 * HOUR });
    const kid = card({
      session_id: 'k',
      parent_session_id: 'p',
      origin: 'worker',
      last_active_at: NOW - 30 * HOUR,
    });
    expect(withinRange([parent, kid], 1, NOW)).toEqual([]);
  });

  it('留下的那些保持原来的顺序', () => {
    const parent = card({ session_id: 'p', last_active_at: NOW - HOUR });
    const other = card({ session_id: 'o', last_active_at: NOW - 2 * HOUR });
    const kid = card({
      session_id: 'k',
      parent_session_id: 'p',
      last_active_at: NOW - 30 * HOUR,
    });
    expect(withinRange([parent, other, kid], 1, NOW).map((s) => s.session_id)).toEqual([
      'p',
      'o',
      'k',
    ]);
  });
});
