/**
 * 页面这一层接上真的 `useForYou`：终端清单报出一场在等你，左栏挂上、页头写出等了多久。
 *
 * 其余数据源换成替身，For you 这一路（取终端清单 → 对上会话 → 交给清单与页头）用真的，
 * 顺带把「For you 判定经一格状态交给清单」那一圈钉住——那里要是互相叫醒，页面会卡死。
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

const NOW = Date.now();
const SID = 'waiting-one';

const page = vi.hoisted(() => ({
  sessions: [] as WorkbenchSession[],
  records: [] as unknown[],
  recordsSessionId: null as string | null,
}));

vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/hooks/useWorkbenchSessions')>();
  return {
    ...real,
    useWorkbenchSessions: (isForYou: (id: string) => boolean = () => false) => ({
      sessions: page.sessions,
      visible: page.sessions,
      loading: false,
      error: null,
      filter: 'all',
      setFilter: () => {},
      days: 0,
      setDays: () => {},
      counts: {
        all: page.sessions.length,
        'for-you': page.sessions.filter((s) => isForYou(s.session_id)).length,
      },
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
  getTmuxWaiting: async () => ({
    sessions: [
      {
        name: `frago-agent-${SID}`,
        session_id: SID,
        client_alive: true,
        awaiting_input: true,
        stop_reason: 'end_turn',
        last_stop_at: new Date(NOW - 44 * 60_000).toISOString(),
        closing_text: 'Reply with one letter for the hook item: A or B.',
      },
    ],
  }),
}));

function session(id: string, over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: id,
    family: 'claude-code',
    title: `title ${id}`,
    directory: '/Users/frago/Repos/frago',
    created_at: NOW - 3_600_000,
    last_active_at: NOW - 44 * 60_000,
    last_reply_at: NOW - 44 * 60_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  page.records = [];
  page.recordsSessionId = null;
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

function previewOfCard(sid: string) {
  const item = screen
    .getAllByTestId('session-item')
    .find((el) => el.querySelector('[data-testid=session-title]')?.textContent === `title ${sid}`)!;
  return item.querySelector('[data-testid=session-preview]')?.textContent ?? '';
}

describe('页面接上 For you', () => {
  it('终端报出在等你的那一场：左栏挂 For you（品牌绿、不加重），页头写 For you · waiting', async () => {
    page.sessions = [session(SID), session('other')];
    const done = await openPage();

    await waitFor(() =>
      expect(document.querySelectorAll('[data-for-you="true"]')).toHaveLength(1)
    );
    const chip = screen.getAllByTestId('for-you-chip')[0];
    expect(chip.hasAttribute('data-emphasis')).toBe(false);
    expect(chip.className).toContain('text-accent-primary');
    expect(previewOfCard(SID)).toContain('A or B');
    expect(screen.getByTestId('list-filter-for-you').textContent).toContain('1');
    // 原型里 For you 是页头里的一枚标签，正文只说「waiting 多久」。
    const head = screen.getByTestId('head-status');
    expect(head.querySelector('[data-testid=head-for-you-chip]')).toBeTruthy();
    expect(head.textContent).toContain('waiting 44 min');
    done();
  });

  it('选中那场留了合法卡片：左栏预览换成卡片的问题，For you 标签照旧不加重', async () => {
    const { DEMOS, wrap } = await import('@/utils/__tests__/decisionDemos');
    page.sessions = [session(SID), session('other')];
    page.recordsSessionId = SID;
    page.records = [
      {
        id: 'r1',
        kind: 'agent.say',
        agent_path: [],
        ts: NOW - 44 * 60_000,
        payload: { text: wrap('两种改法。', DEMOS['single-choice']) },
      },
    ];
    const done = await openPage();

    await waitFor(() => expect(previewOfCard(SID)).toContain('地址要不要也从'));
    const chip = screen.getAllByTestId('for-you-chip')[0];
    expect(chip.hasAttribute('data-emphasis')).toBe(false);
    expect(chip.getAttribute('title')).toBeNull();
    done();
  });
});

/**
 * 详情页头第二行「状态 · 哪家 CLI · 目录」里的名字（原型 20260924-page-polish 五改）。
 * 名字是这一场的固定属性，跟目录同档灰；取出的是会话清单的 `family`，与左栏共用同一份词表。
 */
describe('详情页头写明这场跑在哪家 CLI', () => {
  it('名字排在状态与目录之间，悬停写明这场跑在哪家', async () => {
    page.sessions = [session(SID)];
    const done = await openPage();

    const name = await screen.findByTestId('head-agent');
    expect(name.textContent).toBe('Claude Code');
    expect(name.getAttribute('title')).toBe('This session runs on Claude Code');
    done();
  });

  it('换一家就写那一家的名字', async () => {
    page.sessions = [session(SID, { family: 'codex' })];
    const done = await openPage();

    const name = await screen.findByTestId('head-agent');
    expect(name.textContent).toBe('codex');
    done();
  });
});

/**
 * 页头第三样：目录照原型写缩写（家目录换成 `~`），悬停里仍是完整路径。
 */
describe('页头目录写法照原型', () => {
  it('家目录缩成 ~，其余路径原样', async () => {
    const { withTilde } = await import('../SessionWorkbenchPage');
    expect(withTilde('/Users/frago/Repos/frago')).toBe('~/Repos/frago');
    expect(withTilde('/home/someone/.frago')).toBe('~/.frago');
    expect(withTilde('/var/log')).toBe('/var/log');
    expect(withTilde('~')).toBe('~');
  });

  it('页头里显示的就是缩写', async () => {
    page.sessions = [session(SID)];
    const done = await openPage();

    await waitFor(() => expect(screen.getByText('~/Repos/frago')).toBeTruthy());
    done();
  });
});
