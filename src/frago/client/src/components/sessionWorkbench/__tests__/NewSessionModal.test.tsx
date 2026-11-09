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
import { useDataStore } from '@/stores/dataStore';
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
  browseDirectories: async (path: string) => {
    const at = path || '/Users/frago';
    const tree: Record<string, string[]> = {
      '/Users/frago': ['Repos', 'Documents'],
      '/Users/frago/Repos': ['frago', 'prod-rec-agent-service'],
    };
    return {
      path: at,
      parent: at === '/Users' ? null : at.slice(0, at.lastIndexOf('/')) || '/',
      entries: (tree[at] ?? []).map((name) => ({ name, path: `${at}/${name}` })),
    };
  },
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
    agent_type: 'ghost',
    display_name: 'Ghost CLI',
    installed: true,
    path: '/usr/local/bin/ghost',
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
    if (String(url).endsWith('/api/employees')) {
      return jsonResponse({ employees: [] });
    }
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

describe('NewSessionModal — 第一句话带附件', () => {
  it('截图粘进第一句话就跟着一起发出去，不用等会话起来再补', async () => {
    open();
    await screen.findByTestId('agent-claude');
    await fillFirstMessage('照这张图改');

    fireEvent.paste(screen.getByTestId('new-session-input'), {
      clipboardData: { files: [new File(['fake-png-bytes'], 'shot.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(screen.getAllByTestId('new-session-thumb')).toHaveLength(1));

    fireEvent.click(screen.getByText('创建'));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].text).toBe('照这张图改');
    expect((posted[0].images as string[])[0]).toContain('base64');
  });

  it('一个字没打、只有一张图，照样建得出来', async () => {
    open();
    await screen.findByTestId('agent-claude');
    // 人截了张图想说"看这个"，逼他再补一句废话没有道理。
    expect((screen.getByText('创建') as HTMLButtonElement).disabled).toBe(true);

    fireEvent.paste(screen.getByTestId('new-session-input'), {
      clipboardData: { files: [new File(['fake-png-bytes'], 'shot.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(screen.getAllByTestId('new-session-thumb')).toHaveLength(1));

    await waitFor(() => expect((screen.getByText('创建') as HTMLButtonElement).disabled).toBe(false));
  });

  it('粘错的那一张能单独拿掉，不必整批重来', async () => {
    open();
    await screen.findByTestId('agent-claude');

    fireEvent.paste(screen.getByTestId('new-session-input'), {
      clipboardData: { files: [new File(['fake-png-bytes'], 'shot.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(screen.getAllByTestId('new-session-thumb')).toHaveLength(1));

    fireEvent.click(screen.getByTestId('new-session-remove'));
    await waitFor(() => expect(screen.queryByTestId('new-session-thumb')).toBeNull());
  });
});

describe('NewSessionModal — 挑客户端', () => {
  it('候选来自服务端，不是写死的三个名字', async () => {
    open();
    expect((await screen.findByTestId('agent-claude')).textContent).toContain('Claude Code');
    expect(screen.getByTestId('agent-codex').textContent).toContain('Codex CLI');
  });

  it('用不了的那一家不摆在可挑的那一排里', async () => {
    open();
    await screen.findByTestId('agent-claude');
    expect(screen.queryByTestId('agent-ghost')).toBeNull();
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
    localStorage.setItem('frago-workbench-last-agent', 'ghost');
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

describe('NewSessionModal — 挑工作目录', () => {
  it('第一次用的人也有路可走：翻目录一层一层点进去', async () => {
    open();
    await screen.findByTestId('agent-claude');

    fireEvent.click(screen.getByTestId('toggle-browse-dirs'));
    expect(await screen.findByText('Repos')).toBeTruthy();

    // 停在哪一层就是选了哪一层，不必再点一次"就用这个"。
    fireEvent.click(screen.getByText('Repos'));
    await waitFor(() =>
      expect((screen.getByPlaceholderText('/absolute/path') as HTMLInputElement).value).toBe(
        '/Users/frago/Repos'
      )
    );
    expect(await screen.findByText('prod-rec-agent-service')).toBeTruthy();
  });

  it('子目录多的时候打字筛得动', async () => {
    open();
    await screen.findByTestId('agent-claude');
    fireEvent.click(screen.getByTestId('toggle-browse-dirs'));
    await screen.findByText('Repos');

    fireEvent.change(screen.getByTestId('browse-filter'), { target: { value: 'doc' } });
    expect(screen.getByText('Documents')).toBeTruthy();
    expect(screen.queryByText('Repos')).toBeNull();
  });

  it('翻到的那一层就是建会话时送出去的工作目录', async () => {
    open();
    await screen.findByTestId('agent-claude');
    fireEvent.click(screen.getByTestId('toggle-browse-dirs'));
    fireEvent.click(await screen.findByText('Repos'));
    await waitFor(() => expect(screen.getByText('frago')).toBeTruthy());
    fireEvent.click(screen.getByText('frago'));

    await fillFirstMessage();
    fireEvent.click(screen.getByText('创建'));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].cwd).toBe('/Users/frago/Repos/frago');
  });
});

describe('NewSessionModal — 敲 / 挑 skill（与详情输入区统一组件能力）', () => {
  it('输入框敲 / 弹出 skill 菜单，回车挑中变成顶部引用签并随创建请求送出', async () => {
    useDataStore.setState({
      skills: [
        {
          name: 'git-push',
          description: '智能分析改动并分组提交推送',
        },
        {
          name: 'frago-local-deploy',
          description: '构建前端并装机重启服务',
        },
      ] as never,
    });

    open();
    await screen.findByTestId('agent-claude');

    const input = screen.getByTestId('new-session-input') as HTMLTextAreaElement;
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '/git', selectionStart: 4 } });

    const menu = await screen.findByTestId('skill-menu');
    expect(menu.textContent).toContain('git-push');
    expect(menu.textContent).not.toContain('frago-local-deploy');

    fireEvent.keyDown(input, { key: 'Enter' });

    expect(screen.queryByTestId('skill-menu')).toBeNull();
    expect(input.value).toBe('');
    expect(screen.getByTestId('new-session-skills').textContent).toContain('/git-push');

    // 只挑了 skill、一个字没打也能创建，并将 skills 一并提交给后端
    fireEvent.click(screen.getByText('创建'));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].skills).toEqual(['git-push']);
  });
});

const EMPLOYEES = [
  {
    member_post_id: 'frago-developer',
    title: 'frago Developer',
    agent_kernel: 'codex',
    description: '负责 frago 仓库功能研发与质量守护。',
    work_scope: '负责 frago 仓库功能研发与质量守护。',
    cwd: '/Users/frago/repos/frago',
    knowledge_domains: ['frago-dev'],
    recipes: [],
    data_slots: ['~/.frago/data/frago-dev'],
    schedule_ids: [],
    active_session_ids: [],
    allowed_commands: [],
    skills: ['frago-local-deploy'],
    color: 'violet',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    data_summary: {
      slot_count: 1,
      entry_count: 4,
      slots: [{ slot_path: '~/.frago/data/frago-dev', exists: true, entry_count: 4 }],
    },
  },
  {
    member_post_id: 'stock',
    title: 'A 股双均线研究员',
    agent_kernel: 'claude',
    description: '盯盘、回测与调仓归档。',
    work_scope: '盯盘、回测与调仓归档。',
    cwd: '/Users/frago/.frago/data/stock',
    knowledge_domains: [],
    recipes: ['a_stock_dma'],
    data_slots: ['~/.frago/data/stock'],
    schedule_ids: [],
    active_session_ids: [],
    allowed_commands: [],
    skills: [],
    color: 'amber',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    data_summary: {
      slot_count: 1,
      entry_count: 2,
      slots: [{ slot_path: '~/.frago/data/stock', exists: true, entry_count: 2 }],
    },
  },
];

describe('NewSessionModal — 选择 Employee 创建员工会话（主入口）', () => {
  beforeEach(() => {
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/api/employees')) {
        return jsonResponse({ employees: EMPLOYEES });
      }
      if (u.includes('/api/employees/')) {
        const id = decodeURIComponent(u.split('/api/employees/')[1]);
        const emp = EMPLOYEES.find((e) => e.member_post_id === id) ?? EMPLOYEES[0];
        return jsonResponse({
          employee: emp,
          managed_data: {
            member_post_id: emp.member_post_id,
            data_slots: [
              {
                slot_path: emp.data_slots[0],
                resolved_path: emp.cwd,
                exists: true,
                total_count: emp.data_summary.entry_count,
                entries: [],
              },
            ],
            knowledge_domains: emp.knowledge_domains,
            recipes: emp.recipes,
          },
          business_context_block: `<frago-employee id="${emp.member_post_id}" title="${emp.title}">业务语境原文</frago-employee>`,
        });
      }
      if (u.endsWith('/api/workbench/agents')) {
        return jsonResponse({ agents: AGENTS, default: 'claude' });
      }
      if (u.endsWith('/api/workbench/sessions')) {
        const body = JSON.parse(String(init?.body ?? '{}'));
        posted.push(body);
        return jsonResponse({
          handle: 'emp-handle',
          agent: body.agent,
          display_name: body.agent,
          cwd: body.cwd,
          session_id: null,
          error: null,
          finished: false,
        });
      }
      throw new Error(`没料到的请求：${url}`);
    });
  });

  it('有员工编制时默认选中第一位员工，自动对齐内核、目录、预设 skill 并可展开预览业务语境', async () => {
    const onCreated = open();
    const devCard = await screen.findByTestId('new-session-employee-frago-developer');
    expect(devCard.getAttribute('aria-checked')).toBe('true');

    // 内核自动对齐到 frago-developer 的 codex，工作目录对齐到 /Users/frago/repos/frago
    await waitFor(() =>
      expect(screen.getByTestId('agent-codex').getAttribute('aria-checked')).toBe('true')
    );
    expect((screen.getByPlaceholderText('/absolute/path') as HTMLInputElement).value).toBe(
      '/Users/frago/repos/frago'
    );
    expect(screen.getByTestId('new-session-skills').textContent).toContain('/frago-local-deploy');

    // 可展开查看自动注入的业务语境块
    const ctxBtn = await screen.findByTestId('employee-context-toggle');
    fireEvent.click(ctxBtn);
    expect(await screen.findByText(/业务语境原文/)).toBeTruthy();

    await fillFirstMessage('检查当前状态');
    fireEvent.click(screen.getByText('创建'));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({
      agent: 'codex',
      cwd: '/Users/frago/repos/frago',
      text: '检查当前状态',
      skills: ['frago-local-deploy'],
      employee: 'frago-developer',
    });

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated.mock.calls[0][0]).toMatchObject({
      handle: 'emp-handle',
      employee_id: 'frago-developer',
      employee_title: 'frago Developer',
      employee_color: 'violet',
    });
  });

  it('可切换到「普通会话」以不带员工身份创建会话', async () => {
    open();
    await screen.findByTestId('new-session-employee-frago-developer');

    fireEvent.click(screen.getByTestId('new-session-employee-plain'));
    expect(screen.getByTestId('new-session-employee-plain').getAttribute('aria-checked')).toBe(
      'true'
    );
    expect(screen.queryByTestId('employee-context-toggle')).toBeNull();

    await fillFirstMessage('普通任务');
    fireEvent.click(screen.getByText('创建'));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].employee).toBeUndefined();
    expect(localStorage.getItem('frago-workbench-last-employee')).toBe('');
  });

  it('有 100 个员工时顶栏只露 3 个快捷胶囊 + 置顶普通会话，其余通过可搜索下拉面板瞬时定位', async () => {
    const hundredEmployees = Array.from({ length: 100 }, (_, i) => {
      const idx = String(i + 1).padStart(3, '0');
      return {
        ...EMPLOYEES[0],
        member_post_id: `emp-${idx}`,
        title: `专职员工 ${idx}`,
        description: `负责第 ${idx} 号业务线`,
      };
    });
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u.endsWith('/api/employees')) {
        return jsonResponse({ employees: hundredEmployees });
      }
      if (u.includes('/api/employees/')) {
        const id = decodeURIComponent(u.split('/api/employees/')[1]);
        const emp = hundredEmployees.find((e) => e.member_post_id === id) ?? hundredEmployees[0];
        return jsonResponse({
          employee: emp,
          managed_data: {
            member_post_id: emp.member_post_id,
            data_slots: [],
            knowledge_domains: [],
            recipes: [],
          },
          business_context_block: `<frago-employee id="${emp.member_post_id}">${emp.title}</frago-employee>`,
        });
      }
      if (u.endsWith('/api/workbench/agents')) {
        return jsonResponse({ agents: AGENTS, default: 'claude' });
      }
      if (u.endsWith('/api/workbench/sessions')) {
        const body = JSON.parse(String(init?.body ?? '{}'));
        posted.push(body);
        return jsonResponse({
          handle: 'emp-handle',
          agent: body.agent,
          display_name: body.agent,
          cwd: body.cwd,
          session_id: null,
          error: null,
          finished: false,
        });
      }
      throw new Error(`没料到的请求：${url}`);
    });

    open();
    const trigger = await screen.findByTestId('employee-picker-trigger');
    expect(trigger.textContent).toContain('全部 100 个');

    // 顶栏不会把第 88 号员工直接平铺出来撑爆页面
    expect(screen.queryByTestId('new-session-employee-emp-088')).toBeNull();
    // 「普通会话」始终置顶可见
    expect(screen.getByTestId('new-session-employee-plain')).toBeTruthy();

    // 打开可搜索下拉面板，输入 088 过滤并挑中第 88 号员工
    fireEvent.click(trigger);
    const searchInput = await screen.findByTestId('employee-picker-search');
    fireEvent.change(searchInput, { target: { value: '088' } });

    const item88 = await screen.findByTestId('picker-employee-emp-088');
    expect(screen.queryByTestId('picker-employee-emp-001')).toBeNull();
    fireEvent.click(item88);

    // 挑中后下拉收起，且第 88 号员工被提升到顶栏快捷胶囊第 1 位并处于选中态
    expect(screen.queryByTestId('employee-picker-popover')).toBeNull();
    const promoted = await screen.findByTestId('new-session-employee-emp-088');
    expect(promoted.getAttribute('aria-checked')).toBe('true');
  });

  it('在普通会话模式下于输入框敲 @ 选择员工：自动切回员工会话模式并在输入框顶部渲染 EmployeeQuote', async () => {
    open();
    await screen.findByTestId('new-session-employee-frago-developer');

    // 先切到普通会话模式
    fireEvent.click(screen.getByTestId('new-session-employee-plain'));
    expect(screen.getByTestId('new-session-employee-plain').getAttribute('aria-checked')).toBe(
      'true'
    );

    const input = screen.getByTestId('new-session-input') as HTMLTextAreaElement;
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '@sto', selectionStart: 4 } });

    const menu = await screen.findByTestId('employee-menu');
    expect(menu.getAttribute('data-directive-trigger')).toBe('@');
    expect(menu.textContent).toContain('A 股双均线研究员');

    fireEvent.keyDown(input, { key: 'Enter' });

    expect(screen.queryByTestId('employee-menu')).toBeNull();
    expect(input.value).toBe('');
    expect(screen.getByTestId('employee-quote').getAttribute('data-employee')).toBe('stock');
    expect(screen.getByTestId('new-session-employee-stock').getAttribute('aria-checked')).toBe(
      'true'
    );
  });
});
