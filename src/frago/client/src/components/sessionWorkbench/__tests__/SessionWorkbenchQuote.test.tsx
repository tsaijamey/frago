/**
 * 页面这一层接上「发出成功之后该发生的事」：引用留痕、暂存转用过、带回主线的分支收口。
 *
 * 点「引用」只把原文填进输入框，那一刻不留痕；这句话**落进会话**、而且发出去的内容里还
 * 带着那段原文，才落成引用标注。三种不该留痕的情况各钉一条：引了又删掉、改写成别的、
 * 根本没发（切走了）。
 *
 * 三件事都钉同一条真实踩过的：发送接口要等整整一轮说完才回来，一轮跑得久它就迟迟不回
 * （或以超时收场）。它们 NEVER 等它——这里让接口永远不回，只推进「进了会话」那一步，
 * 三件事照样发生。
 *
 * 记录流换成替身：划选、量位置那一套在 SelectionQuote 自己的用例里钉，这里只看页面把
 * 「引用」这个动作接到了哪里。
 */

import { useSyncExternalStore } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { SendTrail, WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const NOW = Date.now();
const MAIN = '11111111-1111-4111-8111-111111111111';
const OTHER = '33333333-3333-4333-8333-333333333333';
const QUOTED = '先把配色改回中性';

/** 发送进度的替身：测试里手动推进「进了会话」那一步。 */
const trails = vi.hoisted(() => {
  let list: SendTrail[] = [];
  const subs = new Set<() => void>();
  return {
    get: () => list,
    set(next: SendTrail[]) {
      list = next;
      subs.forEach((f) => f());
    },
    subscribe(f: () => void) {
      subs.add(f);
      return () => subs.delete(f);
    },
  };
});

const page = vi.hoisted(() => ({
  sessions: [] as WorkbenchSession[],
  records: {} as Record<string, WorkbenchRecord[]>,
}));

const api = vi.hoisted(() => ({
  getSessionMarks: vi.fn(),
  putSessionMarks: vi.fn(),
  closeBranch: vi.fn(),
}));

vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/hooks/useWorkbenchSessions')>();
  return {
    ...real,
    useWorkbenchSessions: () => ({
      sessions: page.sessions,
      visible: page.sessions,
      loading: false,
      error: null,
      filter: 'all',
      setFilter: () => {},
      days: 0,
      setDays: () => {},
      counts: { all: page.sessions.length, 'for-you': 0 },
      reload: async () => {},
    }),
  };
});

vi.mock('@/hooks/useWorkbenchRecords', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useWorkbenchRecords: (sid: string | null) => ({
    records: (sid && page.records[sid]) || [],
    recordsSessionId: sid,
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    loadOlder: async () => {},
    reload: async () => {},
    awaitingAgent: false,
    outbound: [],
    deliveredAt: null,
    markSent: () => 'out-1',
    clearSent: () => {},
    settleSent: () => {},
    trails: useSyncExternalStore(trails.subscribe, trails.get),
  }),
}));

vi.mock('@/hooks/useSessionLaunch', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSessionLaunch: () => ({ launch: null, begin: () => {}, dismiss: () => {} }),
}));

vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getTmuxWaiting: async () => ({ sessions: [] }),
  getSessionMarks: (...a: unknown[]) => api.getSessionMarks(...a),
  putSessionMarks: (...a: unknown[]) => api.putSessionMarks(...a),
  closeBranch: (...a: unknown[]) => api.closeBranch(...a),
}));

/** 记录流替身：一颗按钮代表「圈了这段、按了引用」。 */
vi.mock('../RecordStream', () => ({
  default: (props: {
    onQuote?: (text: string, anchor?: { record_id: string; text: string; occurrence: number }) => void;
  }) => (
    <div data-testid="fake-stream">
      <button
        type="button"
        data-testid="fake-quote"
        onClick={() => props.onQuote?.(QUOTED, { record_id: 'r1', text: QUOTED, occurrence: 0 })}
      />
    </div>
  ),
}));

function session(id: string, over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id.slice(0, 4)}`,
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 3_600_000,
    last_active_at: NOW - 60_000,
    last_reply_at: NOW - 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

/** 「这一单进了会话」：进度里记上那一步。 */
function landed(id = 'out-1'): SendTrail {
  return {
    id,
    text: '',
    attachments: 0,
    recordId: 'rec-sent',
    midTurn: false,
    steps: { on_its_way: NOW, in_the_session: NOW + 1 },
  };
}

/** 最后一次整份送出的那一份里的引用标注。一次都没送过就是空。 */
function quoteMarksPut(): WorkbenchMark[] {
  const calls = api.putSessionMarks.mock.calls;
  if (!calls.length) return [];
  const body = calls[calls.length - 1][1] as { marks: WorkbenchMark[] };
  return body.marks.filter((m) => m.kind === 'quote');
}

const fetchMock = vi.fn();

beforeEach(() => {
  api.getSessionMarks.mockReset();
  api.putSessionMarks.mockReset();
  api.closeBranch.mockReset();
  api.closeBranch.mockResolvedValue({ closed_at: 1, closed_by: 'bring-back', mark_updated: true });
  page.records = {};
  api.getSessionMarks.mockResolvedValue({ version: 1, marks: [] });
  api.putSessionMarks.mockImplementation(async (_sid: string, body: unknown) => body);
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url: string) => {
    // 发送接口一直不回：这一轮还没说完。
    if (String(url).endsWith('/send')) return new Promise(() => {});
    return { ok: true, json: async () => ({ viewed: {} }) };
  });
  vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);
  trails.set([]);
  page.sessions = [session(MAIN), session(OTHER)];
});

afterEach(async () => {
  vi.unstubAllGlobals();
  const { usePageStore } = await import('@/stores/pageStore');
  usePageStore.getState().setWorkbenchSessionId(null);
});

async function mountOn(sid: string) {
  const { usePageStore } = await import('@/stores/pageStore');
  usePageStore.getState().setWorkbenchSessionId(sid);
  const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
  await act(async () => {
    render(<SessionWorkbenchPage />);
  });
  return usePageStore;
}

/** 按引用，等原文按引用格式落进输入框。 */
async function quoteIntoBox(): Promise<HTMLTextAreaElement> {
  await act(async () => {
    fireEvent.click(screen.getByTestId('fake-quote'));
  });
  const input = (await screen.findByTestId('composer-input')) as HTMLTextAreaElement;
  await waitFor(() => expect(input.value).toContain(QUOTED));
  return input;
}

async function send(input: HTMLTextAreaElement, value: string) {
  await act(async () => {
    fireEvent.change(input, { target: { value } });
  });
  await act(async () => {
    fireEvent.click(screen.getByTestId('composer-send'));
  });
  await waitFor(() =>
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/send'))).toBe(true)
  );
}

describe('引用何时留痕', () => {
  it('点引用那一刻不留痕', async () => {
    await mountOn(MAIN);
    await quoteIntoBox();
    await Promise.resolve();
    expect(quoteMarksPut()).toEqual([]);
  });

  it('带着原文发出、落进会话：留痕——发送接口还没回也照样落', async () => {
    await mountOn(MAIN);
    const input = await quoteIntoBox();
    await send(input, `${input.value}同意`);
    // 接口还挂着，只是发出去了：此刻不留痕
    expect(quoteMarksPut()).toEqual([]);
    await act(async () => {
      trails.set([landed()]);
    });
    await waitFor(() => expect(quoteMarksPut().map((m) => m.text)).toEqual([QUOTED]));
    expect(api.putSessionMarks.mock.calls[api.putSessionMarks.mock.calls.length - 1][0]).toBe(MAIN);
  });

  it('引了又把原文删掉再发：不留痕', async () => {
    await mountOn(MAIN);
    const input = await quoteIntoBox();
    await send(input, '算了，说别的');
    await act(async () => {
      trails.set([landed()]);
    });
    await Promise.resolve();
    expect(quoteMarksPut()).toEqual([]);
  });

  it('引了又改写成别的内容再发：不留痕', async () => {
    await mountOn(MAIN);
    const input = await quoteIntoBox();
    await send(input, '"""\n先把配色改成蓝色\n"""\n>>> 这样行吗');
    await act(async () => {
      trails.set([landed()]);
    });
    await Promise.resolve();
    expect(quoteMarksPut()).toEqual([]);
  });

  it('引了没发就切走：不留痕，回来再发别的也不算', async () => {
    const store = await mountOn(MAIN);
    await quoteIntoBox();
    await act(async () => {
      store.getState().setWorkbenchSessionId(OTHER);
    });
    await act(async () => {
      store.getState().setWorkbenchSessionId(MAIN);
    });
    const input = (await screen.findByTestId('composer-input')) as HTMLTextAreaElement;
    await send(input, `"""\n${QUOTED}\n"""\n>>> 顺便一提`);
    await act(async () => {
      trails.set([landed()]);
    });
    await Promise.resolve();
    expect(quoteMarksPut()).toEqual([]);
  });

  it('同一单进了会话之后进度再变：只落一次', async () => {
    await mountOn(MAIN);
    const input = await quoteIntoBox();
    await send(input, input.value);
    await act(async () => {
      trails.set([landed()]);
    });
    await waitFor(() => expect(quoteMarksPut()).toHaveLength(1));
    await act(async () => {
      trails.set([{ ...landed(), steps: { ...landed().steps, picked_up: NOW + 2 } }]);
    });
    await Promise.resolve();
    expect(quoteMarksPut()).toHaveLength(1);
  });
});

describe('暂存转用过：一轮还没说完也照样转', () => {
  const stacked: WorkbenchMark = {
    id: 'mk_s',
    kind: 'stack',
    record_id: 'r1',
    text: '第二个决策点',
    occurrence: 0,
    note: '倾向选乙',
    used: false,
    created_at: 1,
    used_at: null,
  };

  it('填入、发出、落进会话：标用过——发送接口还没回', async () => {
    api.getSessionMarks.mockResolvedValue({ version: 1, marks: [stacked] });
    await mountOn(MAIN);
    await act(async () => {
      fireEvent.click(await screen.findByTestId('stack-item-fill'));
    });
    const input = (await screen.findByTestId('composer-input')) as HTMLTextAreaElement;
    await waitFor(() => expect(input.value).toContain('第二个决策点'));
    await send(input, input.value);
    expect(api.putSessionMarks).not.toHaveBeenCalled();
    await act(async () => {
      trails.set([landed()]);
    });
    await waitFor(() => expect(api.putSessionMarks).toHaveBeenCalled());
    const calls = api.putSessionMarks.mock.calls;
    const body = calls[calls.length - 1][1] as { marks: WorkbenchMark[] };
    expect(body.marks.find((m) => m.id === 'mk_s')?.used).toBe(true);
  });
});

describe('带回主线收口：一轮还没说完也照样收', () => {
  const CHILD = '22222222-2222-4222-8222-222222222222';

  it('带回、发出、落进会话：收口——发送接口还没回', async () => {
    page.sessions = [
      session(MAIN),
      session(CHILD, { parent_session_id: MAIN, relation: { kind: 'branch', closed: false } }),
    ];
    page.records[CHILD] = [
      {
        id: 'a1',
        session_id: CHILD,
        group_id: null,
        seq: 1,
        ts: NOW - 60_000,
        kind: 'agent.say',
        agent_path: [],
        payload: { text: '查过了，是代理超时' },
        raw_available: false,
      },
    ];
    await mountOn(CHILD);
    await act(async () => {
      fireEvent.click(screen.getByTestId('composer-bring-back'));
    });
    const input = (await screen.findByTestId('composer-input')) as HTMLTextAreaElement;
    await waitFor(() => expect(input.value).toContain('查过了，是代理超时'));
    await send(input, `${input.value}那就不查了`);
    expect(api.closeBranch).not.toHaveBeenCalled();
    await act(async () => {
      trails.set([landed()]);
    });
    await waitFor(() => expect(api.closeBranch).toHaveBeenCalledWith(MAIN, CHILD, 'bring-back'));
    // 进度再变也只收一次
    await act(async () => {
      trails.set([{ ...landed(), steps: { ...landed().steps, picked_up: NOW + 2 } }]);
    });
    await Promise.resolve();
    expect(api.closeBranch).toHaveBeenCalledTimes(1);
  });
});
