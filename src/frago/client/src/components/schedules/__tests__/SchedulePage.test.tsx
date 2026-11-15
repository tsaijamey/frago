import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import SchedulePage from '../SchedulePage';

const getSchedules = vi.fn();
const runSchedule = vi.fn();
const toggleSchedule = vi.fn();
const restartServer = vi.fn();
const switchPage = vi.fn();

vi.mock('@/api', () => ({
  getSchedules: () => getSchedules(),
  runSchedule: (id: string) => runSchedule(id),
  toggleSchedule: (id: string) => toggleSchedule(id),
  removeSchedule: vi.fn(),
  composeSchedule: vi.fn(),
}));

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  restartServer: () => restartServer(),
}));

vi.mock('@/stores/pageStore', () => ({
  usePageStore: (selector: (s: unknown) => unknown) =>
    selector({
      currentScheduleId: null,
      switchPage,
      setWorkbenchSessionId: vi.fn(),
    }),
}));

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  runSchedule.mockResolvedValue({ status: 'ok' });
  toggleSchedule.mockResolvedValue({});
  restartServer.mockResolvedValue({});
});

describe('P2-4 SchedulePage 失败告警与横幅一步修复', () => {
  it('失败排程整行套 .ui-row-failing、显示 Failed ×2 与 .fix-btn (Run now)，停用调度器横幅带 Restart Scheduler', async () => {
    getSchedules.mockResolvedValue({
      scheduler_running: false,
      schedules: [
        {
          id: 'sch_ok',
          name: 'Daily ok',
          kind: 'command',
          command: 'echo ok',
          cron: '0 9 * * *',
          enabled: true,
          last_status: 'success',
          last_run_at: '2026-10-13T09:00:00Z',
          consecutive_failures: 0,
          run_count: 5,
          history: [],
        },
        {
          id: 'sch_fail',
          name: 'Broken job',
          kind: 'recipe',
          recipe: 'demo',
          cron: '0 * * * *',
          enabled: true,
          last_status: 'failed',
          last_run_at: '2026-10-13T09:10:00Z',
          consecutive_failures: 2,
          run_count: 3,
          history: [],
        },
      ],
    });

    const { container } = render(<SchedulePage />);

    expect(await screen.findByText('Broken job')).toBeTruthy();
    const rows = container.querySelectorAll('tbody tr');
    expect(rows[0].className).not.toContain('ui-row-failing');
    expect(rows[1].className).toContain('ui-row-failing');
    expect(screen.getByText('Failed ×2')).toBeTruthy();

    fireEvent.click(screen.getByTestId('schedule-fix-run-sch_fail'));
    await waitFor(() => expect(runSchedule).toHaveBeenCalledWith('sch_fail'));

    const restartBtn = screen.getByTestId('schedules-restart-scheduler');
    expect(restartBtn.className).toContain('fix-btn');
    expect(restartBtn.className).toContain('warn');
    fireEvent.click(restartBtn);
    await waitFor(() => expect(restartServer).toHaveBeenCalledTimes(1));
  });

  it('全部停用横幅带 Enable & Start 一步启用全部排程', async () => {
    getSchedules.mockResolvedValue({
      scheduler_running: true,
      schedules: [
        {
          id: 'sch_1',
          name: 'Disabled job',
          kind: 'command',
          command: 'echo 1',
          cron: '0 9 * * *',
          enabled: false,
          last_status: null,
          last_run_at: null,
          consecutive_failures: 0,
          run_count: 0,
          history: [],
        },
      ],
    });

    render(<SchedulePage />);
    const enableAllBtn = await screen.findByTestId('schedules-enable-all');
    fireEvent.click(enableAllBtn);
    await waitFor(() => expect(toggleSchedule).toHaveBeenCalledWith('sch_1'));
  });
});
