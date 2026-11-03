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

/** 服务端那一套接口的假货。每个用例各自决定回什么。 */
function mockServer(handlers: {
  list?: () => Response;
  detail?: () => Response;
  createSession?: (body: unknown) => Response;
}) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/api/employees') && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(
        handlers.list?.() ??
          new Response(JSON.stringify({ employees: [makePost()], total: 1 }), { status: 200 })
      );
    }
    if (/\/api\/employees\/[^/]+$/.test(url) && (!init?.method || init.method === 'GET')) {
      return Promise.resolve(
        handlers.detail?.() ??
          new Response(
            JSON.stringify({
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
              business_context_block: '<frago-employee id="stock">…</frago-employee>',
            }),
            { status: 200 }
          )
      );
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
  usePageStore.setState({ currentPage: 'employees', workbenchSessionId: null });
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
});
