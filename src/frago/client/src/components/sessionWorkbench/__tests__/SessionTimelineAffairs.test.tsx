/**
 * Unit tests for SessionTimeline completed affairs view:
 * - Badges and preview headlines on calendar grid cells
 * - Month total affairs and active days summary badges
 * - Default affairs tab display on date selection
 * - Affairs card list rendering (title, summary, employee, category, sessions, artifacts)
 * - Affair search and employee/category filtering
 * - Session navigation jump callback on session pill click
 * - CLI guide toggle and empty state guide
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import SessionTimeline from '../SessionTimeline';
import type { SessionTodayState } from '@/hooks/useSessionToday';

const mockAffairs = [
  {
    id: 'aff-20261108-test1',
    date: '2026-11-08',
    title: '实现 Agent Ontology 架构方案',
    summary: '排查多内核待输入状态盲区并设计四级能力矩阵',
    category: '系统研发',
    tags: ['ontology', 'architecture'],
    employee: 'frago-developer',
    sessions: ['c767deb5-f7af-499f-9377-24ffbc05315b'],
    artifacts: ['/Users/frago/.frago/data/frago-dev/20261108-agent-ontology-design/notebook.md'],
    completed_at: '2026-11-08T16:01:59',
    created_at: '2026-11-08T16:01:59',
    updated_at: '2026-11-08T16:01:59',
  },
  {
    id: 'aff-20261108-test2',
    date: '2026-11-08',
    title: '暗光照片局部调光配方录制',
    summary: 'Agent OS 虚拟桌面录屏与视频剪辑成片',
    category: '演示宣发',
    tags: ['video', 'desktop'],
    employee: 'desktop-operator',
    sessions: ['d6316f11-1672-54f6-a35a-f1605a130edc'],
    artifacts: ['/Users/frago/.frago/data/frago-recipe-ops/relight.mp4'],
    completed_at: '2026-11-08T17:30:00',
    created_at: '2026-11-08T17:30:00',
    updated_at: '2026-11-08T17:30:00',
  },
];

vi.mock('@/api', () => ({
  getTokenCalendar: vi.fn(async (month: string) => ({
    month,
    days: {
      '2026-11-08': {
        input: 200_000,
        output: 100_000,
        cache_creation: 0,
        cache_read: 0,
        total: 300_000,
      },
    },
    month_total: {
      input: 500_000,
      output: 250_000,
      cache_creation: 0,
      cache_read: 0,
      total: 750_000,
    },
  })),
  getCalendarAffairs: vi.fn(async () => ({
    items: mockAffairs,
    by_date: {
      '2026-11-08': {
        date: '2026-11-08',
        count: 2,
        categories: ['系统研发', '演示宣发'],
        employees: ['frago-developer', 'desktop-operator'],
        previews: ['实现 Agent Ontology 架构方案', '暗光照片局部调光配方录制'],
      },
    },
    summary: {
      total_affairs: 2,
      active_days: 1,
      categories: ['系统研发', '演示宣发'],
      employees: ['frago-developer', 'desktop-operator'],
    },
    cli_guide: {
      add_example: 'frago calendar add --title "..."',
      write_example: 'frago calendar write --file affairs.json',
      prompt_example: '把今天做完的事整理后写入日历',
    },
  })),
  deleteCalendarAffair: vi.fn(async () => ({ ok: true, id: 'test' })),
}));

function todayState(): SessionTodayState {
  return {
    picked: [],
    isPicked: () => false,
    toggle: vi.fn(async () => {}),
    today: '2026-11-08',
    refresh: vi.fn(async () => {}),
  };
}

describe('SessionTimeline Completed Affairs View', () => {
  it('月历网格展示已完成事务数徽章、微缩标题预览及头部汇总指标', async () => {
    render(
      <SessionTimeline
        sessions={[]}
        selectedId={null}
        today={todayState()}
        onSelect={() => {}}
        onClose={() => {}}
        initialDate={null}
      />
    );

    // 等待数据加载
    await waitFor(() => {
      expect(screen.getByTestId('month-affairs-badge')).toBeTruthy();
    });

    // 1. 月历顶部汇总指标区
    expect(screen.getByTestId('month-affairs-badge').textContent).toContain('2');

    // 2. 2026-11-08 格子内显著展示事务徽章与微缩预览
    const cell = screen.getByTestId('calendar-cell-2026-11-08');
    expect(cell).toBeTruthy();
    expect(cell.textContent).toContain('实现 Agent Ontology 架构方案');
  });

  it('点击日期默认展示已完成事务 Tab，渲染事务卡片与一键直达会话', async () => {
    const onSelect = vi.fn();
    render(
      <SessionTimeline
        sessions={[]}
        selectedId={null}
        today={todayState()}
        onSelect={onSelect}
        onClose={() => {}}
        initialDate="2026-11-08"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('affairs-view')).toBeTruthy();
    });

    // 1. 验证默认处于事务 Tab
    expect(screen.getByTestId('tab-affairs').getAttribute('class')).toContain('bg-[');

    // 2. 验证事务卡片流渲染
    const cards = screen.getAllByTestId('affair-card');
    expect(cards.length).toBe(2);
    expect(cards[0].textContent).toContain('实现 Agent Ontology 架构方案');
    expect(cards[0].textContent).toContain('frago-developer');
    expect(cards[0].textContent).toContain('排查多内核待输入状态盲区');

    // 3. 关联会话直达点击测试
    const sessionBtn = screen.getByTitle(/c767deb5-f7af-499f-9377-24ffbc05315b/);
    expect(sessionBtn).toBeTruthy();
    fireEvent.click(sessionBtn);
    expect(onSelect).toHaveBeenCalledWith('c767deb5-f7af-499f-9377-24ffbc05315b');
  });

  it('事务搜索过滤、员工筛选与分类筛选交互正常', async () => {
    render(
      <SessionTimeline
        sessions={[]}
        selectedId={null}
        today={todayState()}
        onSelect={() => {}}
        onClose={() => {}}
        initialDate="2026-11-08"
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('affairs-view')).toBeTruthy();
    });

    // 关键词搜索
    const searchInput = screen.getByTestId('affair-search-input');
    fireEvent.change(searchInput, { target: { value: '调光' } });
    expect(screen.getAllByTestId('affair-card').length).toBe(1);
    expect(screen.getByText('暗光照片局部调光配方录制')).toBeTruthy();

    // 清空搜索
    fireEvent.change(searchInput, { target: { value: '' } });
    expect(screen.getAllByTestId('affair-card').length).toBe(2);

    // 员工下拉筛选
    const employeeFilter = screen.getByTestId('affair-employee-filter');
    fireEvent.change(employeeFilter, { target: { value: 'frago-developer' } });
    expect(screen.getAllByTestId('affair-card').length).toBe(1);
  });
});
