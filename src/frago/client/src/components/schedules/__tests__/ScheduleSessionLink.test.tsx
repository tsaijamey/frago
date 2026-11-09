import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ScheduleDetail from '../ScheduleDetail';
import type { ScheduleItem } from '@/api';
import { usePageStore } from '@/stores/pageStore';

vi.mock('react-i18next', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-i18next')>();
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, opts?: any) => {
        if (opts?.defaultValue) return opts.defaultValue;
        if (key === 'schedules.history.openSession') return '查看会话';
        return key;
      },
    }),
  };
});

const mockSchedule: ScheduleItem = {
  id: 'sch_test_01',
  name: '测试员工调度任务',
  kind: 'command',
  prompt: null,
  recipe: null,
  command: 'frago employee invoke frago-developer "test"',
  cwd: '/Users/frago',
  instructions: null,
  allowed_tools: [],
  disallowed_tools: [],
  params: {},
  interval_seconds: 3600,
  cron: null,
  overlap: 'skip',
  timeout: 7200,
  start_at: null,
  end_at: null,
  enabled: true,
  created_at: '2026-11-08T00:00:00Z',
  last_run_at: '2026-11-08T01:00:00Z',
  last_status: 'success',
  last_success_at: '2026-11-08T01:00:00Z',
  last_session_id: 'core_06693a0153b34972bbec9039606f560f',
  last_run: {
    session_id: 'core_06693a0153b34972bbec9039606f560f',
    status: 'success',
    triggered_at: '2026-11-08T01:00:00Z',
  },
  consecutive_failures: 0,
  run_count: 1,
  notify: { on: 'never', to: null, context: {} },
  history: [
    {
      triggered_at: '2026-11-08T01:00:00Z',
      status: 'success',
      session_id: 'core_06693a0153b34972bbec9039606f560f',
      exit_code: 0,
    },
  ],
  next_run_at: '2026-11-08T02:00:00Z',
  running: false,
};

describe('ScheduleSessionLink', () => {
  beforeEach(() => {
    usePageStore.setState({
      currentPage: 'schedules',
      workbenchSessionId: null,
    });
  });

  it('ScheduleDetail 渲染并在 lastRun 中展示跳转会话按钮且可点击跳转', () => {
    render(
      <ScheduleDetail
        schedule={mockSchedule}
        busy={null}
        onRun={vi.fn()}
        onToggle={vi.fn()}
        onRemove={vi.fn()}
        onClose={vi.fn()}
      />
    );

    const openButtons = screen.getAllByRole('button', { name: /查看会话/i });
    expect(openButtons.length).toBeGreaterThanOrEqual(1);

    // 点击第一处的跳转按钮（位于 lastRun 属性栏）
    fireEvent.click(openButtons[0]);

    expect(usePageStore.getState().currentPage).toBe('session_workbench');
    expect(usePageStore.getState().workbenchSessionId).toBe(
      'core_06693a0153b34972bbec9039606f560f'
    );
  });
});
