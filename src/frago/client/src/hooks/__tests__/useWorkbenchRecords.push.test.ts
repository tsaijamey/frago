/**
 * 中栏收实时推送这一步：**顺序不托付给推送那一侧**。
 *
 * 2026-09-12 那天页面上看到的是：滚到底，最新内容前面摆着一段几小时前的对话。出处在服务端
 * ——它每次文件变动都整份重翻，而「这条交出去过没有」只记了最近几十条，于是整场历史被当成
 * 新内容推过来；页面照单接在流的尾巴上。服务端那一侧已经修好，这里守的是第二道：推送再错
 * 一次，顺序也不许乱。
 *
 * 喂的是服务端 `create_message` 真实发出的那个形状：type / timestamp / data。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Handler = (msg: unknown) => void;
const handlers = new Map<string, Set<Handler>>();

vi.mock('@/api/websocket', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/api/websocket')>();
  return {
    ...real,
    getWebSocketClient: () => ({
      on: (type: string, handler: Handler) => {
        if (!handlers.has(type)) handlers.set(type, new Set());
        handlers.get(type)!.add(handler);
        return () => handlers.get(type)?.delete(handler);
      },
    }),
  };
});

import { PAGE_SIZE, useWorkbenchRecords, type WorkbenchRecord } from '../useWorkbenchRecords';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

function record(seq: number, id = `rec-${seq}`): WorkbenchRecord {
  return {
    id,
    session_id: SID,
    group_id: null,
    seq,
    ts: 1_753_800_000_000 + seq,
    kind: 'agent.say',
    agent_path: [],
    payload: { text: `第 ${seq} 条` },
    raw_available: true,
  };
}

/** 顶替 fetch：一场 `total` 条的虚拟会话，只认 tail 这一档——这些用例都从尾部开局。 */
function stubSession(total: number) {
  return vi.fn(async () => {
    const start = Math.max(0, total - PAGE_SIZE);
    const seqs = Array.from({ length: total - start }, (_, i) => start + i);
    return { ok: true, json: async () => seqs.map((s) => record(s)) } as Response;
  });
}

function push(records: WorkbenchRecord[], sessionId = SID) {
  const msg = {
    type: 'session_records_append',
    timestamp: '2026-09-12T21:03:15',
    data: { session_id: sessionId, records },
  };
  handlers.get('session_records_append')?.forEach((h) => h(JSON.parse(JSON.stringify(msg))));
}

describe('中栏收实时推送', () => {
  beforeEach(() => {
    handlers.clear();
    vi.unstubAllGlobals();
  });

  it('推来一整场历史，只留窗内那几条新的——旧对话不许接在最新内容后面', async () => {
    vi.stubGlobal('fetch', stubSession(935));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));
    expect(result.current.records[0].seq).toBe(735);

    // 服务端犯的那个错的原样：整场除最后几十条之外的全部，加上真正新长出来的三条。
    const history = Array.from({ length: 735 }, (_, i) => record(i));
    const fresh = [record(935), record(936), record(937)];
    act(() => push([...history, ...fresh]));

    expect(result.current.records).toHaveLength(PAGE_SIZE + 3);
    expect(result.current.records[0].seq).toBe(735);
    expect(result.current.records[result.current.records.length - 1].seq).toBe(937);
    const seqs = result.current.records.map((r) => r.seq);
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
  });

  it('挪位之后新写下来的那条落在窗内，照收，并且落在它该在的位置上', async () => {
    vi.stubGlobal('fetch', stubSession(300));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));

    // 引擎重写掉一条记录，后面的整体往前挪一格：新说的那句话正好落在手头末条的编号上。
    act(() => push([record(299, '刚说的那句')]));

    expect(result.current.records).toHaveLength(PAGE_SIZE + 1);
    expect(result.current.records[result.current.records.length - 1].id).toBe('刚说的那句');
  });

  it('同一批推两遍，第二遍一条不进', async () => {
    vi.stubGlobal('fetch', stubSession(300));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));

    act(() => push([record(300)]));
    expect(result.current.records).toHaveLength(PAGE_SIZE + 1);
    act(() => push([record(300)]));
    expect(result.current.records).toHaveLength(PAGE_SIZE + 1);
  });

  it('手上一条都没有时照收：新开的那一场，推送是它唯一的内容来源', async () => {
    vi.stubGlobal('fetch', stubSession(0));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.records).toHaveLength(0);

    act(() => push([record(0), record(1)]));
    expect(result.current.records.map((r) => r.seq)).toEqual([0, 1]);
  });

  it('别人那场的推送不进这一场', async () => {
    vi.stubGlobal('fetch', stubSession(300));
    const { result } = renderHook(() => useWorkbenchRecords(SID));
    await waitFor(() => expect(result.current.records).toHaveLength(PAGE_SIZE));

    act(() => push([record(300)], 'ffffffff-1111-2222-3333-444444444444'));
    expect(result.current.records).toHaveLength(PAGE_SIZE);
  });
});
