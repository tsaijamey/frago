/**
 * 发起一个 team 时那段等待。
 *
 * 钉住的是「等待必须说实话」这一件事：条子按真实档位走，不是一段自己跑完的动画；
 * 三档各自的状态看得出来；等了多久原样报出来；随时能不等了。
 *
 * 为什么值得钉：这段等待最长三十秒，而它等的是一件人完全看不见的事（新会话报出自己
 * 的编号）。等待期间只要有一处开始编——条子自己跑到头、时间不动、说不清在等什么——
 * 人就会以为卡死了，然后去点第二次，于是起了两场会话。
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { WaitingView } from '../StartTeamPanel';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  vi.useRealTimers();
});

function widthOf(): number {
  const bar = screen.getByTestId('team-start-progress');
  return Number.parseInt(bar.style.width, 10);
}

function states(): string[] {
  return screen.getAllByTestId('team-start-step').map((el) => el.dataset.state ?? '');
}

describe('发起时的等待', () => {
  it('三档按顺序推进，走到哪一档就是哪一档', () => {
    const { rerender } = render(
      <WaitingView
        phase="creating"
        agentName="Claude Code"
        idIsInstant
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(states()).toEqual(['active', 'waiting', 'waiting']);

    rerender(
      <WaitingView
        phase="awaitingId"
        agentName="codex"
        idIsInstant={false}
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(states()).toEqual(['done', 'active', 'waiting']);

    rerender(
      <WaitingView
        phase="askingCode"
        agentName="codex"
        idIsInstant={false}
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(states()).toEqual(['done', 'done', 'active']);
  });

  it('等编号那一档的条子爬在自己的区间里，爬到头也不越界', () => {
    vi.useFakeTimers();
    const started = Date.now();
    render(
      <WaitingView
        phase="awaitingId"
        agentName="codex"
        idIsInstant={false}
        startedAt={started}
        onCancel={() => {}}
      />,
    );

    // 刚进这一档：停在第一档尾。
    expect(widthOf()).toBe(33);

    // 等满上限之后停在本档尾，NEVER 自己跑到 100——跑到头就是在说「马上就好」，
    // 而这一刻并没有任何事情表明它快好了。
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    const atCeiling = widthOf();
    expect(atCeiling).toBeGreaterThan(33);
    expect(atCeiling).toBeLessThanOrEqual(67);
  });

  it('已等多少秒是真的在走', () => {
    vi.useFakeTimers();
    render(
      <WaitingView
        phase="awaitingId"
        agentName="codex"
        idIsInstant={false}
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText(/已等 0 秒/)).toBeTruthy();

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(screen.getByText(/已等 5 秒/)).toBeTruthy();
  });

  it('慢的那一家把预计时间说出来，快的那一家说当场就有', () => {
    const { rerender } = render(
      <WaitingView
        phase="awaitingId"
        agentName="codex"
        idIsInstant={false}
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText(/通常 3–15 秒/)).toBeTruthy();

    rerender(
      <WaitingView
        phase="creating"
        agentName="Claude Code"
        idIsInstant
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText(/当场就有/)).toBeTruthy();
  });

  it('说清为什么不能先把码给出去', () => {
    render(
      <WaitingView
        phase="awaitingId"
        agentName="codex"
        idIsInstant={false}
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText(/还不存在的会话/)).toBeTruthy();
  });

  it('随时能不等了', () => {
    const onCancel = vi.fn();
    render(
      <WaitingView
        phase="awaitingId"
        agentName="codex"
        idIsInstant={false}
        startedAt={Date.now()}
        onCancel={onCancel}
      />,
    );
    screen.getByText('不等了').click();
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('进度条把自己的进度报给读屏', () => {
    render(
      <WaitingView
        phase="creating"
        agentName="Claude Code"
        idIsInstant
        startedAt={Date.now()}
        onCancel={() => {}}
      />,
    );
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('17');
  });
});
