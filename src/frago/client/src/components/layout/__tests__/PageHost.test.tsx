/**
 * 页面宿主的用例：切走的那一页不卸载，只是藏起来。
 *
 * 这里把页面本身换成两个记账用的假货——宿主管的是"留不留"，不是页面里画了什么，
 * 真页面各自的规矩由它们自己的用例守。假货各自带一份局部状态，正是从前会丢掉的
 * 那类东西（人在输入框里打了一半的话）。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import PageHost from '../PageHost';
import { usePageStore, type PageType } from '@/stores/pageStore';

vi.mock('@/components/sessionWorkbench/SessionWorkbenchPage', async () => {
  const { useState } = await import('react');
  function FakeWorkbench() {
    const [text, setText] = useState('');
    return (
      <textarea data-testid="fake-composer" value={text} onChange={(e) => setText(e.target.value)} />
    );
  }
  return { default: FakeWorkbench };
});

vi.mock('@/components/settings/SettingsPage', async () => {
  const { useState } = await import('react');
  function FakeSettings() {
    const [n, setN] = useState(0);
    return (
      <button type="button" data-testid="fake-settings" onClick={() => setN((v) => v + 1)}>
        {n}
      </button>
    );
  }
  return { default: FakeSettings };
});

/** 切到某一页。切页本身走的是页外的状态（地址栏那条路），得让 React 把这一轮走完。 */
function goto(page: PageType) {
  act(() => {
    usePageStore.getState().switchPage(page);
  });
}

/** 某个页面此刻在不在这份文档里，以及是不是被藏着。 */
function slotOf(el: HTMLElement) {
  const slot = el.closest('.page-slot');
  if (!slot) throw new Error('这个元素不在任何页面槽位里');
  return slot as HTMLElement;
}

beforeEach(() => {
  usePageStore.setState({
    currentPage: 'session_workbench',
    currentTaskId: null,
    currentRecipeName: null,
    currentProjectId: null,
    currentTodoId: null,
    currentScheduleId: null,
    currentRecipeAppId: null,
  });
});

describe('PageHost 切页保留', () => {
  it('在输入框里打了一半的话，切走再切回来还在', () => {
    render(<PageHost />);

    fireEvent.change(screen.getByTestId('fake-composer'), { target: { value: '这句话还没发出去' } });
    expect((screen.getByTestId('fake-composer') as HTMLTextAreaElement).value).toBe(
      '这句话还没发出去'
    );

    goto('settings');
    goto('session_workbench');

    expect((screen.getByTestId('fake-composer') as HTMLTextAreaElement).value).toBe(
      '这句话还没发出去'
    );
  });

  it('切走的那一页还留在文档里，只是藏起来——不是被卸掉重挂', () => {
    render(<PageHost />);
    const composer = screen.getByTestId('fake-composer');
    const slot = slotOf(composer);

    goto('settings');
    // 还在文档里，同一个节点，只是藏起来了。
    expect(document.body.contains(composer)).toBe(true);
    expect(slot.hasAttribute('hidden')).toBe(true);
    expect(slotOf(screen.getByTestId('fake-settings')).hasAttribute('hidden')).toBe(false);

    goto('session_workbench');
    expect(slot.hasAttribute('hidden')).toBe(false);
  });

  it('每一页各留各的，回来时仍是自己那一份', () => {
    render(<PageHost />);
    goto('settings');

    fireEvent.click(screen.getByTestId('fake-settings'));
    fireEvent.click(screen.getByTestId('fake-settings'));
    expect(screen.getByTestId('fake-settings').textContent).toBe('2');

    goto('session_workbench');
    goto('settings');
    expect(screen.getByTestId('fake-settings').textContent).toBe('2');
  });

  it('进过的页面都留在文档里，当前那一页不藏', () => {
    render(<PageHost />);
    goto('settings');

    const slots = document.querySelectorAll('.page-slot');
    expect(slots).toHaveLength(2);
    expect(document.querySelectorAll('.page-slot[hidden]')).toHaveLength(1);
  });

  it('配方页面开着时底下一页都不露——它由别处渲染，不是"认不出来的页面"', () => {
    render(<PageHost />);
    goto('settings');
    goto('recipe_app');

    const slots = document.querySelectorAll('.page-slot');
    expect(slots.length).toBeGreaterThan(0);
    expect(document.querySelectorAll('.page-slot:not([hidden])')).toHaveLength(0);
  });
});
