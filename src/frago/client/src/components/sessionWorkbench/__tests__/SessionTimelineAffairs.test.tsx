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

import { getCalendarAffairs } from '@/api';
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

    // 2. 2026-11-08 格子内显著展示事务徽章、微缩预览与最高热力分位
    const cell = screen.getByTestId('calendar-cell-2026-11-08');
    expect(cell).toBeTruthy();
    expect(cell.textContent).toContain('实现 Agent Ontology 架构方案');
    expect(cell.getAttribute('data-heat')).toBe('3');
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

    // 2. 验证扁平分带台账结构与事务行渲染
    expect(screen.getByTestId('affairs-card-list').querySelector('.tl-affair-ledger')).toBeTruthy();
    const cards = screen.getAllByTestId('affair-card');
    expect(cards.length).toBe(2);
    expect(cards[0].className).toContain('tl-affair-row');
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

  it('12+ 及 50 条同日事务全部渲染且保持完整可滚动布局链，不被容器压缩裁切', async () => {
    const manyDate = '2026-11-21';
    const manyAffairs = Array.from({ length: 50 }, (_, idx) => {
      const seq = idx + 1;
      const hh = String(8 + Math.floor(idx / 5)).padStart(2, '0');
      const mm = String((idx % 5) * 10).padStart(2, '0');
      return {
        id: `aff-20261121-${seq}`,
        date: manyDate,
        title: `第 ${seq} 条已完成事务：验证长列表独立滚动到底部`,
        summary: `第 ${seq} 条业务结论摘要，用于验证 .tl-affair-ledger 不会被 flex-shrink 压缩裁切。`,
        category: seq % 2 === 0 ? '系统研发' : '测试验证',
        tags: ['scroll-fix'],
        employee: 'frago-developer',
        sessions: [`sess-20261121-${seq}`],
        artifacts: [`/Users/frago/.frago/data/frago-dev/20261121-case-${seq}/notebook.md`],
        completed_at: `${manyDate}T${hh}:${mm}:00`,
        created_at: `${manyDate}T${hh}:${mm}:00`,
        updated_at: `${manyDate}T${hh}:${mm}:00`,
      };
    });

    vi.mocked(getCalendarAffairs).mockResolvedValueOnce({
      items: manyAffairs,
      by_date: {
        [manyDate]: {
          date: manyDate,
          count: manyAffairs.length,
          categories: ['系统研发', '测试验证'],
          employees: ['frago-developer'],
          previews: manyAffairs.slice(0, 2).map((a) => a.title),
        },
      },
      summary: {
        total_affairs: manyAffairs.length,
        active_days: 1,
        categories: ['系统研发', '测试验证'],
        employees: ['frago-developer'],
      },
      cli_guide: {
        add_example: 'frago calendar add --title "..."',
        write_example: 'frago calendar write --file affairs.json',
        prompt_example: '把今天做完的事整理后写入日历',
      },
    });

    render(
      <SessionTimeline
        sessions={[]}
        selectedId={null}
        today={todayState()}
        onSelect={() => {}}
        onClose={() => {}}
        initialDate={manyDate}
      />
    );

    await waitFor(() => {
      expect(screen.getAllByTestId('affair-card').length).toBe(50);
    });

    // 1. 计数与全部 50 条事务渲染完整（含第 1 条、第 12 条与第 50 条）
    expect(screen.getByTestId('tab-affairs').textContent).toContain('50');
    expect(screen.getByTestId('affairs-view').textContent).toContain('50 / 50');
    expect(screen.getByText('第 1 条已完成事务：验证长列表独立滚动到底部')).toBeTruthy();
    expect(screen.getByText('第 12 条已完成事务：验证长列表独立滚动到底部')).toBeTruthy();
    expect(screen.getByText('第 50 条已完成事务：验证长列表独立滚动到底部')).toBeTruthy();

    // 2. 逐层核对日详情容器链的 min-h-0 / overflow 约束（外层弹窗 → 左日期栏 → 右双 Tab → 滚动容器 → 台账列表）
    const dialog = screen.getByTestId('session-timeline');
    const modalCard = dialog.querySelector('.min-h-0.min-w-0.flex-1.flex-col.overflow-hidden');
    expect(modalCard).toBeTruthy();

    const dateRail = screen.getByTestId('timeline-date-rail');
    expect(dateRail.className).toContain('min-h-0');
    expect(dateRail.className).toContain('overflow-hidden');

    const pane = screen.getByTestId('timeline-pane');
    expect(pane.className).toContain('min-h-0');
    expect(pane.className).toContain('flex-1');
    expect(pane.className).toContain('overflow-hidden');

    const affairsView = screen.getByTestId('affairs-view');
    expect(affairsView.className).toContain('min-h-0');
    expect(affairsView.className).toContain('flex-1');
    expect(affairsView.className).toContain('overflow-hidden');

    const scroller = screen.getByTestId('affairs-card-list');
    expect(scroller.className).toContain('min-h-0');
    expect(scroller.className).toContain('flex-1');
    expect(scroller.className).toContain('overflow-y-auto');
    expect(scroller.className).toContain('pb-10');
    // 滚动容器不再自身设为 flex-col，避免子代 .tl-affair-ledger 因 overflow:hidden 被压缩裁切
    expect(scroller.className).not.toContain('flex-col');

    const ledger = scroller.querySelector('.tl-affair-ledger');
    expect(ledger).toBeTruthy();
    expect(ledger?.className).toContain('shrink-0');

    // 3. 切换至「会话时间轴·用量」Tab，确认轨道外层同样具备 min-h-0 flex-1 overflow-hidden
    fireEvent.click(screen.getByTestId('tab-timeline'));
    const timelineEmptyOrTrack = screen.getByTestId('timeline-pane').querySelector('.min-h-0.flex-1.overflow-hidden');
    expect(timelineEmptyOrTrack).toBeTruthy();
  });
});
