import { describe, expect, it } from 'vitest';
import type { ObserverTaskItem } from '@/hooks/useSessionObserver';
import {
  formatCollapsedTaskIdsSummary,
  isCompletedWatcherTask,
  partitionTasksForOverview,
} from '../tasksOverview';

function makeTask(
  id: string,
  status: ObserverTaskItem['status'] | string,
  title = `事项 ${id}`
): ObserverTaskItem {
  return {
    id,
    proposed_at: 1_753_800_000_000,
    title,
    status: status as ObserverTaskItem['status'],
    actor: '主会话',
    conclusion: `${id} 结论`,
  };
}

describe('tasksOverview utilities', () => {
  it('准确识别各类已完结状态与活跃状态，绝不误判进行中/待拍板/阻塞任务', () => {
    expect(isCompletedWatcherTask({ status: 'done' })).toBe(true);
    expect(isCompletedWatcherTask({ status: 'completed' })).toBe(true);
    expect(isCompletedWatcherTask({ status: 'Completed' })).toBe(true);
    expect(isCompletedWatcherTask({ status: '✅ 已完成' })).toBe(true);
    expect(isCompletedWatcherTask({ status: '已完结' })).toBe(true);
    expect(isCompletedWatcherTask({ status: '已收口' })).toBe(true);
    expect(isCompletedWatcherTask({ status: '已归档' })).toBe(true);

    expect(isCompletedWatcherTask({ status: 'doing' })).toBe(false);
    expect(isCompletedWatcherTask({ status: 'waiting' })).toBe(false);
    expect(isCompletedWatcherTask({ status: 'blocked' })).toBe(false);
    expect(isCompletedWatcherTask({ status: 'error' })).toBe(false);
    expect(isCompletedWatcherTask({ status: 'failed' })).toBe(false);
    expect(isCompletedWatcherTask({ status: 'aborted' })).toBe(false);
    expect(isCompletedWatcherTask({ status: '异常' })).toBe(false);
    expect(isCompletedWatcherTask({ status: '❌ 失败' })).toBe(false);
    expect(isCompletedWatcherTask({ status: '' })).toBe(false);
  });

  it('error / failed 异常行绝不折叠进已完结隐藏分区，即使末尾全部是完结与异常混排', () => {
    const tasks = [
      makeTask('T1', 'done'),
      makeTask('T2', 'done'),
      makeTask('T3', 'done'),
      makeTask('T4', 'error'),
    ];
    const part = partitionTasksForOverview(tasks);
    expect(part.canCollapse).toBe(true);
    expect(part.hiddenCompletedTasks.map((t) => t.id)).toEqual(['T1', 'T2', 'T3']);
    expect(part.visibleTasks.map((t) => t.id)).toEqual(['T4']);
    expect(part.visibleTasks[0]?.status).toBe('error');

    const errorOnlyTail = [
      makeTask('T1', 'done'),
      makeTask('T2', 'done'),
      makeTask('T3', 'error'),
      makeTask('T4', 'failed'),
    ];
    const p2 = partitionTasksForOverview(errorOnlyTail);
    expect(p2.visibleTasks.map((t) => t.id)).toEqual(['T3', 'T4']);
    expect(p2.hiddenCompletedTasks.map((t) => t.id)).toEqual(['T1', 'T2']);
  });

  it('存在活跃事项且已完结行 >= 2 时自动折叠全部已完结行并指定最后一条完结行为渐变预览行', () => {
    const tasks = [
      makeTask('T1', 'done'),
      makeTask('T2', 'done'),
      makeTask('T3', 'done'),
      makeTask('T4', 'doing'),
      makeTask('T5', 'waiting'),
    ];
    const part = partitionTasksForOverview(tasks);
    expect(part.canCollapse).toBe(true);
    expect(part.hiddenCompletedTasks.map((t) => t.id)).toEqual(['T1', 'T2', 'T3']);
    expect(part.visibleTasks.map((t) => t.id)).toEqual(['T4', 'T5']);
    expect(part.peekTask?.id).toBe('T3');
    expect(part.hiddenIdSummary).toBe('T1–T3');
  });

  it('不连续或总行数 >= 4 含单条完结行时也能正确折叠并生成准确编号摘要', () => {
    const interleaved = [
      makeTask('T1', 'done'),
      makeTask('T2', 'doing'),
      makeTask('T3', 'done'),
      makeTask('T4', 'blocked'),
    ];
    const p1 = partitionTasksForOverview(interleaved);
    expect(p1.canCollapse).toBe(true);
    expect(p1.hiddenCompletedTasks.map((t) => t.id)).toEqual(['T1', 'T3']);
    expect(p1.visibleTasks.map((t) => t.id)).toEqual(['T2', 'T4']);
    expect(p1.peekTask?.id).toBe('T3');
    expect(p1.hiddenIdSummary).toBe('T1、T3');

    const fourWithOneDone = [
      makeTask('T1', 'done'),
      makeTask('T2', 'doing'),
      makeTask('T3', 'doing'),
      makeTask('T4', 'waiting'),
    ];
    const p2 = partitionTasksForOverview(fourWithOneDone);
    expect(p2.canCollapse).toBe(true);
    expect(p2.hiddenCompletedTasks.map((t) => t.id)).toEqual(['T1']);
    expect(p2.visibleTasks.map((t) => t.id)).toEqual(['T2', 'T3', 'T4']);
    expect(p2.hiddenIdSummary).toBe('T1');
  });

  it('全表均已完结时：长列表保留最近 2 条兜底可见，短表(<=3)不触发空壳折叠', () => {
    const shortAllDone = [makeTask('T1', 'done'), makeTask('T2', 'done'), makeTask('T3', 'done')];
    expect(partitionTasksForOverview(shortAllDone).canCollapse).toBe(false);

    const longAllDone = [
      makeTask('T1', 'done'),
      makeTask('T2', 'done'),
      makeTask('T3', 'done'),
      makeTask('T4', 'done'),
      makeTask('T5', 'done'),
    ];
    const part = partitionTasksForOverview(longAllDone);
    expect(part.canCollapse).toBe(true);
    expect(part.hiddenCompletedTasks.map((t) => t.id)).toEqual(['T1', 'T2', 'T3']);
    expect(part.visibleTasks.map((t) => t.id)).toEqual(['T4', 'T5']);
    expect(part.peekTask?.id).toBe('T3');
    expect(part.hiddenIdSummary).toBe('T1–T3');
  });

  it('长非连续列表编号摘要超过 3 个时省略中间段', () => {
    const tasks = [
      makeTask('T1', 'done'),
      makeTask('T3', 'done'),
      makeTask('T5', 'done'),
      makeTask('T7', 'done'),
    ];
    expect(formatCollapsedTaskIdsSummary(tasks)).toBe('T1 … T7');
  });
});
