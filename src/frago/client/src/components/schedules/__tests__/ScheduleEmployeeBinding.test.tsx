import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import SchedulePage from '../SchedulePage';
import type { ScheduleItem, ScheduleWritePayload } from '@/api';
import type { EmployeeItem } from '@/types/api';

const getSchedules = vi.fn();
const getEmployees = vi.fn();
const getRecipes = vi.fn();
const createSchedule = vi.fn();
const updateSchedule = vi.fn();
const previewScheduleRuns = vi.fn();
const runSchedule = vi.fn();
const toggleSchedule = vi.fn();
const removeSchedule = vi.fn();
const composeSchedule = vi.fn();
const switchPage = vi.fn();
const setWorkbenchSessionId = vi.fn();

vi.mock('@/api', () => ({
  getSchedules: () => getSchedules(),
  getEmployees: () => getEmployees(),
  getRecipes: () => getRecipes(),
  createSchedule: (payload: ScheduleWritePayload) => createSchedule(payload),
  updateSchedule: (id: string, payload: ScheduleWritePayload) =>
    updateSchedule(id, payload),
  previewScheduleRuns: (payload: unknown) => previewScheduleRuns(payload),
  runSchedule: (id: string) => runSchedule(id),
  toggleSchedule: (id: string) => toggleSchedule(id),
  removeSchedule: (id: string) => removeSchedule(id),
  composeSchedule: (text: string) => composeSchedule(text),
}));

vi.mock('@/stores/pageStore', () => ({
  usePageStore: (selector: (s: unknown) => unknown) =>
    selector({
      currentScheduleId: null,
      switchPage,
      setWorkbenchSessionId,
    }),
}));

vi.mock('@/stores/appStore', () => ({
  usePageStore: (selector: (s: unknown) => unknown) =>
    selector({
      currentScheduleId: null,
      switchPage,
      setWorkbenchSessionId,
    }),
}));

const EMPLOYEES: EmployeeItem[] = [
  {
    member_post_id: 'frago-pm',
    title: 'Frago 产品经理',
    description: '需求评审与发版签收',
    agent_kernel: 'claude',
    cwd: '/Users/frago/Repos/frago',
    color: 'blue',
    recipes: ['frago-dev'],
    knowledge_domains: ['frago-pm'],
  },
  {
    member_post_id: 'quant-researcher',
    title: '量化研究员',
    description: '美股盘前异动与财报扫描',
    agent_kernel: 'codex',
    cwd: '/Users/frago/Workspace/quant',
    color: 'violet',
    recipes: ['market-scan'],
    knowledge_domains: [],
  },
];

const EMP_SCHEDULE: ScheduleItem = {
  id: 'sch_emp_01',
  name: '盘前异动巡检',
  kind: 'employee',
  employee_id: 'quant-researcher',
  employee_title: '量化研究员',
  employee_kernel: 'codex',
  employee_cwd: '/Users/frago/Workspace/quant',
  employee_missing: false,
  session_title_template: '[{date} {weekday}] {employee} · {schedule_name}',
  prompt: '检查隔夜美股核心标的异动并给出简报',
  recipe: null,
  command: null,
  cwd: null,
  instructions: null,
  allowed_tools: [],
  disallowed_tools: [],
  params: {},
  interval_seconds: null,
  cron: '0 8 * * 1-5',
  overlap: 'skip',
  timeout: 7200,
  start_at: null,
  end_at: null,
  enabled: true,
  created_at: '2026-11-24T00:00:00Z',
  last_run_at: '2026-11-24T08:00:00Z',
  last_status: 'success',
  last_success_at: '2026-11-24T08:00:00Z',
  last_session_id: 'sess_emp_run_01',
  last_session_title: '[11-24 Tue] quant-researcher · 盘前异动巡检',
  consecutive_failures: 0,
  run_count: 4,
  notify: { on: 'change', to: 'feishu', context: {} },
  history: [
    {
      triggered_at: '2026-11-24T08:00:00Z',
      status: 'success',
      session_id: 'sess_emp_run_01',
      session_title: '[11-24 Tue] quant-researcher · 盘前异动巡检',
      duration_ms: 1230,
      exit_code: 0,
      answer: 'NVDA +2.1%',
    },
  ],
  next_run_at: '2026-11-25T08:00:00Z',
  running: false,
};

const COMMAND_SCHEDULE: ScheduleItem = {
  ...EMP_SCHEDULE,
  id: 'sch_cmd_01',
  name: 'Legacy agent shell job',
  kind: 'command',
  employee_id: null,
  employee_title: null,
  employee_kernel: null,
  employee_cwd: null,
  employee_missing: false,
  session_title_template: null,
  prompt: null,
  command: 'frago agent run frago-pm "check"',
  last_session_id: null,
  last_session_title: null,
  history: [],
};

const MISSING_EMP_SCHEDULE: ScheduleItem = {
  ...EMP_SCHEDULE,
  id: 'sch_missing_01',
  name: 'Orphaned employee job',
  employee_id: 'retired-agent',
  employee_title: '已离职员工',
  employee_missing: true,
};

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  vi.clearAllMocks();
  getEmployees.mockResolvedValue(EMPLOYEES);
  getRecipes.mockResolvedValue([{ name: 'market-scan', description: 'Scan market' }]);
  previewScheduleRuns.mockResolvedValue({
    runs: [
      { seq: 1, triggered_at: '11-25 08:00', session_title: '[11-25] remote #1' },
      { seq: 2, triggered_at: '11-26 08:00', session_title: '[11-26] remote #2' },
      { seq: 3, triggered_at: '11-27 08:00', session_title: '[11-27] remote #3' },
    ],
  });
  getSchedules.mockResolvedValue({
    scheduler_running: true,
    schedules: [EMP_SCHEDULE, COMMAND_SCHEDULE],
  });
});

describe('Plan 1A Schedule Native Employee Binding', () => {
  it('列表视图展示员工彩标与末次动态标题，并可进入详情归属态与跳回会话', async () => {
    render(<SchedulePage />);

    expect((await screen.findByTestId('sc-row-emp-sch_emp_01')).textContent).toContain(
      '@quant-researcher'
    );
    expect(
      screen.getByText('[11-24 Tue] quant-researcher · 盘前异动巡检')
    ).toBeTruthy();

    fireEvent.click(screen.getByText('盘前异动巡检'));

    expect(await screen.findByTestId('sc-detail-workspace')).toBeTruthy();
    expect(screen.getByTestId('sc-ownership-badge').textContent).toContain(
      '@quant-researcher'
    );
    expect(
      screen.getByText(/Inherited from employee profile: \/Users\/frago\/Workspace\/quant/)
    ).toBeTruthy();

    const openButtons = screen.getAllByRole('button', { name: /See the whole run/i });
    fireEvent.click(openButtons[0]);
    expect(setWorkbenchSessionId).toHaveBeenCalledWith('sess_emp_run_01');
    expect(switchPage).toHaveBeenCalledWith('session_workbench');
  });

  it('新建态两层选择器筛选绑定员工、插入标题变量预览并按正确字段提交 createSchedule', async () => {
    const created: ScheduleItem = {
      ...EMP_SCHEDULE,
      id: 'sch_new_01',
      name: 'Pre-market check',
    };
    createSchedule.mockResolvedValue(created);

    render(<SchedulePage />);
    await screen.findByText('盘前异动巡检');

    fireEvent.click(screen.getByTestId('sc-tab-edit'));
    expect(await screen.findByTestId('sc-edit-pane')).toBeTruthy();

    // Two-tier warning check for command primitive
    fireEvent.click(screen.getByTestId('sc-kind-command'));
    expect(screen.getByTestId('sc-command-warn')).toBeTruthy();
    fireEvent.click(screen.getByTestId('sc-kind-employee'));

    // Filter non-Claude employees & search
    fireEvent.click(screen.getByTestId('sc-emp-filter-nonclaude'));
    expect(screen.queryByTestId('sc-emp-row-frago-pm')).toBeNull();
    expect(screen.getByTestId('sc-emp-row-quant-researcher')).toBeTruthy();

    fireEvent.click(screen.getByTestId('sc-emp-row-quant-researcher'));
    expect(screen.getByTestId('sc-selected-emp-box').textContent).toContain(
      '@quant-researcher'
    );

    // Fill name, prompt, timeout (30 min -> 1800s), insert {run_seq} template var
    fireEvent.change(screen.getByTestId('sc-inp-name'), {
      target: { value: 'Pre-market check' },
    });
    fireEvent.change(screen.getByTestId('sc-inp-timeout'), {
      target: { value: '30' },
    });
    fireEvent.change(screen.getByTestId('sc-inp-emp-prompt'), {
      target: { value: 'Review overnight futures' },
    });
    fireEvent.click(screen.getByTestId('sc-vchip-seq'));
    expect((screen.getByTestId('sc-tpl-input') as HTMLInputElement).value).toContain(
      '#{seq}'
    );

    await waitFor(() =>
      expect(screen.getByTestId('sc-title-preview-list').textContent).toContain(
        '[11-25] remote #1'
      )
    );

    fireEvent.click(screen.getByTestId('sc-save-btn'));
    await waitFor(() => expect(createSchedule).toHaveBeenCalledTimes(1));

    const payload = createSchedule.mock.calls[0][0] as ScheduleWritePayload;
    expect(payload.kind).toBe('employee');
    expect(payload.employee_id).toBe('quant-researcher');
    expect(payload.timeout).toBe(1800);
    expect(payload.notify?.on).toBe('change');
    expect(payload.session_title_template).toContain('#{seq}');
    expect(payload.prompt).toBe('Review overnight futures');
  });

  it('命令型任务详情展示迁移提示，缺失员工的任务编辑需重绑后才允许保存 updateSchedule', async () => {
    getSchedules.mockResolvedValue({
      scheduler_running: true,
      schedules: [COMMAND_SCHEDULE, MISSING_EMP_SCHEDULE],
    });
    updateSchedule.mockResolvedValue({
      ...MISSING_EMP_SCHEDULE,
      employee_id: 'frago-pm',
      employee_missing: false,
    });

    render(<SchedulePage />);
    await screen.findByText('Legacy agent shell job');

    // Command schedule shows migration notice and jumps to edit mode
    fireEvent.click(screen.getByText('Legacy agent shell job'));
    expect(await screen.findByTestId('sc-detail-command-notice')).toBeTruthy();
    fireEvent.click(screen.getByTestId('sc-switch-native-btn'));
    expect(await screen.findByTestId('sc-edit-pane')).toBeTruthy();

    // Missing employee schedule blocks saving until re-bound
    fireEvent.click(screen.getByTestId('sc-sidebar-item-sch_missing_01'));
    expect(await screen.findByTestId('sc-detail-emp-missing')).toBeTruthy();
    fireEvent.click(screen.getByTestId('sc-detail-edit-btn'));
    expect(await screen.findByTestId('sc-emp-missing-warn')).toBeTruthy();

    fireEvent.click(screen.getByTestId('sc-save-btn'));
    expect(updateSchedule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('sc-emp-row-frago-pm'));
    fireEvent.click(screen.getByTestId('sc-save-btn'));
    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith(
        'sch_missing_01',
        expect.objectContaining({
          kind: 'employee',
          employee_id: 'frago-pm',
        })
      )
    );
  });
});
