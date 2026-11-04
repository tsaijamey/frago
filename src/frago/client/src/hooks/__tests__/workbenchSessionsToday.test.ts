/**
 * 左栏「今天」那一道筛选。
 *
 * 判据是**最后一句真正的 agent 回复**（`last_reply_at`），不是文件最后动过的时刻：
 * 一场昨晚 23:59:59 说过话的会话，今天可能被 hook 蹭了无数次，按文件时刻判就会一直
 * 留在今天的清单里——这正是这条口径要挡掉的。
 *
 * 今天刚开、还没说过话的留下；正在跑的留下；人从 timeline 捡回来的留下。
 * 置顶、父子关系、tmux 还开着都不再单独放行（2026-10-19 主人报缺陷后收紧）。
 */

import { describe, expect, it } from 'vitest';

import { startOfToday, withinToday, type WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const HOUR = 3600_000;
// 固定本地时间：2026-10-19 12:00。用本地构造，避免用例自己跨时区。
const NOW = new Date(2026, 9, 19, 12, 0, 0).getTime();
const TODAY_START = new Date(2026, 9, 19, 0, 0, 0).getTime();

function card(over: Partial<WorkbenchSession> & { session_id: string }): WorkbenchSession {
  return {
    family: 'claude-code',
    title: '',
    directory: '/tmp',
    created_at: NOW - 200 * 24 * HOUR,
    last_active_at: NOW,
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

describe('startOfToday', () => {
  it('落在本地日历的零点', () => {
    expect(startOfToday(NOW)).toBe(TODAY_START);
  });
});

describe('withinToday', () => {
  it('今天说过真话的留下，昨天 23:59:59 说了话的今天就不在', () => {
    const justNow = card({ session_id: 'just-now', last_reply_at: NOW - 5 * 60_000 });
    const yesterday = card({
      session_id: 'yesterday',
      last_reply_at: TODAY_START - 1_000,
    });
    expect(withinToday([justNow, yesterday], new Set(), NOW).map((s) => s.session_id)).toEqual([
      'just-now',
    ]);
  });

  it('文件今天被动过、但最后一句回复是昨天：不留', () => {
    const touched = card({
      session_id: 'touched',
      last_active_at: NOW - 60_000,
      last_reply_at: TODAY_START - 1_000,
    });
    expect(withinToday([touched], new Set(), NOW)).toEqual([]);
  });

  it('今天刚开、还没说过话的留下', () => {
    const born = card({ session_id: 'born', created_at: NOW - 10 * 60_000 });
    const old = card({ session_id: 'old', created_at: NOW - 25 * HOUR });
    expect(withinToday([born, old], new Set(), NOW).map((s) => s.session_id)).toEqual(['born']);
  });

  it('正在跑的留下——它今天正在产生数据，只是还没说到最后一句', () => {
    const running = card({
      session_id: 'running',
      status: 'running',
      last_reply_at: TODAY_START - 6 * HOUR,
    });
    expect(withinToday([running], new Set(), NOW).map((s) => s.session_id)).toEqual(['running']);
  });

  it('终端停在输入提示符等人（For you）的隔日旧会话，哪怕被短暂标成 running 也不混入今日', () => {
    const ghostOld = card({
      session_id: 'ghost-old',
      status: 'running',
      last_active_at: NOW - 10_000,
      last_reply_at: TODAY_START - 36 * HOUR,
    });
    const todayForYou = card({
      session_id: 'today-for-you',
      status: 'running',
      last_active_at: NOW - 10_000,
      last_reply_at: NOW - 30 * 60_000,
    });
    expect(
      withinToday(
        [ghostOld, todayForYou],
        new Set(),
        NOW,
        (id) => id === 'ghost-old' || id === 'today-for-you'
      ).map((s) => s.session_id)
    ).toEqual(['today-for-you']);
  });

  it('tmux 还开着但今天没回复：不留', () => {
    // 2026-10-19 主人报缺陷后收紧：终端挂着不等于今天有数据。
    const alive = card({
      session_id: 'alive',
      alive: true,
      in_tmux: true,
      last_reply_at: TODAY_START - 6 * HOUR,
    });
    expect(withinToday([alive], new Set(), NOW)).toEqual([]);
  });

  it('人从 timeline 捡回来的旧会话留下', () => {
    const old = card({ session_id: 'old', last_reply_at: NOW - 10 * 24 * HOUR });
    expect(withinToday([old], new Set(['old']), NOW).map((s) => s.session_id)).toEqual(['old']);
  });

  it('捡回来的名单只认传进来的那几场', () => {
    const a = card({ session_id: 'a', last_reply_at: NOW - 10 * 24 * HOUR });
    const b = card({ session_id: 'b', last_reply_at: NOW - 10 * 24 * HOUR });
    expect(withinToday([a, b], new Set(['b']), NOW).map((s) => s.session_id)).toEqual(['b']);
  });

  it('父会话今天说过话，也不把几天前派出去的 worker 拉进来', () => {
    // 2026-10-19 的缺陷：一场今天回过话的父会话带出 41 场几天前的 worker，
    // 左栏看起来跟没筛一样。父子不再连坐，各看各的。
    const parent = card({ session_id: 'p', last_reply_at: NOW - HOUR });
    const oldKid = card({
      session_id: 'k-old',
      parent_session_id: 'p',
      origin: 'worker',
      last_reply_at: NOW - 30 * HOUR,
    });
    expect(withinToday([parent, oldKid], new Set(), NOW).map((s) => s.session_id)).toEqual([
      'p',
    ]);
  });

  it('子会话自己今天说过话就留下', () => {
    const kid = card({
      session_id: 'k',
      parent_session_id: 'p',
      origin: 'worker',
      last_reply_at: NOW - HOUR,
    });
    expect(withinToday([kid], new Set(), NOW).map((s) => s.session_id)).toEqual(['k']);
  });

  it('留下的那些保持原来的顺序', () => {
    const parent = card({ session_id: 'p', last_reply_at: NOW - HOUR });
    const other = card({ session_id: 'o', last_reply_at: NOW - 2 * HOUR });
    const oldKid = card({
      session_id: 'k-old',
      parent_session_id: 'p',
      last_reply_at: NOW - 30 * HOUR,
    });
    expect(
      withinToday([parent, other, oldKid], new Set(), NOW).map((s) => s.session_id)
    ).toEqual(['p', 'o']);
  });

  it('本机管理（定时任务等）会话及其子 worker 默认不混入今日列表，显式捡回今日时放行', () => {
    const sched = card({
      session_id: 'core_sched',
      local_ops: true,
      last_reply_at: NOW - 10 * 60_000,
    });
    const schedWorker = card({
      session_id: 'core_sched_worker',
      origin: 'worker',
      parent_session_id: 'core_sched',
      last_reply_at: NOW - 5 * 60_000,
    });
    const human = card({
      session_id: 'human_today',
      last_reply_at: NOW - 5 * 60_000,
    });
    expect(withinToday([sched, schedWorker, human], new Set(), NOW).map((s) => s.session_id)).toEqual([
      'human_today',
    ]);
    expect(
      withinToday([sched, schedWorker, human], new Set(['core_sched']), NOW).map((s) => s.session_id)
    ).toEqual(['core_sched', 'core_sched_worker', 'human_today']);
  });

  it('当主会话被添加到 Today 时，它的 branched 会话、worker 会话与分支的 worker 一起进入 Today', () => {
    const main = card({ session_id: 'main', last_reply_at: NOW - 10 * 24 * HOUR });
    const mainWorker = card({
      session_id: 'main-w',
      origin: 'worker',
      parent_session_id: 'main',
      last_reply_at: NOW - 10 * 24 * HOUR,
    });
    const branch = card({
      session_id: 'branch-1',
      parent_session_id: 'main',
      relation: { kind: 'branch', closed: false },
      last_reply_at: NOW - 9 * 24 * HOUR,
    });
    const branchWorker = card({
      session_id: 'branch-1-w',
      origin: 'worker',
      parent_session_id: 'branch-1',
      last_reply_at: NOW - 9 * 24 * HOUR,
    });
    const unrelated = card({
      session_id: 'unrelated',
      last_reply_at: NOW - 10 * 24 * HOUR,
    });

    expect(
      withinToday(
        [main, mainWorker, branch, branchWorker, unrelated],
        new Set(['main']),
        NOW
      ).map((s) => s.session_id)
    ).toEqual(['main', 'main-w', 'branch-1', 'branch-1-w']);
  });

  it('当 branched 会话被添加到 Today 时，其主会话、主会话的 worker、兄弟分支及自身 worker 也全部一起进入 Today', () => {
    const main = card({ session_id: 'main', last_reply_at: NOW - 10 * 24 * HOUR });
    const mainWorker = card({
      session_id: 'main-w',
      origin: 'worker',
      parent_session_id: 'main',
      last_reply_at: NOW - 10 * 24 * HOUR,
    });
    const branch1 = card({
      session_id: 'branch-1',
      parent_session_id: 'main',
      relation: { kind: 'branch', closed: false },
      last_reply_at: NOW - 9 * 24 * HOUR,
    });
    const branch2 = card({
      session_id: 'branch-2',
      parent_session_id: 'main',
      relation: { kind: 'branch', closed: false },
      last_reply_at: NOW - 8 * 24 * HOUR,
    });
    const branch1Worker = card({
      session_id: 'branch-1-w',
      origin: 'worker',
      parent_session_id: 'branch-1',
      last_reply_at: NOW - 9 * 24 * HOUR,
    });

    expect(
      withinToday(
        [main, mainWorker, branch1, branch2, branch1Worker],
        new Set(['branch-1']),
        NOW
      ).map((s) => s.session_id)
    ).toEqual(['main', 'main-w', 'branch-1', 'branch-2', 'branch-1-w']);
  });
});
