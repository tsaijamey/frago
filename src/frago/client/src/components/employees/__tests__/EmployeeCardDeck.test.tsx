/**
 * EmployeeCardDeck 单测：覆盖纯函数 computeCardPose、选中态、键盘/滚轮节流、
 * 输入框/弹窗不劫持、快速检索弹层与边界模式。
 */

import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import EmployeeCardDeck, { computeCardPose, resolveDeckBreakpoint } from '../EmployeeCardDeck';
import i18n from '@/i18n';
import type { EmployeePost } from '@/hooks/useEmployees';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function makeEmp(id: string, title: string, activeCount = 0): EmployeePost {
  return {
    member_post_id: id,
    title,
    agent_kernel: 'claude',
    description: `${title}的职责说明`,
    work_scope: '',
    cwd: '/Users/frago/Repos/frago',
    knowledge_domains: [],
    recipes: [],
    data_slots: [],
    schedule_ids: [],
    active_session_ids: activeCount > 0 ? ['s1'] : [],
    session_counts: { active: activeCount, total: activeCount },
    allowed_commands: [],
    created_at: '',
    updated_at: '',
    data_summary: { slot_count: 0, entry_count: 0, slots: [] },
  };
}

const FIVE_EMPS: EmployeePost[] = [
  makeEmp('emp-0', '零号岗位', 1),
  makeEmp('emp-1', '一号岗位', 0),
  makeEmp('emp-2', '二号岗位', 2),
  makeEmp('emp-3', '三号岗位', 0),
  makeEmp('emp-4', '四号岗位', 0),
];

beforeEach(() => {
  Object.defineProperty(window, 'innerWidth', { writable: true, configurable: true, value: 1380 });
});

describe('computeCardPose & resolveDeckBreakpoint', () => {
  it('断点按 640 / 1024 划分 phone / tablet / desktop', () => {
    expect(resolveDeckBreakpoint(390)).toBe('phone');
    expect(resolveDeckBreakpoint(640)).toBe('phone');
    expect(resolveDeckBreakpoint(641)).toBe('tablet');
    expect(resolveDeckBreakpoint(1024)).toBe('tablet');
    expect(resolveDeckBreakpoint(1025)).toBe('desktop');
  });

  it('桌面端严格对齐 v3 几何参数，且 ±2 标为 isWing、|offset|>2 标为 isFar', () => {
    const center = computeCardPose(0, 'desktop', false, 'dark');
    expect(center).toMatchObject({
      tx: 0,
      ty: -2,
      tz: 48,
      ry: 0,
      rz: 0,
      sc: 1.02,
      zIndex: 60,
      opacity: 1,
      dofDim: 0,
      isFar: false,
      isWing: false,
      direction: 'center',
    });

    const right1 = computeCardPose(1, 'desktop', false, 'dark');
    expect(right1).toMatchObject({
      tx: 232,
      ty: 3,
      tz: -18,
      ry: -10,
      rz: 0.8,
      sc: 0.9,
      opacity: 1,
      dofDim: 0.12,
      zIndex: 50,
      isFar: false,
      isWing: false,
      direction: 'right',
    });

    const left2 = computeCardPose(-2, 'desktop', false, 'dark');
    expect(left2).toMatchObject({
      tx: -368,
      ty: 12,
      tz: -88,
      ry: 16,
      rz: -1.6,
      sc: 0.8,
      opacity: 1,
      dofDim: 0.24,
      zIndex: 40,
      isFar: false,
      isWing: true,
      direction: 'left',
    });

    const far3 = computeCardPose(3, 'desktop', false, 'light');
    expect(far3.isFar).toBe(true);
    expect(far3.opacity).toBe(0);
    expect(far3.dofDim).toBe(0.05);
  });

  it('平板端 maxVisible=1 且 txTable=[0,208,320]；手机端关闭 3D 与遮罩', () => {
    const tab1 = computeCardPose(1, 'tablet', false, 'light');
    expect(tab1.tx).toBe(208);
    expect(tab1.isFar).toBe(false);
    expect(tab1.dofDim).toBe(0.02);

    const tab2 = computeCardPose(2, 'tablet', false, 'light');
    expect(tab2.tx).toBe(320);
    expect(tab2.isFar).toBe(true);
    expect(tab2.opacity).toBe(0);

    const phone = computeCardPose(2, 'phone', false, 'dark');
    expect(phone).toMatchObject({
      tx: 0,
      ty: 0,
      tz: 0,
      ry: 0,
      rz: 0,
      sc: 1,
      dofDim: 0,
      isFar: false,
      isWing: false,
    });
  });

  it('reducedMotion 模式下取消 3D 旋转与景深倾角', () => {
    const pose = computeCardPose(1, 'desktop', true, 'dark');
    expect(pose.tx).toBe(232);
    expect(pose.tz).toBe(0);
    expect(pose.ry).toBe(0);
    expect(pose.rz).toBe(0);
  });
});

describe('EmployeeCardDeck 交互', () => {
  it('绑定选中态 aria-selected/data-active 与外翼 .is-wing/.is-far', () => {
    const onSelect = vi.fn();
    render(
      <EmployeeCardDeck
        employees={FIVE_EMPS}
        activeId="emp-2"
        onSelect={onSelect}
      />
    );

    const center = screen.getByTestId('employee-card-emp-2');
    expect(center.getAttribute('aria-selected')).toBe('true');
    expect(center.getAttribute('data-active')).toBe('true');
    expect(center.getAttribute('data-emp-color')).toBeTruthy();

    const leftWingSlot = screen.getByTestId('employee-card-emp-0').parentElement!;
    const rightWingSlot = screen.getByTestId('employee-card-emp-4').parentElement!;
    expect(leftWingSlot.className).toContain('is-left');
    expect(leftWingSlot.className).toContain('is-wing');
    expect(rightWingSlot.className).toContain('is-right');
    expect(rightWingSlot.className).toContain('is-wing');

    expect(screen.getByTestId('deck-counter').textContent).toBe('03 / 05');

    fireEvent.click(screen.getByTestId('employee-card-emp-1'));
    expect(onSelect).toHaveBeenCalledWith('emp-1');
  });

  it('键盘 ArrowLeft/ArrowRight/Home/End 切卡，且边界触发提示；循环模式首尾相接', () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <EmployeeCardDeck
        employees={FIVE_EMPS}
        activeId="emp-0"
        onSelect={onSelect}
      />
    );

    // 首张按 ArrowLeft 显示边界提示而不越界
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByTestId('deck-boundary-hint').textContent).toBe('已到达牌组首张');

    // ArrowRight 切到下一张并清空边界提示
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenCalledWith('emp-1');
    expect(screen.getByTestId('deck-boundary-hint').textContent).toBe('');

    // End 跳末张，Home 跳首张
    rerender(<EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-1" onSelect={onSelect} />);
    fireEvent.keyDown(window, { key: 'End' });
    expect(onSelect).toHaveBeenLastCalledWith('emp-4');

    rerender(<EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-4" onSelect={onSelect} />);
    fireEvent.keyDown(window, { key: 'Home' });
    expect(onSelect).toHaveBeenLastCalledWith('emp-0');

    // 开启循环模式后，末张按 ArrowRight 回到首张
    fireEvent.click(screen.getByTestId('deck-loop-toggle'));
    rerender(<EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-4" onSelect={onSelect} />);
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(onSelect).toHaveBeenLastCalledWith('emp-0');
  });

  it('输入框聚焦或模态窗打开时不劫持键盘左右键', () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <div>
        <input data-testid="external-input" />
        <EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-2" onSelect={onSelect} />
      </div>
    );

    const input = screen.getByTestId('external-input');
    input.focus();
    fireEvent.keyDown(input, { key: 'ArrowRight' });
    fireEvent.keyDown(input, { key: 'ArrowLeft' });
    expect(onSelect).not.toHaveBeenCalled();

    input.blur();
    rerender(
      <div>
        <input data-testid="external-input" />
        <EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-2" onSelect={onSelect} modalOpen />
      </div>
    );
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('快速检索弹层支持 / 唤醒、输入过滤并回车选中目标员工', () => {
    const onSelect = vi.fn();
    render(<EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-0" onSelect={onSelect} />);

    fireEvent.keyDown(window, { key: '/' });
    const search = screen.getByTestId('deck-jump-search');
    fireEvent.change(search, { target: { value: '三号' } });
    expect(screen.getByTestId('deck-jump-item-emp-3')).toBeTruthy();
    expect(screen.queryByTestId('deck-jump-item-emp-1')).toBeNull();

    fireEvent.keyDown(search, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith('emp-3');
    expect(screen.queryByTestId('deck-jump-popover')).toBeNull();
  });

  it('滚轮切卡带阈值累加与 150ms 冷却锁，连续滚轮不连跳', () => {
    const onSelect = vi.fn();
    let now = 1000;
    const perfSpy = vi.spyOn(performance, 'now').mockImplementation(() => now);

    render(<EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-1" onSelect={onSelect} />);
    const stage = screen.getByTestId('employee-deck-stage');

    // 小幅滚轮累计不到 28 不切卡
    fireEvent.wheel(stage, { deltaY: 15 });
    expect(onSelect).not.toHaveBeenCalled();

    // 再滚 20 达到阈值 35 -> 切卡一次
    fireEvent.wheel(stage, { deltaY: 20 });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith('emp-2');

    // 冷却锁 150ms 内再次大滚轮不连跳
    now = 1080;
    fireEvent.wheel(stage, { deltaY: 120 });
    expect(onSelect).toHaveBeenCalledTimes(1);

    // 超过冷却锁后再滚轮可触发下一次
    now = 1200;
    fireEvent.wheel(stage, { deltaY: 40 });
    expect(onSelect).toHaveBeenCalledTimes(2);

    perfSpy.mockRestore();
  });

  it('模态窗或快速检索弹层开启时，滚轮不误触发切卡', () => {
    const onSelect = vi.fn();
    const { rerender } = render(
      <EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-2" onSelect={onSelect} modalOpen />
    );
    const stage = screen.getByTestId('employee-deck-stage');
    fireEvent.wheel(stage, { deltaY: 80 });
    expect(onSelect).not.toHaveBeenCalled();

    rerender(<EmployeeCardDeck employees={FIVE_EMPS} activeId="emp-2" onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('deck-jump-trigger'));
    expect(screen.getByTestId('deck-jump-popover')).toBeTruthy();
    fireEvent.wheel(stage, { deltaY: 80 });
    expect(onSelect).not.toHaveBeenCalled();
  });
});
