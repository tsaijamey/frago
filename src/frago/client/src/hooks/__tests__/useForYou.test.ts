/**
 * For you 的判据。
 *
 * 三条缺一条就不挂；worker 不挂；判不出（非 Claude Code，`awaiting_input` 为 null）不挂；
 * 加重只认字面；原话截开头留结尾；卡片的问题覆盖原话。
 */

import { describe, expect, it } from 'vitest';

import { closableTerminals, forYouOf, keepTail, WORDS_MAX } from '../useForYou';
import type { WorkbenchSession } from '../useWorkbenchSessions';
import type { TmuxWaitingItem } from '@/types/api';

const STOP = '2026-09-24T13:11:00+00:00';
const STOP_MS = Date.parse(STOP);

function session(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: 's1',
    family: 'claude-code',
    title: 'zenith',
    directory: '/Users/frago/Repos/zenith',
    created_at: STOP_MS - 3_600_000,
    last_active_at: STOP_MS,
    last_reply_at: STOP_MS,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

function row(over: Partial<TmuxWaitingItem> = {}): TmuxWaitingItem {
  return {
    name: 'frago-agent-s1',
    session_id: 's1',
    client_alive: true,
    awaiting_input: true,
    stop_reason: 'end_turn',
    last_stop_at: STOP,
    closing_text: '做完了。',
    ...over,
  };
}

describe('挂不挂', () => {
  it('三条都成立就挂，等的起点是 tmux 报的停下时刻', () => {
    const info = forYouOf(session(), row(), undefined);
    expect(info).not.toBeNull();
    expect(info?.waitingSince).toBe(STOP_MS);
  });

  it('不在 tmux 里不挂', () => {
    expect(forYouOf(session(), undefined, undefined)).toBeNull();
  });

  it('客户端退了（前台只剩 shell）不挂', () => {
    expect(forYouOf(session(), row({ client_alive: false }), undefined)).toBeNull();
  });

  it('前台问不出不挂', () => {
    expect(forYouOf(session(), row({ client_alive: null }), undefined)).toBeNull();
  });

  it('在忙（没停在输入框）不挂', () => {
    expect(forYouOf(session(), row({ awaiting_input: false }), undefined)).toBeNull();
  });

  it('非 Claude Code 判不出（null）不挂，宁可漏挂', () => {
    expect(forYouOf(session({ family: 'opencode' }), row({ awaiting_input: null }), undefined)).toBeNull();
  });

  it('worker 不挂：它等的是主控，不是你', () => {
    expect(forYouOf(session({ origin: 'worker' }), row(), undefined)).toBeNull();
  });

  it('那一轮没终结（没有停下时刻）照挂，等的起点退回最后回复', () => {
    const info = forYouOf(session({ last_reply_at: STOP_MS - 5_000 }), row({ last_stop_at: null }), undefined);
    expect(info?.waitingSince).toBe(STOP_MS - 5_000);
  });
});

describe('加重', () => {
  it('问句 → answer，原话取那一句', () => {
    const info = forYouOf(session(), row({ closing_text: '三条都记下了。\n\n要我把它们标成高优先级吗？' }), undefined);
    expect(info?.emphasis).toBe('answer');
    expect(info?.words).toBe('要我把它们标成高优先级吗？');
  });

  it('A or B → pick-one', () => {
    const info = forYouOf(session(), row({ closing_text: 'Two ways to fix it. Reply with one letter for the hook item: A or B.' }), undefined);
    expect(info?.emphasis).toBe('pick-one');
    expect(info?.words).toContain('A or B');
  });

  it('出错停下 → stopped，原话取卡住摘要', () => {
    const info = forYouOf(session({ digest_stuck: 'API Error: 连接中断' }), row(), undefined);
    expect(info?.emphasis).toBe('stopped');
    expect(info?.words).toBe('API Error: 连接中断');
  });

  it('「请你验收」要明说才算；「你可以再发一次试试」是建议不是问', () => {
    expect(forYouOf(session(), row({ closing_text: '修好了，请你验收。' }), undefined)?.emphasis).toBe('answer');
    expect(forYouOf(session(), row({ closing_text: '修好了，你可以再发一次试试。' }), undefined)?.emphasis).toBeNull();
  });

  it('卡片的问题覆盖原话，加重为 decision-card', () => {
    const info = forYouOf(session(), row({ closing_text: '要我记下来吗？' }), undefined, '选哪一条改法？');
    expect(info?.emphasis).toBe('decision-card');
    expect(info?.words).toBe('选哪一条改法？');
  });
});

describe('原话与看过没', () => {
  it('没有问句取最后一段', () => {
    const info = forYouOf(session(), row({ closing_text: '第一段。\n\n最后一段说完了。' }), undefined);
    expect(info?.words).toBe('最后一段说完了。');
  });

  it('超长截开头、留结尾', () => {
    const long = `${'前情'.repeat(200)}A or B.`;
    const out = keepTail(long);
    expect(out.startsWith('…')).toBe(true);
    expect(out.endsWith('A or B.')).toBe(true);
    expect(out.length).toBeLessThanOrEqual(WORDS_MAX);
  });

  it('停下之后没点开过 → unseen；之后点开过 → 不是', () => {
    expect(forYouOf(session(), row(), undefined)?.unseen).toBe(true);
    expect(forYouOf(session(), row(), STOP_MS - 60_000)?.unseen).toBe(true);
    expect(forYouOf(session(), row(), STOP_MS + 60_000)?.unseen).toBe(false);
  });
});

describe('可关的终端', () => {
  it('只认客户端已退出的；在等你的、在忙的、问不出的都不算', () => {
    const rows = [
      row({ name: 'a', client_alive: false }),
      row({ name: 'b', client_alive: true, awaiting_input: true }),
      row({ name: 'c', client_alive: true, awaiting_input: false }),
      row({ name: 'd', client_alive: null }),
    ];
    expect(closableTerminals(rows).map((r) => r.name)).toEqual(['a']);
  });
});
