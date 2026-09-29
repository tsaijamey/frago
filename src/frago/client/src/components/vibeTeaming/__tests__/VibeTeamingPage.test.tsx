/**
 * Teams 页结对之后的样子：一眼分得清哪边是我、发之前知道会怎样、发之后看得到走到哪。
 *
 * 钉住的是 spec 验收里那几条人看得见的事：两栏身份头与说话人叫法、页面上不出现完整
 * 连接码、右栏「Your request」卡与左栏队友请求块各在对的一栏、右下三格按输入点亮、
 * 三格的来源标签不说假话、首次说明收起后记住。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import i18n from '@/i18n';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';
import type { TeamStatus } from '@/hooks/useTeam';

const CODE = '7R7PEMN4PT';
const verify = (mid: string) =>
  `（核实来源：frago team verify --team-code ${CODE} --message ${mid}）`;

function rec(id: string, kind: WorkbenchRecord['kind'], text: string, ts: number): WorkbenchRecord {
  return {
    id,
    session_id: 's',
    group_id: null,
    seq: ts,
    ts,
    kind,
    agent_path: [],
    payload: { text },
    raw_available: false,
  };
}

const mineRecords: WorkbenchRecord[] = [
  rec('m1', 'user.say', `我的码是 ${CODE}，别外传`, 1_000),
  rec('m2', 'agent.say', '好的', 2_000),
  rec('m3', 'user.say', `【frago team】前缀\n\n帮我看一下你那边 frago --version\n\n${verify('mid-incoming-1')}`, 3_000),
];

const peerRecords: WorkbenchRecord[] = [
  rec('p1', 'user.say', '先做我自己的事', 1_000),
  rec('p2', 'user.say', `【frago team】前缀\n\n跑一下测试\n\n${verify('mid-outgoing-1')}`, 2_000),
  rec('p3', 'agent.say', '测试全过了', 3_000),
];

let peerStatus: TeamStatus;
const sendToPeer = vi.fn(async () => 'mid-new');

vi.mock('@/hooks/useTeam', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useTeam')>();
  return {
    ...actual,
    useTeamState: () => ({
      state: {
        member: 'me',
        configured: true,
        relay_url: 'https://www.frago.ai',
        prefix: '',
        interval_seconds: 15,
        request_rules: { read: 'do', change: 'ask' },
        teams: [{ code: CODE, session_id: 'sess-1', side: 'A', active: true, pushed_seq: 3 }],
      },
      error: null,
      loading: false,
      reload: async () => {},
    }),
    usePeerRecords: () => ({
      records: peerRecords,
      status: peerStatus,
      loading: false,
      error: null,
      reload: async () => {},
    }),
    sendToPeer: (...args: unknown[]) => sendToPeer(...(args as [])),
    verifyRelayed: async () => true,
  };
});

vi.mock('@/hooks/useWorkbenchRecords', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useWorkbenchRecords')>();
  return {
    ...actual,
    useWorkbenchRecords: () => ({
      records: mineRecords,
      loading: false,
      loadingOlder: false,
      hasOlder: false,
      error: null,
      loadOlder: async () => {},
      reload: async () => {},
      awaitingAgent: false,
      markSent: () => undefined,
      clearSent: () => {},
      settleSent: () => {},
      deliveredAt: null,
      outbound: [],
    }),
  };
});

vi.mock('@/hooks/useWorkbenchSessions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useWorkbenchSessions')>();
  return {
    ...actual,
    useWorkbenchSessions: () => ({
      sessions: [{ session_id: 'sess-1', family: 'claude-code', title: 't', status: 'idle' }],
      reload: async () => {},
    }),
  };
});

// 输入区是会话页那一整套，这里只要它在、并且是这一屏唯一的实心绿发送键。
vi.mock('@/components/sessionWorkbench/Composer', () => ({
  default: () => (
    <button className="bg-accent-primary" data-testid="composer-send">
      Send
    </button>
  ),
}));

import VibeTeamingPage from '../VibeTeamingPage';

beforeAll(async () => {
  await i18n.changeLanguage('en');
});

beforeEach(() => {
  peerStatus = { exists: true, side: 'A', peer_present: true, inbox: 0, peer_inbox: 0 };
  window.localStorage.clear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('两栏归属', () => {
  it('各有身份头，右栏标只读', () => {
    render(<VibeTeamingPage />);
    const mine = screen.getByTestId('identity-me');
    const peer = screen.getByTestId('identity-peer');
    expect(within(mine).getByText('You')).toBeTruthy();
    expect(within(mine).getByText(/Your agent · Claude Code · this machine/)).toBeTruthy();
    expect(within(peer).getByText('Teammate')).toBeTruthy();
    expect(within(peer).getByText('Read-only')).toBeTruthy();
  });

  it('说话人叫法两栏各说各的', () => {
    render(<VibeTeamingPage />);
    const mine = screen.getByTestId('teams-mine');
    const peer = screen.getByTestId('teams-peer');
    expect(within(mine).getAllByText('You said').length).toBeGreaterThan(0);
    expect(within(mine).getByText('Your agent replied')).toBeTruthy();
    expect(within(peer).getByText('Your teammate said')).toBeTruthy();
    expect(within(peer).getAllByText('Their agent replied').length).toBeGreaterThan(0);
  });

  it('左下有泄露提醒；实心绿只有左下那一个', () => {
    const { container } = render(<VibeTeamingPage />);
    expect(screen.getByTestId('teams-leak-note').textContent).toMatch(/Don't paste keys/);
    expect(container.querySelectorAll('.bg-accent-primary, .page-header-primary').length).toBe(1);
  });
});

describe('连接码', () => {
  it('页面可见文字里没有完整码，页头只露前 4 位', () => {
    render(<VibeTeamingPage />);
    expect(document.body.textContent).not.toContain(CODE);
    expect(screen.getByTestId('team-code').textContent).toBe('7R7P••••••');
  });

  it('Copy 复制到的是完整码', async () => {
    const writeText = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText } });
    render(<VibeTeamingPage />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('team-code-copy'));
    });
    expect(writeText).toHaveBeenCalledWith(CODE);
  });
});

describe('请求', () => {
  it('右栏记录里真实转来的请求画成「Your request」卡，对方已回复', () => {
    render(<VibeTeamingPage />);
    const peer = screen.getByTestId('teams-peer');
    const card = within(peer).getByTestId('team-request-card');
    expect(card.textContent).toContain('跑一下测试');
    expect(card.getAttribute('data-step')).toBe('replied');
    expect(within(peer).queryByText(/核实来源/)).toBeNull();
  });

  it('左栏的队友请求画成「From your teammate」块，只摆原文', () => {
    render(<VibeTeamingPage />);
    const mine = screen.getByTestId('teams-mine');
    const block = within(mine).getByTestId('team-incoming');
    expect(block.textContent).toContain('From your teammate');
    expect(block.textContent).toContain('帮我看一下你那边 frago --version');
    expect(block.textContent).not.toContain('核实来源');
    expect(within(block).getByTestId('team-incoming-rules').textContent).toMatch(
      /read-only asks → do it/
    );
  });

  it('右下输入「push the fix」点亮第二格，Send 左边写明命中的词', () => {
    render(<VibeTeamingPage />);
    const box = within(screen.getByTestId('teams-instruct')).getByRole('textbox');
    fireEvent.change(box, { target: { value: 'push the fix' } });
    expect(screen.getByTestId('tier-change').getAttribute('data-on')).toBe('true');
    expect(screen.getByTestId('tier-read').getAttribute('data-on')).toBeNull();
    const said = screen.getByTestId('peer-prediction').textContent ?? '';
    expect(said).toContain('“push”, “fix”');
    expect(said).toContain('ask its owner first');
  });

  it('发出之后右栏流末尾立刻有一张停在 Sent 的卡', async () => {
    render(<VibeTeamingPage />);
    const box = within(screen.getByTestId('teams-instruct')).getByRole('textbox');
    fireEvent.change(box, { target: { value: '看看磁盘还剩多少' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('teams-instruct-send'));
    });
    expect(sendToPeer).toHaveBeenCalledWith(CODE, '看看磁盘还剩多少');
    const cards = within(screen.getByTestId('teams-peer')).getAllByTestId('team-request-card');
    const fresh = cards.find((one) => one.textContent?.includes('看看磁盘还剩多少'));
    expect(fresh?.getAttribute('data-step')).toBe('sent');
  });
});

describe('三格的来源不说假话', () => {
  it('对方设置没传过来时标 frago 的规矩', () => {
    render(<VibeTeamingPage />);
    const source = screen.getByTestId('peer-tiers-source');
    expect(source.getAttribute('data-source')).toBe('frago');
    expect(source.textContent).toBe("frago's rules");
  });

  it('传过来了就标对方设的，并按对方的设置预判', () => {
    peerStatus = { ...peerStatus, peer_rules: { read: 'do', change: 'refuse' } };
    render(<VibeTeamingPage />);
    expect(screen.getByTestId('peer-tiers-source').textContent).toBe('Set by your teammate');
    expect(screen.getByTestId('tier-change').textContent).toContain('Refuses');
    const box = within(screen.getByTestId('teams-instruct')).getByRole('textbox');
    fireEvent.change(box, { target: { value: 'push it' } });
    expect(screen.getByTestId('peer-prediction').textContent).toContain('their agent will refuse');
  });
});

describe('首次说明与我的设置', () => {
  it('第一次展开，收起后记住，「?」可再打开', () => {
    const first = render(<VibeTeamingPage />);
    expect(screen.getByTestId('teams-guide')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Hide — reopen with ?'));
    expect(screen.queryByTestId('teams-guide')).toBeNull();
    first.unmount();

    render(<VibeTeamingPage />);
    expect(screen.queryByTestId('teams-guide')).toBeNull();
    fireEvent.click(screen.getByTestId('teams-help'));
    expect(screen.getByTestId('teams-guide')).toBeTruthy();
  });

  it('左栏输入框上方一行摘要写着本机的设置', () => {
    render(<VibeTeamingPage />);
    expect(screen.getByTestId('my-rules-summary').textContent).toBe(
      'read-only → do it · changes → ask me'
    );
  });
});
