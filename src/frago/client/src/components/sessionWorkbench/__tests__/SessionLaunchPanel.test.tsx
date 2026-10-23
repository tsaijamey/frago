/**
 * 中栏那块启动面板：会话还没起来时，人看到的是什么。
 *
 * 三档各断言一件最容易破的事：正在认领编号时第二步不许先亮、起来之后第一步要打勾、
 * 没起来时原因和那句话都得留在眼前。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import SessionLaunchPanel from '../SessionLaunchPanel';
import type { SessionLaunch } from '@/hooks/useSessionLaunch';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const BASE: SessionLaunch = {
  handle: 'launch-1',
  agentName: 'codex',
  cwd: '/Users/frago/Repos/frago',
  text: '把 recipes 目录清一遍',
  sessionId: null,
  phase: 'claiming',
  error: null,
  at: Date.now(),
};

describe('新会话启动面板', () => {
  it('正在认领编号：第一步在走，第二步还没轮到', () => {
    render(<SessionLaunchPanel launch={BASE} onDismiss={() => {}} />);

    expect(screen.getByTestId('session-launch').getAttribute('data-phase')).toBe('claiming');
    const steps = screen.getAllByTestId('launch-step');
    expect(steps[0].getAttribute('data-state')).toBe('active');
    expect(steps[1].getAttribute('data-state')).toBe('waiting');
    // 他刚打的那句话得在——等待期间界面上只有它是他自己的东西。
    expect(screen.getByTestId('launch-first-message').textContent).toBe('把 recipes 目录清一遍');
    // 顶部镜头栏与会话详情保持完全一致：默认落在「对话」档，且词条已正常翻译（非原始键名）
    expect(screen.getByTestId('lens-talk').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('lens-all').getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByTestId('lens-talk').textContent).toContain('对话');
    expect(screen.getByTestId('lens-all').textContent).toContain('全部');
    expect(screen.getByTestId('trail-bubble').textContent).toContain('你说');
  });

  it('编号有了：第一步打勾，改等它写下第一笔', () => {
    render(
      <SessionLaunchPanel
        launch={{ ...BASE, phase: 'warming', sessionId: 'sid-1' }}
        onDismiss={() => {}}
      />
    );

    const steps = screen.getAllByTestId('launch-step');
    expect(steps[0].getAttribute('data-state')).toBe('done');
    expect(steps[1].getAttribute('data-state')).toBe('active');
  });

  it('没起来：原因照抄摆出来，由人自己收掉或返回修改', () => {
    const onDismiss = vi.fn();
    const onBackToEdit = vi.fn();
    render(
      <SessionLaunchPanel
        launch={{ ...BASE, phase: 'failed', error: 'codex 起不来：命令没找到' }}
        onDismiss={onDismiss}
        onBackToEdit={onBackToEdit}
      />
    );

    expect(screen.getByTestId('launch-error').textContent).toContain('命令没找到');
    // 没起来那一档不摆进度：两步都没走完，画个半截进度只会误导。
    expect(screen.queryAllByTestId('launch-step')).toHaveLength(0);
    expect(screen.getByTestId('launch-first-message').textContent).toBe('把 recipes 目录清一遍');
    expect(screen.getByTestId('trail-bubble').getAttribute('data-fresh')).toBe('true');

    fireEvent.click(screen.getByTestId('launch-back-to-edit'));
    expect(onBackToEdit).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId('launch-dismiss'));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
