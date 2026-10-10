/**
 * 记录流顶上那排里的「文件」那一档。
 *
 * 它不是镜头，是兄弟按钮：按下去记录流原地让位、清单铺满同一块地方，再按一下回来。
 * 盯四件事：不给就不出这一档（Teams 页那份记录流没有它）、按下去报「开」、数字还不知道时
 * 不摆数字（不因此按灰）、点某一档镜头就把清单合上——人那一下是在说「我要看记录」。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import RecordStream from '../RecordStream';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

const RECORDS: WorkbenchRecord[] = [
  {
    session_id: SID,
    group_id: null,
    id: 'r1',
    seq: 0,
    ts: 1_753_800_000_000,
    kind: 'agent.say',
    agent_path: [],
    payload: { text: '好的' },
    raw_available: true,
  },
];

function renderStream(props: Partial<Parameters<typeof RecordStream>[0]> = {}) {
  const all = {
    sessionId: SID,
    records: RECORDS,
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    onLoadOlder: () => {},
    ...props,
  };
  return render(<RecordStream {...all} />);
}

describe('「文件」那一档在镜头排里', () => {
  it('不给就不出：Teams 页那份记录流不带它', () => {
    renderStream();

    expect(screen.getByTestId('lens-talk')).toBeTruthy();
    expect(screen.queryByTestId('lens-files')).toBeNull();
  });

  it('按一下报「开」，开着的时候按一下报「关」——开关归上层，这一层只报', () => {
    const onFilesOpenChange = vi.fn();
    const { rerender } = renderStream({
      filesView: <div data-testid="panel-body" />,
      onFilesOpenChange,
    });

    fireEvent.click(screen.getByTestId('lens-files'));
    expect(onFilesOpenChange).toHaveBeenLastCalledWith(true);
    expect(screen.getByTestId('lens-files').getAttribute('aria-pressed')).toBe('false');

    rerender(
      <RecordStream
        sessionId={SID}
        records={RECORDS}
        loading={false}
        loadingOlder={false}
        hasOlder={false}
        error={null}
        onLoadOlder={() => {}}
        filesView={<div data-testid="panel-body" />}
        filesOpen
        onFilesOpenChange={onFilesOpenChange}
      />
    );
    expect(screen.getByTestId('lens-files').getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByTestId('lens-files'));
    expect(onFilesOpenChange).toHaveBeenLastCalledWith(false);
  });

  it('还在数：写个省略号占住位置，别让它看着像「没有」', () => {
    renderStream({ filesView: <div />, filesCount: null, filesPending: true });

    const btn = screen.getByTestId('lens-files');
    expect(screen.getByTestId('lens-files-pending').textContent).toBe('…');
    // 不按灰：按灰的是「一条都没有」，而「还不知道」不是那个意思。
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it('数不出来而且出错了：不写个数，也不写省略号——那时该说的是故障', () => {
    renderStream({ filesView: <div />, filesCount: null, filesPending: false });

    expect(screen.getByTestId('lens-files').textContent).toBe('文件');
    expect(screen.queryByTestId('lens-files-pending')).toBeNull();
  });

  it('数字到手就写上', () => {
    renderStream({ filesView: <div />, filesCount: 8 });

    expect(screen.getByTestId('lens-files').textContent).toBe('文件8');
  });
});

describe('清单开着的时候', () => {
  it('铺在记录流上面，记录流不卸载（滚动位置与标注都还在）', () => {
    renderStream({ filesView: <div data-testid="panel-body" />, filesOpen: true });

    expect(screen.getByTestId('files-panel')).toBeTruthy();
    expect(screen.getByTestId('panel-body')).toBeTruthy();
    // 记录流那一块还在 DOM 里：换掉（卸载）它，滚动位置、标注高亮、翻过的页全得重建。
    expect(screen.queryByTestId('record-stream-scroll')).toBeTruthy();
  });

  it('没开着就一个都不铺', () => {
    renderStream({ filesView: <div data-testid="panel-body" />, filesOpen: false });

    expect(screen.queryByTestId('files-panel')).toBeNull();
  });

  it('点某一档镜头就把清单合上：他这一下是在说「我要看记录」', () => {
    const onFilesOpenChange = vi.fn();
    renderStream({
      filesView: <div />,
      filesOpen: true,
      onFilesOpenChange,
    });

    fireEvent.click(screen.getByTestId('lens-all'));
    expect(onFilesOpenChange).toHaveBeenLastCalledWith(false);
  });
});
