/**
 * 右栏下半的暂存列表。
 *
 * 盯的是列表自己的承诺：只摆暂存（引用不进来）、「填入」「点原文」交出的是那一条、删除
 * 直接删、上移下移换算到整份数组里的正确位置、用过了的那条看得出来、空列表给一句怎么用、
 * 找不到原处时条目上有提示、想法能补写。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import StackPanel, { marksAboard, type StackPanelProps } from '../StackPanel';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function mark(id: string, fields: Partial<WorkbenchMark> = {}): WorkbenchMark {
  return {
    id,
    kind: 'stack',
    record_id: 'rec-1',
    text: `原文 ${id}`,
    occurrence: 0,
    note: '',
    used: false,
    created_at: 1,
    used_at: null,
    ...fields,
  };
}

function mount(props: Partial<StackPanelProps> = {}) {
  const handlers = {
    onFill: vi.fn(),
    onLocate: vi.fn(),
    onDelete: vi.fn(),
    onMove: vi.fn(),
    onNoteChange: vi.fn(),
  };
  render(<StackPanel marks={[]} {...handlers} {...props} />);
  return handlers;
}

describe('StackPanel', () => {
  it('只摆暂存，引用不进列表', () => {
    mount({ marks: [mark('a'), mark('q', { kind: 'quote' }), mark('b')] });
    const items = screen.getAllByTestId('stack-item');
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain('原文 a');
    expect(items[1].textContent).toContain('原文 b');
  });

  it('空列表给一句怎么用', () => {
    mount({ marks: [mark('q', { kind: 'quote' })] });
    expect(screen.getByTestId('stack-empty').textContent).toContain('暂存');
    expect(screen.queryByTestId('stack-item')).toBeNull();
  });

  it('「填入」与点原文各自交出那一条', () => {
    const b = mark('b', { note: '回头问' });
    const h = mount({ marks: [mark('a'), b] });
    const second = screen.getAllByTestId('stack-item')[1];
    fireEvent.click(within(second).getByTestId('stack-item-fill'));
    expect(h.onFill).toHaveBeenCalledWith(b);
    fireEvent.click(within(second).getByTestId('stack-item-text'));
    expect(h.onLocate).toHaveBeenCalledWith(b);
  });

  it('删除直接删，不再确认', () => {
    const h = mount({ marks: [mark('a')] });
    fireEvent.click(screen.getByTestId('stack-item-more'));
    fireEvent.click(screen.getByTestId('stack-item-delete'));
    expect(h.onDelete).toHaveBeenCalledWith('a');
  });

  it('上移下移换算到整份数组里的位置：夹在中间的引用不算数', () => {
    // 整份：a, q(引用), b, c。暂存列表：a, b, c。
    const h = mount({ marks: [mark('a'), mark('q', { kind: 'quote' }), mark('b'), mark('c')] });
    const [first, second] = screen.getAllByTestId('stack-item');

    fireEvent.click(within(second).getByTestId('stack-item-more'));
    fireEvent.click(within(second).getByTestId('stack-item-up'));
    // b 挪到 a 原来的位置
    expect(h.onMove).toHaveBeenLastCalledWith('b', 0);

    fireEvent.click(within(first).getByTestId('stack-item-more'));
    fireEvent.click(within(first).getByTestId('stack-item-down'));
    // a 挪到 b 原来的位置（整份里第 2 位）
    expect(h.onMove).toHaveBeenLastCalledWith('a', 2);
  });

  it('第一条不能再上移，最后一条不能再下移', () => {
    mount({ marks: [mark('a'), mark('b')] });
    const [first, last] = screen.getAllByTestId('stack-item');
    fireEvent.click(within(first).getByTestId('stack-item-more'));
    expect((within(first).getByTestId('stack-item-up') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(last).getByTestId('stack-item-more'));
    expect((within(last).getByTestId('stack-item-down') as HTMLButtonElement).disabled).toBe(true);
  });

  it('拖到另一条上放下：挪到那一条的位置', () => {
    const h = mount({ marks: [mark('a'), mark('b'), mark('c')] });
    const items = screen.getAllByTestId('stack-item');
    const grip = items[2].querySelector('[draggable]') as HTMLElement;
    fireEvent.dragStart(grip, { dataTransfer: { setData: () => {} } });
    fireEvent.dragOver(items[0]);
    fireEvent.drop(items[0]);
    expect(h.onMove).toHaveBeenCalledWith('c', 0);
  });

  it('用过了：标「用过了」、整条降一档', () => {
    mount({ marks: [mark('a', { used: true, used_at: 5 }), mark('b')] });
    const [used, fresh] = screen.getAllByTestId('stack-item');
    expect(used.getAttribute('data-used')).toBe('true');
    expect(within(used).getByTestId('stack-item-used').textContent).toBe('用过了');
    expect(fresh.getAttribute('data-used')).toBeNull();
    expect(within(fresh).queryByTestId('stack-item-used')).toBeNull();
  });

  it('已填入待发出、没找到原处，各自在条目上写明', () => {
    mount({
      marks: [mark('a'), mark('b')],
      pendingIds: ['a'],
      locate: { b: 'notFound' },
    });
    const [a, b] = screen.getAllByTestId('stack-item');
    expect(a.getAttribute('data-pending')).toBe('true');
    expect(a.textContent).toContain('发出后标为用过');
    expect(within(b).getByTestId('stack-item-not-found').textContent).toBe('没找到原处');
  });

  it('补写想法：回车存，去掉首尾空白', () => {
    const h = mount({ marks: [mark('a')] });
    fireEvent.click(screen.getByTestId('stack-item-add-note'));
    const input = screen.getByTestId('stack-item-note-input');
    fireEvent.change(input, { target: { value: ' 先问清范围 ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(h.onNoteChange).toHaveBeenCalledWith('a', '先问清范围');
  });

  it('改想法时 Esc 放弃，不存', () => {
    const h = mount({ marks: [mark('a', { note: '旧的' })] });
    fireEvent.click(screen.getByTestId('stack-item-note'));
    const input = screen.getByTestId('stack-item-note-input');
    fireEvent.change(input, { target: { value: '新的' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(h.onNoteChange).not.toHaveBeenCalled();
    expect(screen.getByTestId('stack-item-note').textContent).toContain('旧的');
  });
});

describe('marksAboard 「用过了」的判定', () => {
  const marks = [mark('a', { text: '第一个决策点' }), mark('b', { text: '第二个决策点' })];

  it('发出去的话里还带着原文才算用上；填了几条就算几条', () => {
    const sent = '"""\n第一个决策点\n"""\n>>> 选甲\n"""\n第二个决策点\n"""\n>>> 选乙';
    expect(marksAboard(sent, ['a', 'b'], marks)).toEqual(['a', 'b']);
  });

  it('填进去又删掉、改填了别的：不算', () => {
    expect(marksAboard('算了，先说别的', ['a'], marks)).toEqual([]);
    expect(marksAboard('"""\n第二个决策点\n"""\n>>> ', ['a', 'b'], marks)).toEqual(['b']);
  });

  it('没点过填入的不算，哪怕原文恰好出现在话里', () => {
    expect(marksAboard('第一个决策点', [], marks)).toEqual([]);
  });

  it('人在框里调了换行照样认得', () => {
    expect(marksAboard('第一个\n决策点', ['a'], marks)).toEqual(['a']);
  });
});
