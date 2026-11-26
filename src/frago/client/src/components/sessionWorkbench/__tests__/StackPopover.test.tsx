import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import StackPopover, { type StackPopoverState } from '../StackPopover';
import type { WorkbenchMark } from '@/types/api';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function mk(id: string, over: Partial<WorkbenchMark> = {}): WorkbenchMark {
  return {
    id,
    kind: 'stack',
    record_id: 'r1',
    text: `原话-${id}`,
    occurrence: 0,
    note: '',
    used: false,
    created_at: 1_753_800_000_000,
    used_at: null,
    ...over,
  };
}

const ANCHOR = { top: 200, left: 600, right: 740, bottom: 222 };

describe('StackPopover 3 态浮层交互', () => {
  it('单条态支持内联编辑想法（Enter/blur）、复制原文、定位、删除与 Esc 焦点归还', async () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const onClose = vi.fn();
    const onNoteChange = vi.fn();
    const onLocate = vi.fn();
    const onDelete = vi.fn();
    const onFill = vi.fn();
    const m1 = mk('m1', { text: '关键结论句', note: '旧想法' });

    const state: StackPopoverState = {
      mode: 'item',
      markId: 'm1',
      anchorRect: ANCHOR,
      triggerEl: trigger,
      placement: 'left',
    };

    try {
      render(
        <StackPopover
          state={state}
          marks={[m1]}
          inDraftMarkIds={new Set()}
          onClose={onClose}
          onFill={onFill}
          onRemoveFromDraft={vi.fn()}
          onLocate={onLocate}
          onDelete={onDelete}
          onNoteChange={onNoteChange}
        />
      );

      expect(screen.getByTestId('stack-popover').getAttribute('data-mode')).toBe('item');
      expect(screen.getByTestId('stack-popover-quote').textContent).toBe('关键结论句');

      // 复制原文
      fireEvent.click(screen.getByTestId('stack-popover-copy'));
      expect(writeText).toHaveBeenCalledWith('关键结论句');

      // 默认展示静态按钮，点击进入 textarea 编辑态并 Enter 保存
      const noteDisplay = screen.getByTestId('stack-popover-note-display');
      expect(noteDisplay.textContent).toBe('旧想法');
      expect(screen.queryByTestId('stack-popover-note-input')).toBeNull();
      fireEvent.click(noteDisplay);

      const noteInput = screen.getByTestId('stack-popover-note-input') as HTMLTextAreaElement;
      expect(noteInput.tagName).toBe('TEXTAREA');
      fireEvent.change(noteInput, { target: { value: '改为方案B' } });
      fireEvent.keyDown(noteInput, { key: 'Enter' });
      expect(onNoteChange).toHaveBeenCalledWith('m1', '改为方案B');
      expect(screen.queryByTestId('stack-popover-note-input')).toBeNull();

      // 定位 & 填入
      fireEvent.click(screen.getByTestId('stack-popover-locate'));
      expect(onLocate).toHaveBeenCalledWith(m1);
      fireEvent.click(screen.getByTestId('stack-popover-fill'));
      expect(onFill).toHaveBeenCalledWith(m1);

      // Esc 关闭需携带 restoreFocus: true
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledWith({ restoreFocus: true });

      // 点击空白处关闭需携带 restoreFocus: false
      fireEvent.pointerDown(document.body);
      expect(onClose).toHaveBeenCalledWith({ restoreFocus: false });

      // 删除回调
      fireEvent.click(screen.getByTestId('stack-popover-delete'));
      expect(onDelete).toHaveBeenCalledWith(m1);
    } finally {
      trigger.remove();
    }
  });

  it('集群态当待填入条数为 2-5 时提供「全部填入 (N)」并逐条填入', () => {
    const marks = [mk('m1'), mk('m2'), mk('m3')];
    const onFill = vi.fn();
    const onClose = vi.fn();
    render(
      <StackPopover
        state={{
          mode: 'cluster',
          clusterId: 'm1+m2+m3',
          markIds: ['m1', 'm2', 'm3'],
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
        }}
        marks={marks}
        inDraftMarkIds={new Set(['m2'])}
        onClose={onClose}
        onFill={onFill}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );

    const fillAll = screen.getByTestId('stack-popover-fill-all');
    expect(fillAll.textContent).toContain('2');
    fireEvent.click(fillAll);
    expect(onFill.mock.calls.map((c) => (c[0] as WorkbenchMark).id)).toEqual(['m1', 'm3']);
    expect(onClose).toHaveBeenCalledWith({ restoreFocus: false });
  });

  it('汇总态置顶未加载条目并标识「尚未加载」，且支持展开/折叠「已处理 (N)」', () => {
    const marks = [
      mk('m-loaded'),
      mk('m-unloaded'),
      mk('m-used', { used: true, used_at: 99 }),
    ];
    render(
      <StackPopover
        state={{
          mode: 'summary',
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
        }}
        marks={marks}
        inDraftMarkIds={new Set()}
        unloadedMarkIds={new Set(['m-unloaded'])}
        onClose={vi.fn()}
        onFill={vi.fn()}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );

    const rows = screen.getAllByTestId('stack-list-row');
    expect(rows.map((r) => r.getAttribute('data-mark-id'))).toEqual(['m-unloaded', 'm-loaded']);
    expect(screen.getByTestId('stack-unloaded-badge')).toBeTruthy();

    // 默认折叠已处理，点击展开并支持对已处理条目「再次填入」
    expect(screen.getAllByTestId('stack-list-row')).toHaveLength(2);
    fireEvent.click(screen.getByTestId('stack-used-toggle'));
    expect(screen.getAllByTestId('stack-list-row')).toHaveLength(3);
  });

  it('行内 textarea 支持 Shift+Enter 换行，且编辑态按 Esc 仅放弃草稿退出编辑而不关闭浮层', () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    const onClose = vi.fn();
    const onNoteChange = vi.fn();
    const m1 = mk('m1', { text: '原句', note: '初始想法' });

    try {
      render(
        <StackPopover
          state={{
            mode: 'item',
            markId: 'm1',
            anchorRect: ANCHOR,
            triggerEl: trigger,
            placement: 'left',
          }}
          marks={[m1]}
          inDraftMarkIds={new Set()}
          onClose={onClose}
          onFill={vi.fn()}
          onRemoveFromDraft={vi.fn()}
          onLocate={vi.fn()}
          onDelete={vi.fn()}
          onNoteChange={onNoteChange}
        />
      );

      fireEvent.click(screen.getByTestId('stack-popover-note-display'));
      const ta = screen.getByTestId('stack-popover-note-input') as HTMLTextAreaElement;
      expect(ta.tagName).toBe('TEXTAREA');

      // Shift+Enter 不触发提交与关闭，保持编辑态并保留多行文本
      fireEvent.keyDown(ta, { key: 'Enter', shiftKey: true });
      fireEvent.change(ta, { target: { value: '第一行\n第二行' } });
      expect(onNoteChange).not.toHaveBeenCalled();
      expect(screen.getByTestId('stack-popover-note-input')).toBeTruthy();

      // 编辑态按 Esc：仅撤销草稿并退出编辑态，不关闭浮层
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onClose).not.toHaveBeenCalled();
      expect(onNoteChange).not.toHaveBeenCalled();
      expect(screen.queryByTestId('stack-popover-note-input')).toBeNull();
      expect(screen.getByTestId('stack-popover-note-display').textContent).toBe('初始想法');

      // 非编辑态再按 Esc：关闭浮层并归还焦点
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledWith({ restoreFocus: true });

      // 失焦保存
      fireEvent.click(screen.getByTestId('stack-popover-note-display'));
      const ta2 = screen.getByTestId('stack-popover-note-input') as HTMLTextAreaElement;
      fireEvent.change(ta2, { target: { value: '失焦保存文本\n第二行' } });
      fireEvent.blur(ta2);
      expect(onNoteChange).toHaveBeenCalledWith('m1', '失焦保存文本\n第二行');
    } finally {
      trigger.remove();
    }
  });

  it('已处理（used=true）条目在汇总折叠区与单条详情态均支持「再次填入」', () => {
    const usedMark = mk('m-used', { used: true, used_at: 99, note: '旧备注' });
    const onFill = vi.fn();

    const { rerender } = render(
      <StackPopover
        state={{
          mode: 'summary',
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
        }}
        marks={[usedMark]}
        inDraftMarkIds={new Set()}
        onClose={vi.fn()}
        onFill={onFill}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId('stack-used-toggle'));
    const rowFillBtn = screen.getByTestId('stack-row-fill');
    expect(rowFillBtn.textContent).toBe('再次填入');
    fireEvent.click(rowFillBtn);
    expect(onFill).toHaveBeenCalledWith(usedMark);

    // 单条详情态底部同样展示「再次填入」
    rerender(
      <StackPopover
        state={{
          mode: 'item',
          markId: 'm-used',
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
        }}
        marks={[usedMark]}
        inDraftMarkIds={new Set()}
        onClose={vi.fn()}
        onFill={onFill}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );

    const itemFillBtn = screen.getByTestId('stack-popover-fill');
    expect(itemFillBtn.textContent).toBe('再次填入');
    fireEvent.click(itemFillBtn);
    expect(onFill).toHaveBeenCalledTimes(2);
    expect(onFill).toHaveBeenLastCalledWith(usedMark);
  });

  it('从集群或汇总钻取单条详情时携带 backTo 上下文并渲染返回按钮', () => {
    const m1 = mk('m1');
    const m2 = mk('m2');
    const onSwitchToItem = vi.fn();
    const onBack = vi.fn();

    const { rerender } = render(
      <StackPopover
        state={{
          mode: 'cluster',
          clusterId: 'm1+m2',
          markIds: ['m1', 'm2'],
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
        }}
        marks={[m1, m2]}
        inDraftMarkIds={new Set()}
        onClose={vi.fn()}
        onSwitchToItem={onSwitchToItem}
        onBack={onBack}
        onFill={vi.fn()}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );

    const firstRowMain = screen.getAllByTestId('stack-list-row')[0].querySelector('.sp-row-main')!;
    fireEvent.click(firstRowMain);
    expect(onSwitchToItem).toHaveBeenCalledWith('m1', {
      mode: 'cluster',
      clusterId: 'm1+m2',
      markIds: ['m1', 'm2'],
    });

    // 无 backTo 时不渲染返回按钮
    rerender(
      <StackPopover
        state={{
          mode: 'item',
          markId: 'm1',
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
        }}
        marks={[m1, m2]}
        inDraftMarkIds={new Set()}
        onClose={vi.fn()}
        onSwitchToItem={onSwitchToItem}
        onBack={onBack}
        onFill={vi.fn()}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );
    expect(screen.queryByTestId('stack-popover-back')).toBeNull();

    // 带 backTo 时在头部渲染返回按钮并触发 onBack
    rerender(
      <StackPopover
        state={{
          mode: 'item',
          markId: 'm1',
          anchorRect: ANCHOR,
          triggerEl: null,
          placement: 'left',
          backTo: { mode: 'cluster', clusterId: 'm1+m2', markIds: ['m1', 'm2'] },
        }}
        marks={[m1, m2]}
        inDraftMarkIds={new Set()}
        onClose={vi.fn()}
        onSwitchToItem={onSwitchToItem}
        onBack={onBack}
        onFill={vi.fn()}
        onRemoveFromDraft={vi.fn()}
        onLocate={vi.fn()}
        onDelete={vi.fn()}
        onNoteChange={vi.fn()}
      />
    );
    const backBtn = screen.getByTestId('stack-popover-back');
    fireEvent.click(backBtn);
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
