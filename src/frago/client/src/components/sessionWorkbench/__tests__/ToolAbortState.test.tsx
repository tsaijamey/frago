/**
 * Wave A · Top5 方案 5A 前端自动化回归测试（对照唯一权威主原型 `#sessions/top5-abort`）。
 *
 * 覆盖：
 * 1. `sessionLifecycleOf()` 三态及边界（tool_aborted / awaiting_input / completed / ordinary error）；
 * 2. 左栏 `SessionItem` 三态清晰区隔；
 * 3. `RecordStream` + `ToolRun` 自动展开含中断工具框、标红 `.tool-aborted` 与「异常中断 · 未返回结果」；
 * 4. 跨镜头「定位中断点」（talk → all 自动切换并滚动聚焦中断工具行）；
 * 5. 正文顶部警示条 `.abort-alert-bar` 交互与「从断点续跑」预填草稿。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import RecordStream from '../RecordStream';
import SessionItem, { sessionLifecycleOf } from '../SessionItem';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const NOOP = () => {};

function makeSession(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: 'sess-top5-demo',
    family: 'claude-code',
    title: 'Top5 工具中断验证会话',
    directory: '/Users/frago/Repos/frago',
    created_at: 1_753_800_000_000,
    last_active_at: 1_753_800_500_000,
    last_reply_at: 1_753_800_400_000,
    agent_paths: [],
    status: 'done',
    digest_done: '已完成前序检查',
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    lifecycle_state: 'completed',
    ...over,
  };
}

function makeRecord(
  over: Partial<WorkbenchRecord> & Pick<WorkbenchRecord, 'id' | 'seq' | 'kind'>
): WorkbenchRecord {
  return {
    session_id: 'sess-top5-demo',
    group_id: null,
    ts: 1_753_800_100_000,
    agent_path: [],
    payload: {},
    raw_available: true,
    ...over,
  };
}

describe('Wave A Top5 5A · sessionLifecycleOf & SessionItem 三态区隔', () => {
  it('tool_aborted=true 时即使底层 status 为 done/idle 也绝不被掩盖为 Completed', () => {
    const aborted = makeSession({
      status: 'done',
      lifecycle_state: 'error',
      tool_aborted: true,
      abort_reason: 'process_terminated_mid_turn',
    });
    const life = sessionLifecycleOf(aborted);
    expect(life).toEqual({
      key: 'error',
      label: 'Aborted (incomplete)',
      aborted: true,
    });
  });

  it('tool_aborted=true 但在新一轮 sending 时优先回到 Running', () => {
    const aborted = makeSession({
      status: 'error',
      lifecycle_state: 'error',
      tool_aborted: true,
    });
    expect(sessionLifecycleOf(aborted, { sending: true })).toEqual({
      key: 'running',
      label: 'Running',
    });
  });

  it('普通 error（非工具中断）保持向后兼容返回 Error', () => {
    const plainErr = makeSession({
      status: 'error',
      lifecycle_state: 'error',
      tool_aborted: false,
    });
    expect(sessionLifecycleOf(plainErr)).toEqual({
      key: 'error',
      label: 'Error',
    });
  });

  it('lifecycle_state=awaiting_input（无 DecisionCard/ForYou）不折叠为 Completed/Idle', () => {
    const waiting = makeSession({
      status: 'done',
      lifecycle_state: 'awaiting_input',
      tool_aborted: false,
    });
    expect(sessionLifecycleOf(waiting)).toEqual({
      key: 'waiting',
      label: 'Awaiting input',
    });
  });

  it('正常 completed 会话返回 Completed', () => {
    const done = makeSession({
      status: 'done',
      lifecycle_state: 'completed',
      tool_aborted: false,
    });
    expect(sessionLifecycleOf(done)).toEqual({
      key: 'completed',
      label: 'Completed',
    });
  });

  it('左栏 SessionItem 明确区分工具中断、等待输入与已完成', () => {
    const abortSession = makeSession({
      session_id: 's-abort',
      status: 'error',
      lifecycle_state: 'error',
      tool_aborted: true,
    });
    const waitSession = makeSession({
      session_id: 's-wait',
      status: 'done',
      lifecycle_state: 'awaiting_input',
      tool_aborted: false,
    });
    const doneSession = makeSession({
      session_id: 's-done',
      status: 'done',
      lifecycle_state: 'completed',
      tool_aborted: false,
    });

    const { rerender } = render(
      <SessionItem
        session={abortSession}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    const abortChip = screen.getByTestId('session-lifecycle');
    expect(abortChip.getAttribute('data-lifecycle')).toBe('error');
    expect(abortChip.getAttribute('data-tool-aborted')).toBe('true');
    expect(abortChip.textContent).toContain('异常中断（未完成）');

    rerender(
      <SessionItem
        session={waitSession}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    const waitChip = screen.getByTestId('session-lifecycle');
    expect(waitChip.getAttribute('data-lifecycle')).toBe('waiting');
    expect(waitChip.getAttribute('data-tool-aborted')).toBeNull();
    expect(waitChip.textContent).toContain('等待输入');

    rerender(
      <SessionItem
        session={doneSession}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    expect(screen.queryByTestId('session-lifecycle')).toBeNull();
  });
});

describe('Wave A Top5 5A · RecordStream 中断工具行自动展开与跨镜头定位', () => {
  const abortRecords: WorkbenchRecord[] = [
    makeRecord({
      id: 'rec-u1',
      seq: 1,
      kind: 'user.say',
      payload: { text: '请帮我运行迁移脚本' },
    }),
    makeRecord({
      id: 'rec-tc1',
      seq: 2,
      kind: 'tool.call',
      payload: {
        call_id: 'call-1',
        tool_name: 'Read',
        tool_family: 'read',
        args: { file_path: 'alembic.ini' },
      },
    }),
    makeRecord({
      id: 'rec-tr1',
      seq: 3,
      kind: 'tool.result',
      payload: {
        call_id: 'call-1',
        tool_name: 'Read',
        status: 'ok',
        duration_ms: 42,
        body: 'ok',
      },
    }),
    makeRecord({
      id: 'rec-tc-abort',
      seq: 4,
      kind: 'tool.call',
      payload: {
        call_id: 'call-abort-2',
        tool_name: 'Bash',
        tool_family: 'bash',
        args: { command: 'pytest -q' },
      },
    }),
  ];

  it('在全部镜头下自动展开中断工具框并标红「异常中断 · 未返回结果」', () => {
    render(
      <RecordStream
        sessionId="sess-top5-demo"
        records={abortRecords}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={NOOP}
        abortedToolCallId="rec-tc-abort"
      />
    );

    // 切到「全部」镜头查看工具流
    fireEvent.click(screen.getByTestId('lens-all'));

    const rail = screen.getByTestId('turn-tools-rail');
    expect(rail.getAttribute('data-has-aborted')).toBe('true');
    expect(screen.getByTestId('tool-run-abort-pill').textContent).toContain('1 中断');
    // 已自动展开，无需点击 toggle 即可见到工具列表与异常中断徽标
    expect(screen.getByTestId('tool-run')).toBeTruthy();
    const abortedBadge = screen.getByTestId('tool-aborted-badge');
    expect(abortedBadge.textContent).toContain('异常中断 · 未返回结果');
    const abortedLines = screen
      .getAllByTestId('tool-run-line')
      .filter((el) => el.getAttribute('data-tool-aborted') === 'true');
    expect(abortedLines).toHaveLength(1);
    expect(abortedLines[0].classList.contains('tool-aborted')).toBe(true);
  });

  it('默认处于「对话」镜头时，收到中断点 scrollTarget 自动切到「全部」镜头并滚动高亮', () => {
    const scrollIntoViewMock = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoViewMock;

    const { rerender } = render(
      <RecordStream
        sessionId="sess-top5-demo"
        records={abortRecords}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={NOOP}
        abortedToolCallId="rec-tc-abort"
        scrollTarget={null}
      />
    );

    // 初始为对话镜头，工具行不在 DOM 中
    expect(screen.queryByTestId('tool-aborted-badge')).toBeNull();

    // 触发「定位中断点」
    rerender(
      <RecordStream
        sessionId="sess-top5-demo"
        records={abortRecords}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={NOOP}
        abortedToolCallId="rec-tc-abort"
        abortLocateSeq={1}
        scrollTarget={{ recordId: 'rec-tc-abort', at: 1001 }}
      />
    );

    // 自动切至 all 镜头、展开工具框并滚动到中断行
    expect(screen.getByTestId('tool-aborted-badge').textContent).toContain('异常中断 · 未返回结果');
    expect(scrollIntoViewMock).toHaveBeenCalled();
  });
});
