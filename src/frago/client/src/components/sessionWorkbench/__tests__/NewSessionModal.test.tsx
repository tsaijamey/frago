/**
 * 新建会话对话框里"挑客户端"那一段的用例。
 *
 * 盯五件人真会撞上的事：
 *
 * 1. **名单来自服务端**，不是这里写死的三个名字。写死的话，接新家的人改完 driver 会发现
 *    界面上它根本不出现，而 driver 那侧一点异样都没有。
 * 2. **用不了的那几家不藏**，折在一句话后面，点开看得见为什么用不了——藏掉的话，人只会
 *    以为 frago 不支持它，而真相往往只是没装。
 * 3. **挑了谁就用谁**：创建时送出去的是选中那一家，不是永远的 claude。
 * 4. **编号要等认领的那两家先把这段空窗说在前头**，点完创建才发现要等，人会以为卡住了。
 * 5. **建不起来时留在对话框里**，把话原样摆出来——关掉再弹提示，人打的那段话就没了。
 */

import { describe, expect, it, vi, beforeAll, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import NewSessionModal from '../NewSessionModal';
import i18n from '@/i18n';

/**
 * 界面上的字全部走词表了，用例断言的是中文那一份，所以先把语言切到中文。
 *
 * 这一句顺带把另一件事也核了：`zh.json` 里的字必须与从前写死在组件里的逐字相同，
 * 差一个标点，下面这些断言就红。
 */
beforeAll(async () => {
  await i18n.changeLanguage('zh');
});


vi.mock('../../../api/client', () => ({
  getSystemDirectories: async () => ({ home: '/Users/frago', cwd: '/Users/frago/Repos/frago' }),
}));

vi.mock('../../../utils/recentDirectories', () => ({
  getRecentDirectories: () => [],
  addRecentDirectory: vi.fn(),
}));

const AGENTS = [
  {
    agent_type: 'claude',
    display_name: 'Claude Code',
    installed: true,
    path: '/usr/local/bin/claude',
    family: 'claude-code',
    selectable: true,
    reason: null,
    id_origin: 'caller' as const,
  },
  {
    agent_type: 'codex',
    display_name: 'Codex CLI',
    installed: true,
    path: '/opt/homebrew/bin/codex',
    family: 'codex',
    selectable: true,
    reason: null,
    id_origin: 'claimed' as const,
  },
  {
    agent_type: 'codebuddy',
    display_name: 'CodeBuddy Code',
    installed: true,
    path: '/Applications/WorkBuddy.app/cli',
    family: null,
    selectable: false,
    reason: '它的会话记录读不进工作台',
    id_origin: 'caller' as const,
  },
];

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;
let posted: Array<Record<string, unknown>>;

beforeEach(() => {
  localStorage.clear();
  posted = [];
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (String(url).endsWith('/api/workbench/agents')) {
      return jsonResponse({ agents: AGENTS, default: 'claude' });
    }
    if (String(url).endsWith('/api/workbench/sessions')) {
      const body = JSON.parse(String(init?.body ?? '{}'));
      posted.push(body);
      return jsonResponse({
        handle: body.agent === 'claude' ? 'a-uuid' : 'webui-handle',
        agent: body.agent,
        display_name: body.agent,
        cwd: body.cwd,
        session_id: body.agent === 'claude' ? 'a-uuid' : null,
        error: null,
        finished: false,
      });
    }
    throw new Error(`没料到的请求：${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(onCreated = vi.fn()) {
  render(<NewSessionModal isOpen onClose={vi.fn()} onCreated={onCreated} />);
  return onCreated;
}

async function fillFirstMessage(text = '干活') {
  fireEvent.change(await screen.findByPlaceholderText('要它做什么…'), {
    target: { value: text },
  });
}

describe('NewSessionModal — 挑客户端', () => {
  it('候选来自服务端，不是写死的三个名字', async () => {
    open();
    expect((await screen.findByTestId('agent-claude')).textContent).toContain('Claude Code');
    expect(screen.getByTestId('agent-codex').textContent).toContain('Codex CLI');
  });

  it('用不了的那一家不摆在可挑的那一排里', async () => {
    open();
    await screen.findByTestId('agent-claude');
    expect(screen.queryByTestId('agent-codebuddy')).toBeNull();
  });

  it('用不了的那几家折在一句话后面，点开说得出为什么', async () => {
    open();
    const toggle = await screen.findByTestId('toggle-unavailable-agents');
    expect(toggle.textContent).toContain('还有 1 个用不了');
    // 折着的时候不占地方，理由也不在页面上。
    expect(screen.queryByText(/读不进工作台/)).toBeNull();

    fireEvent.click(toggle);
    expect(screen.getByText(/读不进工作台/)).toBeTruthy();
  });

  it('默认选中服务端建议的那一家', async () => {
    open();
    const claude = await screen.findByTestId('agent-claude');
    expect(claude.getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('agent-codex').getAttribute('aria-checked')).toBe('false');
  });

  it('上次挑过的那一家优先于服务端建议的默认值', async () => {
    localStorage.setItem('frago-workbench-last-agent', 'codex');
    open();
    expect((await screen.findByTestId('agent-codex')).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('agent-claude').getAttribute('aria-checked')).toBe('false');
  });

  it('上次挑的那一家现在挑不了时，不声张地退回默认', async () => {
    localStorage.setItem('frago-workbench-last-agent', 'codebuddy');
    open();
    expect((await screen.findByTestId('agent-claude')).getAttribute('aria-checked')).toBe('true');
  });

  it('编号要等认领的那一家，先把这段空窗说在前头', async () => {
    open();
    fireEvent.click(await screen.findByTestId('agent-codex'));
    expect(screen.getByText(/会话编号由它自己分配/)).toBeTruthy();

    // 编号当场就有的那一家不该多这句话——没有等待却说要等，是另一种谎报。
    fireEvent.click(screen.getByTestId('agent-claude'));
    expect(screen.queryByText(/会话编号由它自己分配/)).toBeNull();
  });

  it('挑了谁就把谁送出去，并记住这次的选择', async () => {
    const onCreated = open();
    fireEvent.click(await screen.findByTestId('agent-codex'));
    await fillFirstMessage();
    fireEvent.click(screen.getByText('创建'));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].agent).toBe('codex');
    expect(posted[0].text).toBe('干活');
    expect(localStorage.getItem('frago-workbench-last-agent')).toBe('codex');

    // 编号还没有的那条路，把手照原样交出去，NEVER 在这里编一个编号。
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated.mock.calls[0][0]).toMatchObject({
      handle: 'webui-handle',
      session_id: null,
    });
  });

  it('建不起来时留在对话框里，人打的那段话还在', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (String(url).endsWith('/api/workbench/agents')) {
        return jsonResponse({ agents: AGENTS, default: 'claude' });
      }
      return jsonResponse({ detail: 'Codex CLI 现在挑不了：本机没找到这个命令' }, false, 400);
    });

    const onCreated = open();
    await screen.findByTestId('agent-claude');
    await fillFirstMessage('别丢了这句话');
    fireEvent.click(screen.getByText('创建'));

    expect(await screen.findByText(/本机没找到这个命令/)).toBeTruthy();
    expect(onCreated).not.toHaveBeenCalled();
    expect((screen.getByPlaceholderText('要它做什么…') as HTMLTextAreaElement).value).toBe(
      '别丢了这句话'
    );
  });

  it('一家可用的都没有时明说，而不是摆一个点了必错的默认值', async () => {
    fetchMock.mockImplementation(async () =>
      jsonResponse({ agents: [AGENTS[2]], default: null })
    );
    open();
    expect(await screen.findByText(/本机一家可用的 CLI 都没找到/)).toBeTruthy();
  });
});
