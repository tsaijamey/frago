/**
 * 换语言这一下，会话页上的字必须当场跟着变——不许要人刷新页面。
 *
 * 盯的是最容易漏的那一类：状态名（在跑／出错／已完成／停着）与镜头名（全部／对话／
 * 旁路注入／工具／系统）从前是**模块级常量**，模块加载时把字取出来存住，此后语言换成
 * 什么都跟它无关。左栏与中栏各有一片这样的字，切到英文时整片纹丝不动，正是这次要消灭的
 * 病。所以这里不是断言"英文文案写得对"，而是断言"这些字是在渲染时取的"。
 */

import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';

import i18n from '@/i18n';
import SessionRail from '../SessionRail';
import RecordStream from '../RecordStream';
import RecordCard from '../RecordCard';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchSession, WorkbenchSessionsState } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const NOOP = () => {};

/** 换语言会让一大片组件重渲染，包进 act 里等它落定。 */
async function switchTo(lang: 'zh' | 'en') {
  await act(async () => {
    await i18n.changeLanguage(lang);
  });
}

/** 每个用例都从中文起步：上一个用例把语言留在英文，下一个就从错的地方开始了。 */
beforeEach(async () => {
  await i18n.changeLanguage('zh');
});

afterAll(async () => {
  await i18n.changeLanguage('zh');
});

function session(over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>): WorkbenchSession {
  return {
    family: 'claude-code',
    title: '会话工作台 webUI',
    directory: '/Users/frago/Repos/frago',
    created_at: 1_753_700_000_000,
    last_active_at: 1_753_800_000_000,
    last_reply_at: null,
    agent_paths: [],
    status: 'running',
    digest_done: null,
    digest_stuck: null,
    ...over,
  };
}

function railState(rows: WorkbenchSession[]): WorkbenchSessionsState {
  return {
    sessions: rows,
    visible: rows,
    searched: rows,
    loading: false,
    error: null,
    search: '',
    setSearch: NOOP,
    status: 'all',
    setStatus: NOOP,
    days: 0,
    setDays: NOOP,
    counts: { all: rows.length, running: rows.length, error: 0, done: 0, idle: 0 },
    content: { query: '', matches: new Map(), searching: false, warnings: [], error: null },
    reload: async () => {},
  };
}

describe('换语言不用刷新页面', () => {
  it('左栏的状态名当场跟着变', async () => {
    render(
      <SessionRail state={railState([session({ session_id: SID })])} selectedId={null} onSelect={NOOP} />
    );
    // 卡上一处、筛选行一处，两处说的是同一个词。
    expect(screen.getAllByText('在跑').length).toBeGreaterThan(0);

    await switchTo('en');
    expect(screen.getAllByText('Running').length).toBeGreaterThan(0);
    expect(screen.queryByText('在跑')).toBeNull();

    await switchTo('zh');
    expect(screen.getAllByText('在跑').length).toBeGreaterThan(0);
  });

  it('中栏的镜头名当场跟着变', async () => {
    const records: WorkbenchRecord[] = [
      {
        id: 'a',
        session_id: SID,
        group_id: null,
        seq: 0,
        ts: 1_753_800_000_000,
        kind: 'agent.say',
        agent_path: [],
        payload: { text: '好的' },
        raw_available: true,
      },
    ];
    render(
      <RecordStream
        sessionId={SID}
        records={records}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={NOOP}
      />
    );
    expect(screen.getByTestId('lens-hook').textContent).toContain('旁路注入');

    await switchTo('en');
    expect(screen.getByTestId('lens-hook').textContent).toContain('Hook injections');
  });

  it('记录卡的形态名与已发生的量当场跟着变', async () => {
    const record: WorkbenchRecord = {
      id: 'r',
      session_id: SID,
      group_id: null,
      seq: 0,
      ts: 1_753_800_000_000,
      kind: 'tool.result',
      agent_path: [],
      payload: { tool_name: 'Bash', status: 'ok', body: 'done', duration_ms: 2190 },
      raw_available: true,
    };
    const { container } = render(<RecordCard record={record} sessionId={SID} />);
    expect(container.textContent).toContain('成功');
    // 时长是纯函数拼的，它同样得跟着语言走。
    expect(container.textContent).toContain('耗时 2.2 秒');

    await switchTo('en');
    expect(container.textContent).toContain('OK');
    expect(container.textContent).toContain('took 2.2 s');
  });
});
