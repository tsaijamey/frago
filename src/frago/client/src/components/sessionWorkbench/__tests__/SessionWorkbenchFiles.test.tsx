/**
 * 会话页那一档「文件」的个数：**切到这一场就得在**，不等人点一下。
 *
 * 主人 10-10 报的缺陷就是这个：切到某场会话，镜头排上「Files」后面什么都没有，点一下才冒
 * 出数字——那个数跟旁边几档一样是这一场的读数，空着看着就是说「它没动过文件」。
 *
 * 这一页其余数据源用替身，只把「哪一场会话」与 `getSessionFiles` 这两样接上真的。
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import type { SessionFileRow } from '@/types/api';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

const NOW = Date.now();
const SID = 'sid-files';

const page = vi.hoisted(() => ({
  sessions: [] as WorkbenchSession[],
  records: [] as unknown[],
  recordsSessionId: null as string | null,
}));

const getSessionFiles = vi.hoisted(() => vi.fn());

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
  useWorkbenchRecords: () => ({
    records: page.records,
    recordsSessionId: page.recordsSessionId,
    loading: false,
    loadingOlder: false,
    hasOlder: false,
    error: null,
    loadOlder: async () => {},
    reload: async () => {},
    awaitingAgent: false,
    outbound: [],
    deliveredAt: null,
    markSent: () => 'out-0',
    clearSent: () => {},
    settleSent: () => {},
    trails: [],
  }),
}));

vi.mock('@/hooks/useSessionLaunch', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useSessionLaunch: () => ({ launch: null, begin: () => {}, dismiss: () => {} }),
}));

vi.mock('@/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  getSessionFiles: (sid: string) => getSessionFiles(sid),
  getTmuxWaiting: async () => ({ sessions: [] }),
}));

function session(id: string): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id}`,
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
  };
}

function record(id: string, seq: number) {
  return {
    id,
    session_id: SID,
    group_id: null,
    seq,
    ts: NOW,
    kind: 'agent.say',
    agent_path: [],
    payload: { text: '好' },
    raw_available: true,
  };
}

function file(path: string): SessionFileRow {
  return { path, action: 'modified', count: 1, first_seq: 0 };
}

afterEach(() => {
  vi.unstubAllGlobals();
  page.records = [];
  page.recordsSessionId = null;
  getSessionFiles.mockReset();
});

async function openPage() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => ({ viewed: {} }) })) as unknown as typeof fetch
  );
  const { usePageStore } = await import('@/stores/pageStore');
  usePageStore.getState().setWorkbenchSessionId(SID);
  const { default: SessionWorkbenchPage } = await import('../SessionWorkbenchPage');
  await act(async () => {
    render(<SessionWorkbenchPage />);
  });
  return () => usePageStore.getState().setWorkbenchSessionId(null);
}

describe('切到会话，文件个数当场在', () => {
  it('一挂上就去取，数字不用点就出现', async () => {
    page.sessions = [session(SID)];
    page.records = [record('r1', 0)];
    page.recordsSessionId = SID;
    getSessionFiles.mockResolvedValue([file('/w/a.py'), file('/w/b.py'), file('/w/c.py')]);

    const done = await openPage();

    await waitFor(() => expect(screen.getByTestId('lens-files').textContent).toBe('Files3'));
    expect(getSessionFiles).toHaveBeenCalledWith(SID);
    // 没点过那一档：清单面板不该自己铺开。
    expect(screen.queryByTestId('files-panel')).toBeNull();
    done();
  });

  it('还没数出来时先写省略号，不写成「没有」', async () => {
    page.sessions = [session(SID)];
    page.records = [record('r1', 0)];
    page.recordsSessionId = SID;
    // 一直不回来：这一档就停在「还在数」。
    getSessionFiles.mockReturnValue(new Promise(() => {}));

    const done = await openPage();

    await waitFor(() => expect(screen.getByTestId('lens-files-pending')).toBeTruthy());
    expect(screen.getByTestId('lens-files').textContent).toBe('Files…');
    done();
  });

  it('这一场确实没动过文件：写 0，不写省略号', async () => {
    page.sessions = [session(SID)];
    page.records = [record('r1', 0)];
    page.recordsSessionId = SID;
    getSessionFiles.mockResolvedValue([]);

    const done = await openPage();

    await waitFor(() => expect(screen.getByTestId('lens-files').textContent).toBe('Files0'));
    expect(screen.queryByTestId('lens-files-pending')).toBeNull();
    done();
  });

  it('取不到就说故障，不写个数也不写省略号', async () => {
    page.sessions = [session(SID)];
    page.records = [record('r1', 0)];
    page.recordsSessionId = SID;
    getSessionFiles.mockRejectedValue(new Error('boom'));

    const done = await openPage();

    await waitFor(() => expect(getSessionFiles).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByTestId('lens-files-pending')).toBeNull()
    );
    expect(screen.getByTestId('lens-files').textContent).toBe('Files');
    done();
  });
});
