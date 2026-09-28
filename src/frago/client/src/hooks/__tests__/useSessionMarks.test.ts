/**
 * 会话标注这一路的用例。
 *
 * 盯五件事：标注从服务端读（跟着会话走）、增删改排序标用过都是点下去就改并整份送出、
 * 存不下时界面退回最后一份落盘的并只提示一次、读回来之前的改动不会把盘上原有的抹掉、
 * 换会话先清空再读。
 */

import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getSessionMarks = vi.fn();
const putSessionMarks = vi.fn();
vi.mock('@/api', () => ({
  getSessionMarks: (sid: string) => getSessionMarks(sid),
  putSessionMarks: (sid: string, body: unknown) => putSessionMarks(sid, body),
}));

import { useSessionMarks, type WorkbenchMark } from '../useSessionMarks';
import { useUIStore } from '@/stores/uiStore';

const A = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const B = 'ses_058288655ffeYMxYC1AZKCcv56';

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

/** 最后一次送出去的那一份里各条的编号。 */
function lastPutIds(): string[] {
  const calls = putSessionMarks.mock.calls;
  const body = calls[calls.length - 1][1] as { marks: WorkbenchMark[] };
  return body.marks.map((m) => m.id);
}

const toast = vi.fn();

beforeEach(() => {
  getSessionMarks.mockReset();
  putSessionMarks.mockReset();
  toast.mockReset();
  getSessionMarks.mockResolvedValue({ version: 1, marks: [] });
  putSessionMarks.mockImplementation(async (_sid: string, body: unknown) => body);
  useUIStore.setState({ showToast: toast });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function loadedHook(sid: string | null = A) {
  const hook = renderHook(({ id }) => useSessionMarks(id), { initialProps: { id: sid } });
  await waitFor(() => expect(hook.result.current.loaded).toBe(sid !== null));
  return hook;
}

describe('useSessionMarks', () => {
  it('从服务端读这场会话的标注', async () => {
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('a'), mark('b')] });
    const { result } = await loadedHook();
    expect(getSessionMarks).toHaveBeenCalledWith(A);
    expect(result.current.marks.map((m) => m.id)).toEqual(['a', 'b']);
  });

  it('新增一条：补齐字段、接在最后、整份送出', async () => {
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('a')] });
    const { result } = await loadedHook();
    let added: WorkbenchMark | null = null;
    act(() => {
      added = result.current.addMark({
        kind: 'stack',
        record_id: 'rec-9',
        text: '第三个决策点',
        occurrence: 1,
        note: '先放一放',
      });
    });
    expect(added).not.toBeNull();
    const made = added as unknown as WorkbenchMark;
    expect(made.id).toMatch(/^mk_/);
    expect(made).toMatchObject({ used: false, used_at: null, note: '先放一放', occurrence: 1 });
    expect(result.current.marks.map((m) => m.id)).toEqual(['a', made.id]);
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(1));
    expect(putSessionMarks.mock.calls[0][0]).toBe(A);
    expect(lastPutIds()).toEqual(['a', made.id]);
  });

  it('改想法、删、挪顺序各自整份送出', async () => {
    getSessionMarks.mockResolvedValueOnce({
      version: 1,
      marks: [mark('a'), mark('b'), mark('c')],
    });
    const { result } = await loadedHook();

    act(() => result.current.setNote('b', '回头问'));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(1));
    expect(result.current.marks[1].note).toBe('回头问');

    act(() => result.current.move('c', 0));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(2));
    expect(result.current.marks.map((m) => m.id)).toEqual(['c', 'a', 'b']);
    expect(lastPutIds()).toEqual(['c', 'a', 'b']);

    act(() => result.current.remove('a'));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(3));
    expect(lastPutIds()).toEqual(['c', 'b']);
  });

  it('没变的改动不送：同样的想法、挪到原位、删不存在的', async () => {
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('a', { note: 'x' })] });
    const { result } = await loadedHook();
    act(() => {
      result.current.setNote('a', 'x');
      result.current.move('a', 0);
      result.current.remove('nope');
    });
    await Promise.resolve();
    expect(putSessionMarks).not.toHaveBeenCalled();
  });

  it('标用过：只改没用过的，写上时刻', async () => {
    getSessionMarks.mockResolvedValueOnce({
      version: 1,
      marks: [mark('a'), mark('b', { used: true, used_at: 7 }), mark('c')],
    });
    const { result } = await loadedHook();
    act(() => result.current.markUsed(['a', 'b']));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(1));
    const [a, b, c] = result.current.marks;
    expect(a.used).toBe(true);
    expect(a.used_at).toBeGreaterThan(7);
    expect(b.used_at).toBe(7);
    expect(c.used).toBe(false);
  });

  it('标用过时人已经切去别的会话：直接改那一场的文件，不碰眼下这一场', async () => {
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('here')] });
    const { result } = await loadedHook(A);
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('x'), mark('y')] });
    act(() => result.current.markUsed(['y'], B));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(1));
    expect(putSessionMarks.mock.calls[0][0]).toBe(B);
    const body = putSessionMarks.mock.calls[0][1] as { marks: WorkbenchMark[] };
    expect(body.marks.map((m) => m.used)).toEqual([false, true]);
    expect(result.current.marks.map((m) => m.id)).toEqual(['here']);
  });

  it('存不下：退回最后一份落盘的，连着失败只提示一次', async () => {
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('a')] });
    const { result } = await loadedHook();
    putSessionMarks.mockRejectedValue(new Error('HTTP 500'));

    act(() => result.current.remove('a'));
    expect(result.current.marks).toEqual([]);
    await waitFor(() => expect(result.current.marks.map((m) => m.id)).toEqual(['a']));
    expect(toast).toHaveBeenCalledTimes(1);
    expect(toast.mock.calls[0][1]).toBe('error');

    act(() => result.current.setNote('a', '再试'));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.marks[0].note).toBe(''));
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it('读回来之前的暂存接在盘上原有的后面，不把它们抹掉', async () => {
    let release: (v: unknown) => void = () => {};
    getSessionMarks.mockReturnValueOnce(new Promise((r) => (release = r)));
    const { result } = renderHook(() => useSessionMarks(A));
    act(() => {
      result.current.addMark({ kind: 'quote', record_id: 'r', text: 't', occurrence: 0 });
    });
    expect(putSessionMarks).not.toHaveBeenCalled();
    await act(async () => release({ version: 1, marks: [mark('old')] }));
    await waitFor(() => expect(putSessionMarks).toHaveBeenCalledTimes(1));
    expect(lastPutIds()[0]).toBe('old');
    expect(lastPutIds()).toHaveLength(2);
  });

  it('读不到的那一场不写盘，按存不下处理', async () => {
    getSessionMarks.mockRejectedValueOnce(new Error('HTTP 404'));
    const { result } = await loadedHook();
    act(() => {
      result.current.addMark({ kind: 'stack', record_id: 'r', text: 't', occurrence: 0 });
    });
    await waitFor(() => expect(result.current.marks).toEqual([]));
    expect(putSessionMarks).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it('换会话先清空再读另一场', async () => {
    getSessionMarks.mockResolvedValueOnce({ version: 1, marks: [mark('a')] });
    const hook = await loadedHook();
    let release: (v: unknown) => void = () => {};
    getSessionMarks.mockReturnValueOnce(new Promise((r) => (release = r)));
    hook.rerender({ id: B });
    expect(hook.result.current.marks).toEqual([]);
    expect(hook.result.current.loaded).toBe(false);
    await act(async () => release({ version: 1, marks: [mark('b')] }));
    await waitFor(() => expect(hook.result.current.marks.map((m) => m.id)).toEqual(['b']));
    expect(getSessionMarks).toHaveBeenLastCalledWith(B);
  });

  it('没选会话时什么都不做', async () => {
    const { result } = renderHook(() => useSessionMarks(null));
    let added: WorkbenchMark | null = mark('x');
    act(() => {
      added = result.current.addMark({ kind: 'stack', record_id: 'r', text: 't', occurrence: 0 });
    });
    expect(added).toBeNull();
    expect(getSessionMarks).not.toHaveBeenCalled();
  });
});
