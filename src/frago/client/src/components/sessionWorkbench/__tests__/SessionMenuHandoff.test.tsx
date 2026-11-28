/**
 * 页头「…」二级菜单中的「交接到新会话」入口。
 *
 * 钉住：
 * 1. 普通空闲会话、运行中会话、无上下文水位/低上下文会话均可随时触发交接，不再受阈值或忙态禁用；
 * 2. 点击交接项会回调 `onHandoff(session)` 并收起菜单；
 * 3. 交接进行中（`handingOff=true`）置灰防重复点击并切换文案为「交接中」；
 * 4. 未传 `onHandoff`（如左栏会话卡菜单）时不渲染该项，不影响原有分段结构；
 * 5. 中英文双语文案正确。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import SessionMenu from '../SessionMenu';
import i18n from '@/i18n';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

function makeSession(over: Partial<WorkbenchSession> = {}): WorkbenchSession {
  return {
    session_id: SID,
    family: 'claude-code',
    title: '修登录页',
    directory: '/Users/frago/Repos/frago',
    created_at: 1_753_700_000_000,
    last_active_at: 1_753_800_000_000,
    last_reply_at: null,
    agent_paths: [],
    status: 'done',
    digest_done: null,
    digest_stuck: null,
    origin: 'human',
    parent_session_id: null,
    ...over,
  };
}

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

describe('SessionMenu 交接到新会话（二级菜单降级入口）', () => {
  it('普通空闲会话：打开页头更多菜单即可直接点击交接，点击后收起菜单', () => {
    const onHandoff = vi.fn();
    const session = makeSession({ status: 'done' });
    render(
      <SessionMenu
        session={session}
        variant="header"
        pinned={false}
        inTmux={false}
        onHandoff={onHandoff}
      />
    );

    fireEvent.click(screen.getByTestId('session-menu-button'));
    const item = screen.getByTestId('session-menu-handoff') as HTMLButtonElement;
    expect(item.disabled).toBe(false);
    expect(item.textContent).toContain('交接到新会话');

    fireEvent.click(item);
    expect(onHandoff).toHaveBeenCalledTimes(1);
    expect(onHandoff).toHaveBeenCalledWith(session);
    expect(screen.queryByTestId('session-menu')).toBeNull();
  });

  it('运行中会话（busyTurn + inTmux + running）：无时机限制，同样可直接交接', () => {
    const onHandoff = vi.fn();
    const session = makeSession({ status: 'running', in_tmux: true });
    render(
      <SessionMenu
        session={session}
        variant="header"
        pinned={false}
        inTmux
        busyTurn
        onHandoff={onHandoff}
      />
    );

    fireEvent.click(screen.getByTestId('session-menu-button'));
    const item = screen.getByTestId('session-menu-handoff') as HTMLButtonElement;
    expect(item.disabled).toBe(false);
    fireEvent.click(item);
    expect(onHandoff).toHaveBeenCalledTimes(1);
  });

  it('交接进行中：按钮禁用并展示「交接中」，重复点击不重入', () => {
    const onHandoff = vi.fn();
    render(
      <SessionMenu
        session={makeSession()}
        variant="header"
        pinned={false}
        inTmux={false}
        onHandoff={onHandoff}
        handingOff
      />
    );

    fireEvent.click(screen.getByTestId('session-menu-button'));
    const item = screen.getByTestId('session-menu-handoff') as HTMLButtonElement;
    expect(item.disabled).toBe(true);
    expect(item.textContent).toContain('交接中');
    fireEvent.click(item);
    expect(onHandoff).not.toHaveBeenCalled();
  });

  it('未传 onHandoff（如左栏卡片菜单）时不渲染该项，不改变原有菜单分段', () => {
    render(<SessionMenu session={makeSession()} variant="card" pinned={false} inTmux={false} />);
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.queryByTestId('session-menu-handoff')).toBeNull();
    const sections = screen.getAllByTestId('session-menu-section').map((el) => el.dataset.section);
    expect(sections).toEqual(['organize', 'delete']);
  });

  it('英文语言下展示正确文案', async () => {
    await i18n.changeLanguage('en');
    const view = render(
      <SessionMenu
        session={makeSession()}
        variant="header"
        pinned={false}
        inTmux={false}
        onHandoff={vi.fn()}
      />
    );
    try {
      fireEvent.click(screen.getByTestId('session-menu-button'));
      const item = screen.getByTestId('session-menu-handoff');
      expect(item.textContent).toContain('Hand to new session');
      expect(item.getAttribute('title')).toContain('same agent, same folder');
    } finally {
      view.unmount();
      await i18n.changeLanguage('zh');
    }
  });
});
