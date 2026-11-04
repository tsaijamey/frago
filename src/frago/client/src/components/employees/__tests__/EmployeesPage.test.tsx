/**
 * 员工页的用例。守的是这一页对外的三条承诺，不是它长什么样：
 *
 * 1. 一张卡片表面只有缩写、名字、一行摘要、编辑按钮——岗位说明与目录清单不许漏到卡片上；
 * 2. 整卡点下去是起会话，铅笔点下去是详情，两者不互相触发；
 * 3. 起会话时交上去的那一份请求里带着这个员工的编号（服务端据此拼业务语境）。
 */

import { beforeEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import EmployeesPage from '../EmployeesPage';
import i18n from '@/i18n';
import { usePageStore } from '@/stores/pageStore';
import type { EmployeePost } from '@/hooks/useEmployees';

// 断言写的是中文界面上的话（页头、摘要、报错），所以先把语言钉在中文：i18n 的默认语言
// 是英文，不切的话这些用例验的是一套没人看见的文案。
beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

/** 一份够用的员工编制。字段照服务端的 `EmployeePostRecord` 对齐。 */
function makePost(over: Partial<EmployeePost> = {}): EmployeePost {
  return {
    member_post_id: 'stock',
    title: 'Stock 投研与策略专员',
    agent_kernel: 'claude',
    description: '专门负责股票与 ETF 全场景投研工作。涵盖日常对答、标的调研、策略回测。',
    work_scope: '这一段是几百字的岗位说明，卡片上 NEVER 出现它。'.repeat(8),
    cwd: '/Users/frago/Repos/frago',
    knowledge_domains: ['etf-research'],
    recipes: ['cn_stock_data_feed'],
    data_slots: ['~/.frago/data/stock'],
    schedule_ids: [],
    active_session_ids: [],
    allowed_commands: [],
    created_at: '',
    updated_at: '',
    data_summary: {
      slot_count: 1,
      entry_count: 3,
      slots: [{ slot_path: '~/.frago/data/stock', exists: true, entry_count: 3 }],
    },
    ...over,
  };
}

/** 一份够用的详情：编制、领地索引、账本（含明细）、可补绑的候选。 */
function makeDetail(over: Record<string, unknown> = {}) {
  return {
    employee: makePost(),
    managed_data: {
      member_post_id: 'stock',
      data_slots: [
        {
          slot_path: '~/.frago/data/stock',
          resolved_path: '/Users/frago/.frago/data/stock',
          exists: true,
          total_count: 3,
          entries: [{ name: '20261101-signal-review', summary: '', file_count: 2 }],
        },
      ],
      knowledge_domains: ['etf-research'],
      recipes: ['cn_stock_data_feed'],
    },
    ledger: {
      member_post_id: 'stock',
      updated_at: '2026-11-03T10:00:00',
      last_synced_at: '2026-11-03T10:00:00',
      claimed_resources: {
        data_slots: ['~/.frago/data/stock'],
        recipe_count: 1,
        knowledge_domain_count: 1,
        matched_session_count: 2,
      },
      claimed_details: {
        data_slots: [
          {
            path: '~/.frago/data/stock',
            name: 'stock',
            discovered_by: 'entry_summary',
            evidence: '讲的是 ETF 择时信号',
          },
        ],
        recipes: [{ name: 'cn_stock_data_feed', display_title: 'A 股数据源', description: '拉行情' }],
        knowledge_domains: [{ name: 'etf-research', purpose: 'ETF 研究方法', doc_count: 4 }],
        matched_sessions: [
          { session_id: 's1', title: 'DMA 信号复盘' },
          { session_id: 's2', title: 'ETF 波动率调研' },
        ],
        glossary: [{ term: 'DMA', meaning: '双均线指标' }],
      },
    },
    available_resources: {
      data_slots: [
        { path: '~/.frago/data/stock', name: 'stock' },
        { path: '~/.frago/data/family-health', name: 'family-health' },
      ],
      knowledge_domains: [
        { name: 'etf-research', purpose: 'ETF 研究方法' },
        { name: 'family-health', purpose: '家庭健康' },
      ],
      recipes: [
        { name: 'cn_stock_data_feed', display_title: 'A 股数据源', description: '拉行情' },
        { name: 'relationship_board', display_title: '关系看板', description: '人际往来' },
      ],
    },
    business_context_block: '<frago-employee id="stock">…</frago-employee>',
    ...over,
  };
}

/** 服务端那一套接口的假货。每个用例各自决定回什么。 */
function mockServer(handlers: {
  list?: () => Response;
  detail?: () => Response;
  create?: (body: unknown) => Response;
  update?: (body: unknown) => Response;
  sync?: () => Response;
  createSession?: (body: unknown) => Response;
}) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/sync-ledger')) {
      return Promise.resolve(handlers.sync?.() ?? new Response(JSON.stringify({ added: 0 }), { status: 200 }));
    }
    if (url.endsWith('/api/employees') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return Promise.resolve(handlers.create?.(body) ?? new Response(JSON.stringify(makePost()), { status: 201 }));
    }
    if (/\/api\/employees\/[^/]+$/.test(url) && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body));
      return Promise.resolve(handlers.update?.(body) ?? new Response(JSON.stringify(makePost()), { status: 200 }));
    }
    if (url.endsWith('/api/employees') && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(
        handlers.list?.() ??
          new Response(JSON.stringify({ employees: [makePost()], total: 1 }), { status: 200 })
      );
    }
    if (/\/api\/employees\/[^/]+$/.test(url) && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(handlers.detail?.() ?? new Response(JSON.stringify(makeDetail()), { status: 200 }));
    }
    if (url.endsWith('/api/workbench/agents')) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            agents: [
              {
                agent_type: 'claude',
                display_name: 'Claude Code',
                installed: true,
                path: '/usr/local/bin/claude',
                family: 'claude-code',
                selectable: true,
                reason: null,
                id_origin: 'caller',
              },
            ],
            default: 'claude',
          }),
          { status: 200 }
        )
      );
    }
    if (url.endsWith('/api/workbench/sessions') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      return Promise.resolve(
        handlers.createSession?.(body) ??
          new Response(
            JSON.stringify({
              handle: 'h1',
              agent: body.agent,
              display_name: 'Claude Code',
              cwd: body.cwd,
              session_id: 'sid-1',
              error: null,
              finished: false,
            }),
            { status: 201 }
          )
      );
    }
    return Promise.resolve(new Response('{}', { status: 404 }));
  });
}

beforeEach(() => {
  usePageStore.setState({
    currentPage: 'employees',
    workbenchSessionId: null,
    pendingWorkbenchLaunch: null,
  });
});

describe('员工页', () => {
  it('卡片表面只有名字与一行摘要，岗位说明与目录清单不上卡片', async () => {
    vi.stubGlobal('fetch', mockServer({}));
    const { container } = render(<EmployeesPage />);

    expect(await screen.findByText('Stock 投研与策略专员')).toBeTruthy();
    // 摘要取 description 的第一句，止于第一个句号。
    expect(screen.getByText('专门负责股票与 ETF 全场景投研工作')).toBeTruthy();
    // 岗位说明原文一个字都不许出现在卡片区。
    expect(container.textContent).not.toContain('这一段是几百字的岗位说明');
    // 纳管目录也不在卡片上。
    expect(container.textContent).not.toContain('~/.frago/data/stock');
    vi.unstubAllGlobals();
  });

  it('整卡点下去开起会话弹窗，铅笔点下去开详情弹窗，两件事不互相触发', async () => {
    vi.stubGlobal('fetch', mockServer({}));
    render(<EmployeesPage />);
    const card = await screen.findByTestId('employee-card-stock');

    fireEvent.click(card);
    expect(await screen.findByTestId('employee-start-session')).toBeTruthy();
    // 起会话那个窗开着时，详情窗不该也冒出来。
    expect(screen.queryByTestId('employee-save')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    fireEvent.click(screen.getByRole('button', { name: '员工详情 Stock 投研与策略专员' }));
    expect(await screen.findByTestId('employee-save')).toBeTruthy();
    expect(screen.queryByTestId('employee-start-session')).toBeNull();
    vi.unstubAllGlobals();
  });

  it('起会话时把员工编号交上去，编号当场就有的直接切进那一场', async () => {
    const seen: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      mockServer({
        createSession: (body) => {
          seen.push(body);
          return new Response(
            JSON.stringify({
              handle: 'h1',
              agent: 'claude',
              display_name: 'Claude Code',
              cwd: '/Users/frago/Repos/frago',
              session_id: 'sid-1',
              error: null,
              finished: false,
            }),
            { status: 201 }
          );
        },
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));
    fireEvent.change(await screen.findByLabelText('想让他做什么'), {
      target: { value: '看看最近的 DMA 信号' },
    });
    fireEvent.click(screen.getByTestId('employee-start-session'));

    await waitFor(() => {
      expect(usePageStore.getState().workbenchSessionId).toBe('sid-1');
    });
    expect(usePageStore.getState().currentPage).toBe('session_workbench');
    expect(seen[0]).toMatchObject({
      agent: 'claude',
      text: '看看最近的 DMA 信号',
      employee: 'stock',
    });
    vi.unstubAllGlobals();
  });

  it('一个字没打、只粘一张截图也起得来，图跟着请求一起发出去', async () => {
    const seen: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      mockServer({
        createSession: (body) => {
          seen.push(body);
          return new Response(
            JSON.stringify({
              handle: 'h1',
              agent: 'claude',
              display_name: 'Claude Code',
              cwd: '/Users/frago/Repos/frago',
              session_id: 'sid-1',
              error: null,
              finished: false,
            }),
            { status: 201 }
          );
        },
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));

    const start = (await screen.findByTestId('employee-start-session')) as HTMLButtonElement;
    // 人截了张图想说"看这个"，一个字没打时按钮得是灰的——先确认它确实灰着。
    expect(start.disabled).toBe(true);

    fireEvent.paste(await screen.findByLabelText('想让他做什么'), {
      clipboardData: { files: [new File(['fake-png-bytes'], 'shot.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(screen.getAllByTestId('employee-launch-thumb')).toHaveLength(1));

    await waitFor(() => expect(start.disabled).toBe(false));
    fireEvent.click(start);

    await waitFor(() => {
      expect(usePageStore.getState().workbenchSessionId).toBe('sid-1');
    });
    expect(seen[0]).toMatchObject({ employee: 'stock', text: '' });
    const images = (seen[0] as { images?: string[] }).images ?? [];
    expect(images.length).toBeGreaterThan(0);
    expect(images[0]).toContain('base64');
    vi.unstubAllGlobals();
  });

  it('剪贴板走 items 载体或在弹窗容器内粘贴截图时，同样能贴入附件并发送', async () => {
    vi.stubGlobal('fetch', mockServer({}));
    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));

    const toggle = await screen.findByTestId('employee-context-toggle');
    const png = new File(['fake-png-bytes'], 'clipboard-item.png', { type: 'image/png' });
    fireEvent.paste(toggle, {
      clipboardData: {
        files: [],
        items: [{ kind: 'file', type: 'image/png', getAsFile: () => png }],
      },
    });

    await waitFor(() => expect(screen.getAllByTestId('employee-launch-thumb')).toHaveLength(1));
    vi.unstubAllGlobals();
  });

  it('认领型内核（agy / codex）点开始后立即转交会话工作台启动面板，不在弹窗内阻塞苦等', async () => {
    vi.stubGlobal(
      'fetch',
      mockServer({
        createSession: () =>
          new Response(
            JSON.stringify({
              handle: 'webui-agy-1',
              agent: 'agy',
              display_name: 'Antigravity CLI',
              cwd: '/Users/frago/.frago',
              session_id: null,
              error: null,
              finished: false,
            }),
            { status: 201 }
          ),
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));
    fireEvent.change(await screen.findByLabelText('想让他做什么'), {
      target: { value: '帮我查一下体检报告' },
    });
    fireEvent.click(screen.getByTestId('employee-start-session'));

    await waitFor(() => {
      expect(usePageStore.getState().currentPage).toBe('session_workbench');
    });
    expect(usePageStore.getState().workbenchSessionId).toBeNull();
    expect(usePageStore.getState().pendingWorkbenchLaunch).toMatchObject({
      launch: {
        handle: 'webui-agy-1',
        agent: 'agy',
        display_name: 'Antigravity CLI',
        session_id: null,
      },
      text: '帮我查一下体检报告',
    });
    vi.unstubAllGlobals();
  });

  it('岗位配了目录时，这一栏开窗就带着它，人也能改成别处', async () => {
    const seen: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      mockServer({
        createSession: (body) => {
          seen.push(body);
          return new Response(
            JSON.stringify({
              handle: 'h1',
              agent: 'claude',
              display_name: 'Claude Code',
              cwd: '/tmp/elsewhere',
              session_id: 'sid-1',
              error: null,
              finished: false,
            }),
            { status: 201 }
          );
        },
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));

    const folder = (await screen.findByLabelText('在哪个目录里干活')) as HTMLInputElement;
    expect(folder.value).toBe('/Users/frago/Repos/frago');

    fireEvent.change(folder, { target: { value: '/tmp/elsewhere' } });
    fireEvent.change(screen.getByLabelText('想让他做什么'), {
      target: { value: '换个目录干活' },
    });
    fireEvent.click(screen.getByTestId('employee-start-session'));

    await waitFor(() => {
      expect(seen[0]).toMatchObject({ cwd: '/tmp/elsewhere', employee: 'stock' });
    });
    vi.unstubAllGlobals();
  });

  it('岗位没配目录时这一栏带着 frago 家目录，点开就能起', async () => {
    const seen: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      mockServer({
        list: () =>
          new Response(JSON.stringify({ employees: [makePost({ cwd: '' })], total: 1 }), {
            status: 200,
          }),
        detail: () =>
          new Response(
            JSON.stringify({
              employee: makePost({ cwd: '' }),
              managed_data: {
                member_post_id: 'stock',
                data_slots: [],
                knowledge_domains: [],
                recipes: [],
              },
              business_context_block: '',
            }),
            { status: 200 }
          ),
        createSession: (body) => {
          seen.push(body);
          return new Response(
            JSON.stringify({
              handle: 'h1',
              agent: 'claude',
              display_name: 'Claude Code',
              cwd: '/Users/frago/.frago',
              session_id: 'sid-1',
              error: null,
              finished: false,
            }),
            { status: 201 }
          );
        },
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));

    // 从前这一档底下写的是一句"这个岗位没配目录，这一栏必须填"，人点卡片起会话先撞上一句
    // 要他去填的话——而这一栏本来就该有默认值。
    const folder = (await screen.findByLabelText('在哪个目录里干活')) as HTMLInputElement;
    expect(folder.value).toBe('~/.frago');
    expect(screen.queryByText(/这一栏必须填/)).toBeNull();

    fireEvent.change(screen.getByLabelText('想让他做什么'), { target: { value: '干活' } });
    fireEvent.click(screen.getByTestId('employee-start-session'));

    await waitFor(() => {
      expect(seen[0]).toMatchObject({ cwd: '~/.frago', employee: 'stock' });
    });
    vi.unstubAllGlobals();
  });

  it('人清空这一栏不是错，底下改成说它会用哪个目录', async () => {
    vi.stubGlobal('fetch', mockServer({}));
    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));

    const folder = (await screen.findByLabelText('在哪个目录里干活')) as HTMLInputElement;
    fireEvent.change(folder, { target: { value: '' } });

    expect(await screen.findByText('留空，用 ~/Repos/frago')).toBeTruthy();
    expect(screen.queryByText(/必须填/)).toBeNull();
    vi.unstubAllGlobals();
  });

  it('语境预览平时收着一行摘要，点开才把服务端拼的那段原文摆出来', async () => {
    vi.stubGlobal('fetch', mockServer({}));
    render(<EmployeesPage />);
    fireEvent.click(await screen.findByTestId('employee-card-stock'));

    const toggle = await screen.findByTestId('employee-context-toggle');
    expect(toggle.textContent).toContain('1 个数据目录');
    expect(screen.queryByText(/frago-employee/)).toBeNull();

    fireEvent.click(toggle);
    expect(await screen.findByText(/frago-employee/)).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it('清单取不到时明说取不到，不摆一张空清单', async () => {
    vi.stubGlobal(
      'fetch',
      mockServer({
        list: () => new Response(JSON.stringify({ detail: '服务没起来' }), { status: 503 }),
      })
    );
    render(<EmployeesPage />);

    expect(await screen.findByText(/员工清单取不到/)).toBeTruthy();
    // 「还没有员工」这句话不许出现：真相是没问着，不是本机没有岗位。
    expect(screen.queryByText('还没有员工')).toBeNull();
    vi.unstubAllGlobals();
  });

  it('新建员工只问岗位本身：默认目录预填家目录，资源栏不出现', async () => {
    vi.stubGlobal('fetch', mockServer({}));
    render(<EmployeesPage />);

    fireEvent.click(await screen.findByRole('button', { name: '新建员工' }));

    // 默认工作目录预填家目录：这一栏留空本来就等价于用它。
    const cwd = (await screen.findByLabelText('默认工作目录')) as HTMLInputElement;
    expect(cwd.value).toBe('~/.frago');

    // 员工还没查过，问人等于让人替它猜——三栏一个都不出现。
    expect(screen.queryByLabelText('纳管的数据目录')).toBeNull();
    expect(screen.queryByLabelText('知识域')).toBeNull();
    expect(screen.queryByLabelText('配方')).toBeNull();
    expect(
      screen.getByText(/创建后员工会自动在 ~\/\.frago 下巡检并认领/)
    ).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it('新建提交后当场切进详情，把刚巡检认下的资源摆出来', async () => {
    // 服务端返回编制之前已经跑完首次巡检，并把认领结果反哺回编制——所以这份编制里就带着
    // 刚认下的目录、知识域与配方，弹窗切到详情态时摆的就是它。
    const created = makePost({
      member_post_id: 'assistant',
      title: '个人助理',
      data_slots: ['~/.frago/data/family-health'],
      knowledge_domains: ['family-health'],
      recipes: ['relationship_board'],
    });
    vi.stubGlobal(
      'fetch',
      mockServer({
        create: () => new Response(JSON.stringify(created), { status: 201 }),
        detail: () =>
          new Response(
            JSON.stringify(
              makeDetail({
                employee: created,
                ledger: {
                  member_post_id: 'assistant',
                  updated_at: '2026-11-03T10:00:00',
                  last_synced_at: '2026-11-03T10:00:00',
                  claimed_resources: {
                    data_slots: ['~/.frago/data/family-health'],
                    recipe_count: 1,
                    knowledge_domain_count: 1,
                    matched_session_count: 0,
                  },
                  claimed_details: {
                    data_slots: [{ path: '~/.frago/data/family-health', name: 'family-health' }],
                    recipes: [{ name: 'relationship_board', display_title: '关系看板' }],
                    knowledge_domains: [{ name: 'family-health', purpose: '家庭健康' }],
                    matched_sessions: [],
                    glossary: [],
                  },
                },
              })
            ),
            { status: 200 }
          ),
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByRole('button', { name: '新建员工' }));
    fireEvent.change(await screen.findByLabelText('编号'), { target: { value: 'assistant' } });
    fireEvent.change(screen.getByLabelText('岗位名称'), { target: { value: '个人助理' } });
    fireEvent.click(screen.getByTestId('employee-save'));

    // 建完不是留一句「接着去配」——服务端返回前已经巡检过，当场把认下的东西摆出来。
    expect(await screen.findByText(/岗位已建立并完成首次自动巡检/)).toBeTruthy();
    expect(await screen.findByTestId('employee-chip-slot-~/.frago/data/family-health')).toBeTruthy();
    expect(screen.getByTestId('employee-chip-domain-family-health')).toBeTruthy();
    expect(screen.getByTestId('employee-chip-recipe-relationship_board')).toBeTruthy();
    // 切到详情态之后，三栏的手填框该在（它们现在用来补不在下拉里的条目）。
    expect(screen.getByLabelText('知识域')).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it('详情里点 × 能剔掉误认领的一项，保存时就不再交上去', async () => {
    const seen: unknown[] = [];
    vi.stubGlobal(
      'fetch',
      mockServer({
        update: (body) => {
          seen.push(body);
          return new Response(JSON.stringify(makePost()), { status: 200 });
        },
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByRole('button', { name: '员工详情 Stock 投研与策略专员' }));

    expect(await screen.findByTestId('employee-chip-recipe-cn_stock_data_feed')).toBeTruthy();
    fireEvent.click(screen.getByTestId('employee-chip-recipe-cn_stock_data_feed-remove'));
    expect(screen.queryByTestId('employee-chip-recipe-cn_stock_data_feed')).toBeNull();
    // 剔掉的那一栏空了要说「暂未认领」，不是留一片空白让人以为界面坏了。
    expect(screen.getByText('暂未认领配方。')).toBeTruthy();

    fireEvent.click(screen.getByTestId('employee-save'));
    await waitFor(() => {
      expect(seen[0]).toMatchObject({ recipes: [] });
    });
    // 另外两栏没动过，照原样交上去。
    expect(seen[0]).toMatchObject({ knowledge_domains: ['etf-research'] });
    vi.unstubAllGlobals();
  });

  it('点重新巡检走 sync-ledger 的 full 路，回来把认领结果刷新一遍', async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        calls.push(`${init?.method ?? 'GET'} ${url}`);
        return mockServer({})(input, init);
      })
    );

    render(<EmployeesPage />);
    fireEvent.click(await screen.findByRole('button', { name: '员工详情 Stock 投研与策略专员' }));
    fireEvent.click(await screen.findByTestId('employee-sync-ledger'));

    await waitFor(() => {
      expect(calls.some((c) => c === 'POST /api/employees/stock/sync-ledger?full=true')).toBe(true);
    });
    // 巡检完要重取详情，人才看得见这一趟到底认下了什么。
    await waitFor(() => {
      expect(calls.filter((c) => c === 'GET /api/employees/stock').length).toBeGreaterThan(1);
    });
    expect(await screen.findByText('巡检完成，认领结果已更新。')).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
