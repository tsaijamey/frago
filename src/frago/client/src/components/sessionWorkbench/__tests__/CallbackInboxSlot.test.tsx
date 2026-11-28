/**
 * CallbackInbox 前端组件与分轨约束单元测试。
 *
 * 覆盖：
 * 1. 空态（count === 0）隐藏且占高 0px（display: none）。
 * 2. 运行中态：单行轻提示可展开纯只读摘要抽屉，无输入/发送控件，且点击不抢占 Composer 焦点。
 * 3. 挂卡中态（blocked_reason === 'blocked_by_card' / holdingByCard）：仅单行低扰动提示，不可展开；
 *    决策卡内保持 0 条回执节点。
 * 4. Next Task 排队栏纯净性：仅渲染人类指令，过滤系统异步回执块。
 * 5. 左栏会话卡：callback_inbox.count > 0 时渲染低饱和中性胶囊「有 N 份新回执」，与琥珀「Waiting decision」区分层级。
 * 6. 中英双语 i18n 与 useCallbackInbox Hook 拉取/回退逻辑。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import type { CallbackInboxSummary } from '@/types/api';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { useCallbackInbox } from '@/hooks/useCallbackInbox';
import CallbackInboxSlot from '../CallbackInboxSlot';
import Composer from '../Composer';
import SessionItem from '../SessionItem';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';
const NOOP = () => {};

function makeInbox(overrides: Partial<CallbackInboxSummary> = {}): CallbackInboxSummary {
  return {
    count: 2,
    blocked_reason: null,
    items: [
      {
        job_id: 'disp-01',
        kind: 'worker',
        mode: 'new',
        target_session_id: 'worker-1',
        target_name: 'worker-ui-audit',
        employee_id: 'qa',
        task_summary: '已完成 Light/Dark 双主题 4 边闭合边框静态检查。',
        exit_code: 0,
        delivery_state: 'queued',
        worker_finished_at: '2026-11-27T14:38:00Z',
        updated_at: '2026-11-27T14:38:00Z',
      },
      {
        job_id: 'disp-02',
        kind: 'employee',
        mode: 'ask',
        target_session_id: 'emp-2',
        target_name: 'worker-queue-trace',
        employee_id: null,
        task_summary: 'Next Task 持久化队列不包含异步回执条目。',
        exit_code: 0,
        delivery_state: 'delivering',
        worker_finished_at: '2026-11-27T14:39:00Z',
        updated_at: '2026-11-27T14:39:00Z',
      },
    ],
    ...overrides,
  };
}

function makeSession(overrides: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: SID,
    family: 'claude-code',
    title: '异步回执测试会话',
    directory: '/Users/frago/Repos/frago',
    created_at: 1_700_000_000_000,
    last_active_at: 1_700_000_100_000,
    last_reply_at: 1_700_000_100_000,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...overrides,
  };
}

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

beforeEach(async () => {
  await i18n.changeLanguage('zh');
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ sid: SID, count: 0, blocked_reason: null, items: [] }),
    }))
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('CallbackInboxSlot', () => {
  it('空态（count === 0 或 null）完全隐藏且零占高（display: none）', () => {
    const { rerender } = render(
      <CallbackInboxSlot inbox={{ count: 0, blocked_reason: null, items: [] }} />
    );
    const emptySlot = screen.getByTestId('callback-inbox-slot');
    expect(emptySlot.getAttribute('data-count')).toBe('0');
    expect(emptySlot.className).toContain('is-empty');
    expect(getComputedStyle(emptySlot).display).toBe('none');
    expect(screen.queryByTestId('callback-inbox-bar')).toBeNull();
    expect(screen.queryByTestId('callback-inbox-drawer')).toBeNull();

    rerender(<CallbackInboxSlot inbox={null} />);
    expect(getComputedStyle(screen.getByTestId('callback-inbox-slot')).display).toBe('none');
  });

  it('运行中态：展示单行提示，点击展开纯只读摘要抽屉且无编辑/发送控件', () => {
    const inbox = makeInbox();
    render(<CallbackInboxSlot inbox={inbox} />);

    const slot = screen.getByTestId('callback-inbox-slot');
    expect(slot.getAttribute('data-mode')).toBe('running');
    expect(slot.getAttribute('data-count')).toBe('2');

    const bar = screen.getByTestId('callback-inbox-bar');
    expect(bar.getAttribute('data-state')).toBe('running');
    expect(bar.getAttribute('aria-expanded')).toBe('false');
    expect(bar.textContent).toContain('2 份后台回执已收齐，本轮结束后自动并入');
    expect(bar.textContent).toContain('查看只读摘要');

    fireEvent.click(bar);
    expect(bar.getAttribute('aria-expanded')).toBe('true');

    const drawer = screen.getByTestId('callback-inbox-drawer');
    expect(drawer.textContent).toContain('待消化后台回执摘要（2 份）');
    expect(drawer.textContent).toContain('纯只读 · 本轮结束后自动并入');
    expect(drawer.textContent).toContain('qa · worker-ui-audit');
    expect(drawer.textContent).toContain('已完成 Light/Dark 双主题 4 边闭合边框静态检查。');
    expect(drawer.textContent).toContain('worker-queue-trace');
    expect(drawer.textContent).toContain('投递中');

    // 抽屉内部严禁存在输入框、文本域或发送按钮
    expect(drawer.querySelectorAll('input, textarea, select')).toHaveLength(0);
    const drawerButtons = Array.from(drawer.querySelectorAll('button'));
    expect(drawerButtons).toHaveLength(1);
    expect(drawerButtons[0].getAttribute('data-testid')).toBe('callback-inbox-collapse');

    // 点击收起按钮关闭抽屉
    fireEvent.click(screen.getByTestId('callback-inbox-collapse'));
    expect(screen.queryByTestId('callback-inbox-drawer')).toBeNull();
  });

  it('挂卡中态（blocked_reason === blocked_by_card 或 holdingByCard）：单行低扰动提示且不可展开', () => {
    const inbox = makeInbox({ blocked_reason: 'blocked_by_card' });
    const { rerender } = render(<CallbackInboxSlot inbox={inbox} />);

    const slot = screen.getByTestId('callback-inbox-slot');
    expect(slot.getAttribute('data-mode')).toBe('holding');

    const bar = screen.getByTestId('callback-inbox-bar');
    expect(bar.getAttribute('data-state')).toBe('holding');
    expect(bar.tagName).toBe('DIV');
    expect(bar.textContent).toContain('另有 2 份后台回执已就绪，拍板后自动汇总');
    expect(bar.textContent).toContain('等待上方决策卡拍板');

    fireEvent.click(bar);
    expect(screen.queryByTestId('callback-inbox-drawer')).toBeNull();

    // 当 blocked_reason 为 null 但页面检测到待拍板卡（holdingByCard=true）时同样进入 holding
    rerender(<CallbackInboxSlot inbox={makeInbox({ blocked_reason: null })} holdingByCard />);
    expect(screen.getByTestId('callback-inbox-bar').getAttribute('data-state')).toBe('holding');
  });

  it('英文语言下完整切换文案，零硬编码中文', async () => {
    await i18n.changeLanguage('en');
    render(<CallbackInboxSlot inbox={makeInbox()} />);
    const bar = screen.getByTestId('callback-inbox-bar');
    expect(bar.textContent).toContain('2 background receipt(s) ready');
    expect(bar.textContent).toContain('View read-only summary');
    fireEvent.click(bar);
    expect(screen.getByTestId('callback-inbox-drawer').textContent).toContain(
      'Pending background receipts (2)'
    );
  });
});

describe('Composer 焦点保留与 Next Task 队列纯净性', () => {
  it('展开与收起回执抽屉不抢占 composer-input 焦点，且不阻塞主发送按钮', () => {
    render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        callbackInbox={makeInbox()}
      />
    );

    const input = screen.getByTestId('composer-input') as HTMLTextAreaElement;
    act(() => {
      input.focus();
    });
    fireEvent.change(input, { target: { value: '继续当前人类指令' } });
    expect(document.activeElement).toBe(input);

    const sendBtn = screen.getByTestId('composer-send') as HTMLButtonElement;
    expect(sendBtn.disabled).toBe(false);

    const bar = screen.getByTestId('callback-inbox-bar');
    fireEvent.mouseDown(bar);
    fireEvent.click(bar);
    expect(screen.getByTestId('callback-inbox-drawer')).toBeTruthy();
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe('继续当前人类指令');
    expect(sendBtn.disabled).toBe(false);

    const collapseBtn = screen.getByTestId('callback-inbox-collapse');
    fireEvent.mouseDown(collapseBtn);
    fireEvent.click(collapseBtn);
    expect(screen.queryByTestId('callback-inbox-drawer')).toBeNull();
    expect(document.activeElement).toBe(input);
    expect(sendBtn.disabled).toBe(false);
  });

  it('Next Task 排队栏仅渲染人类指令，彻底过滤系统异步回执块', () => {
    render(
      <Composer
        sessionId={SID}
        family="claude-code"
        onSent={NOOP}
        queueItems={[
          {
            id: 'q-human-1',
            text: '人类指令：先合并 PR 再回归测试',
            skills: [],
            attachments: 0,
            created_at: 1000,
          },
          {
            id: 'q-sys-cb',
            text: '<frago-async-callback kind="worker" job_id="disp-1" target_session_id="w-1">交付内容</frago-async-callback>',
            skills: [],
            attachments: 0,
            created_at: 1001,
          },
          {
            id: 'q-sys-batch',
            text: '<frago-async-callbacks count="2">摘要</frago-async-callbacks>',
            skills: [],
            attachments: 0,
            created_at: 1002,
          },
        ]}
      />
    );

    const queueBar = screen.getByTestId('session-message-queue');
    expect(queueBar.getAttribute('data-system-callback-count')).toBe('0');
    const items = screen.getAllByTestId('session-queue-item');
    expect(items).toHaveLength(1);
    expect(items[0].getAttribute('data-task-kind')).toBe('human');
    expect(items[0].textContent).toContain('人类指令：先合并 PR 再回归测试');
    expect(queueBar.textContent).not.toContain('frago-async-callback');
  });
});

describe('SessionItem 左侧会话栏低饱和回执角标', () => {
  it('后台/已结束会话有 callback_inbox.count > 0 时渲染低饱和中性胶囊「有 N 份新回执」，与琥珀「Waiting decision」区分层级', () => {
    const cbSession = makeSession({
      session_id: 's-bg-cb',
      title: '后台跑完带回执的会话',
      status: 'done',
      need_decision: false,
      callback_inbox: makeInbox({ count: 3 }),
    });
    const waitSession = makeSession({
      session_id: 's-wait',
      title: '等待人类拍板会话',
      status: 'done',
      need_decision: true,
    });

    render(
      <>
        <SessionItem
          session={cbSession}
          selected={false}
          copied={false}
          callbackQueued
          callbackCount={3}
          onSelect={NOOP}
          onCopy={NOOP}
        />
        <SessionItem
          session={waitSession}
          selected={false}
          copied={false}
          onSelect={NOOP}
          onCopy={NOOP}
        />
      </>
    );

    const badges = screen.getAllByTestId('session-lifecycle');
    const cbBadge = badges.find((el) => el.getAttribute('data-lifecycle') === 'callback')!;
    const waitBadge = badges.find((el) => el.getAttribute('data-lifecycle') === 'waiting')!;

    expect(cbBadge.textContent).toContain('有 3 份新回执');
    expect(cbBadge.className).toContain('text-text-muted');
    expect(cbBadge.className).toContain('font-normal');
    expect(cbBadge.className).toContain('bg-bg-hover');
    expect(cbBadge.className).not.toContain('text-accent-warning');

    expect(waitBadge.textContent).toContain('Waiting decision');
    expect(waitBadge.className).toContain('text-accent-warning');
    expect(waitBadge.className).toContain('font-semibold');
  });

  it('运行中会话同时带有未消化回执时保留 Running 主态并附带低饱和回执胶囊', () => {
    const runningWithCb = makeSession({
      session_id: 's-run-cb',
      status: 'running',
      callback_inbox: makeInbox({ count: 2 }),
    });

    render(
      <SessionItem
        session={runningWithCb}
        selected={false}
        copied={false}
        callbackQueued
        callbackCount={2}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );

    expect(screen.getByTestId('session-lifecycle').textContent).toContain('Running');
    const extraBadge = screen.getByTestId('session-callback-badge');
    expect(extraBadge.textContent).toContain('有 2 份新回执');
    expect(extraBadge.className).toContain('text-text-muted');
  });

  it('P0-4：同时持有未回答决策卡（Tier 2）与待投递回执（Tier 3）时主态保持琥珀 Waiting decision，回执仅作次级低饱和副提示', () => {
    const waitingWithCb = makeSession({
      session_id: 's-wait-cb',
      title: '既待决策又有回执',
      status: 'done',
      need_decision: true,
      callback_inbox: makeInbox({ count: 2 }),
    });

    render(
      <SessionItem
        session={waitingWithCb}
        selected={false}
        copied={false}
        card="请先确认发布方案"
        callbackQueued
        callbackCount={2}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );

    const primaryBadge = screen.getByTestId('session-lifecycle');
    expect(primaryBadge.getAttribute('data-lifecycle')).toBe('waiting');
    expect(primaryBadge.textContent).toContain('Waiting decision');
    expect(primaryBadge.className).toContain('text-accent-warning');
    expect(primaryBadge.className).toContain('font-semibold');

    const secondaryBadge = screen.getByTestId('session-callback-badge');
    expect(secondaryBadge.textContent).toContain('有 2 份新回执');
    expect(secondaryBadge.className).toContain('text-text-muted');
  });
});

describe('useCallbackInbox Hook', () => {
  it('拉取接口数据，失败时优雅回退 initialSummary', async () => {
    const mockFetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        sid: SID,
        count: 1,
        blocked_reason: 'blocked_by_card',
        items: makeInbox({ count: 1 }).items.slice(0, 1),
      }),
    }));
    vi.stubGlobal('fetch', mockFetch);

    function Harness({ sid, initial }: { sid: string | null; initial?: CallbackInboxSummary | null }) {
      const { inbox } = useCallbackInbox(sid, initial);
      return (
        <div
          data-testid="hook-out"
          data-count={inbox.count}
          data-blocked={inbox.blocked_reason ?? ''}
        />
      );
    }

    const { rerender } = render(<Harness sid={SID} />);
    await waitFor(() => {
      expect(screen.getByTestId('hook-out').getAttribute('data-count')).toBe('1');
      expect(screen.getByTestId('hook-out').getAttribute('data-blocked')).toBe('blocked_by_card');
    });

    // 接口失败时回退到 initialSummary
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network error');
      })
    );
    rerender(<Harness sid="other-sid" initial={makeInbox({ count: 2 })} />);
    await waitFor(() => {
      expect(screen.getByTestId('hook-out').getAttribute('data-count')).toBe('2');
    });
  });
});
