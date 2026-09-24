/**
 * 记录流的连续同类合并。
 *
 * 现有 `RecordCard.test.tsx` 测单卡，这里测跨卡的分段规则：调用与结果按 `call_id` 配对、
 * 结果未到写 running、夹在调用之间的空 hook / 用量 / 空思考并进框里不丢、系统段两种文案、
 * 报错不被压、只并相邻的。
 */

import { beforeAll, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import RecordStream, { collapseRuns, groupSegments, isSilentHook } from '../RecordStream';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

const SID = 'sid-runs';
let seq = 0;

function rec(over: Partial<WorkbenchRecord> & Pick<WorkbenchRecord, 'kind'>): WorkbenchRecord {
  seq += 1;
  return {
    id: `r${seq}`,
    session_id: SID,
    group_id: null,
    seq,
    ts: 1_753_800_000_000 + seq * 1000,
    agent_path: [],
    payload: {},
    raw_available: false,
    ...over,
  };
}

const call = (id: string, name = 'Read', group: string | null = null) =>
  rec({
    kind: 'tool.call',
    group_id: group,
    payload: { call_id: id, tool_name: name, tool_family: 'file-read', args: { file_path: `/x/${id}` } },
  });
const result = (id: string, name = 'Read', group: string | null = null) =>
  rec({ kind: 'tool.result', group_id: group, payload: { call_id: id, tool_name: name, status: 'ok', body: 'ok' } });
const silentHook = () =>
  rec({ kind: 'context.inject', payload: { source: 'hook', hook_event: 'PreToolUse', silent: true } });
const tick = (n: number) => rec({ kind: 'usage.tick', payload: { context_tokens: n, total_tokens: n } });
const state = (field: string) => rec({ kind: 'session.state', payload: { field, to: 'x' } });
const say = (text: string) => rec({ kind: 'agent.say', payload: { text } });

const ALL = { tools: true, system: true };

describe('collapseRuns', () => {
  it('调用与结果按 call_id 配对成一行，夹着的空 hook 与用量并进框里', () => {
    const segs = collapseRuns(
      [call('a'), silentHook(), result('a'), tick(10), call('b'), result('b')],
      ALL
    );
    expect(segs).toHaveLength(1);
    const run = segs[0];
    expect(run.kind).toBe('tools');
    if (run.kind !== 'tools') return;
    expect(run.rows).toHaveLength(2);
    expect(run.rows.every((r) => r.call && r.result)).toBe(true);
    expect(run.extras.map((r) => r.kind)).toEqual(['context.inject', 'usage.tick']);
  });

  it('框尾的透明记录不被框收下，退回去照常分段', () => {
    const segs = collapseRuns([call('a'), result('a'), tick(10), tick(20)], ALL);
    expect(segs.map((s) => s.kind)).toEqual(['tools', 'system']);
  });

  it('只并相邻的：中间隔一句回复就分成两框', () => {
    const segs = collapseRuns([call('a'), result('a'), say('看一下'), call('b'), result('b')], ALL);
    expect(segs.map((s) => s.kind)).toEqual(['tools', 'record', 'tools']);
  });

  it('连续系统记录压成一段；报错不进去', () => {
    const err = rec({ kind: 'error', payload: { scope: 'api', message: 'boom' } });
    const segs = collapseRuns([state('title'), state('mode'), err, state('model')], ALL);
    expect(segs.map((s) => s.kind)).toEqual(['system', 'record', 'system']);
    expect(segs[0].kind === 'system' && segs[0].records).toHaveLength(2);
  });

  it('「系统」档不压系统记录', () => {
    const segs = collapseRuns([state('title'), state('mode')], { tools: true, system: false });
    expect(segs.map((s) => s.kind)).toEqual(['record', 'record']);
  });

  it('跨了两次回复的工具框不归进任何一组', () => {
    const groups = groupSegments(
      collapseRuns([call('a', 'Read', 'm1'), result('a', 'Read', 'm1'), call('b', 'Bash', 'm2')], ALL)
    );
    expect(groups).toHaveLength(1);
    expect(groups[0].groupId).toBeNull();
    expect(groups[0].size).toBe(3);
  });

  it('空正文的 hook 才算「没说话」；说了话或出了错的不算', () => {
    expect(isSilentHook(silentHook())).toBe(true);
    expect(isSilentHook(rec({ kind: 'context.inject', payload: { source: 'hook', body: '请先查手册' } }))).toBe(false);
    expect(isSilentHook(rec({ kind: 'context.inject', payload: { source: 'hook', exit_code: 2 } }))).toBe(false);
  });
});

describe('RecordStream 画出来的样子', () => {
  function stream(records: WorkbenchRecord[]) {
    render(
      <RecordStream
        sessionId={SID}
        records={records}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
      />
    );
    fireEvent.click(screen.getByTestId('lens-all'));
  }

  it('工具框每行一条，结果没到、又是流的最后一段写 running…', () => {
    stream([say('开工'), call('a'), result('a'), call('b')]);
    const run = screen.getByTestId('tool-run');
    const lines = run.querySelectorAll('[data-testid=tool-run-line]');
    expect(lines).toHaveLength(2);
    expect(lines[1].textContent).toContain('running…');
    expect(run.textContent).toContain('2 tool calls');
  });

  it('点一行摊回原来的调用卡与结果卡', () => {
    stream([call('a'), result('a')]);
    fireEvent.click(screen.getByTestId('tool-run-line'));
    expect(document.querySelectorAll('[data-kind="tool.call"]').length).toBe(1);
    expect(document.querySelectorAll('[data-kind="tool.result"]').length).toBe(1);
  });

  it('并进框里的那几条不藏起来：框底报数，点开摊回原卡', () => {
    stream([call('a'), silentHook(), result('a')]);
    const extras = screen.getByTestId('tool-run-extras');
    expect(extras.textContent).toContain('1 more record folded in');
    fireEvent.click(extras);
    expect(screen.getAllByTestId('hook-inject').length).toBe(1);
  });

  it('系统段一行：有调用边界报这一轮耗时', () => {
    stream([say('开工'), state('title'), rec({ kind: 'call.envelope', payload: { duration_ms: 110_000 } })]);
    const line = screen.getByTestId('system-run');
    expect(line.textContent).toContain('2 system records');
    expect(line.textContent).toContain('turn');
  });

  it('系统段一行：没有调用边界就报上下文', () => {
    stream([say('开工'), tick(166_518)]);
    const line = screen.getByTestId('system-run');
    expect(line.textContent).toContain('1 system record');
    expect(line.textContent).toContain('context 166,518');
  });

  it('空正文的 hook 注入缩成一行「Hook <时机>」', () => {
    stream([say('开工'), rec({ kind: 'context.inject', payload: { source: 'hook', hook_event: 'Stop', quiet: true } })]);
    const hook = screen.getByTestId('hook-inject');
    expect(hook.getAttribute('data-empty')).toBe('true');
    expect(hook.textContent).toContain('Hook');
  });
});
