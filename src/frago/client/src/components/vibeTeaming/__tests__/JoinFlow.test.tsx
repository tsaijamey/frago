/**
 * 加入一个 team：填码，挑一场会话带进去。
 *
 * 钉住的是**人在这条路上会撞见的每一种收场**。这条路的处境特殊：人手里攥着队友刚发来
 * 的码，注意力全在"进不进得去"上，而这一步能出的事有好几种，每种该做的下一步完全不同。
 * 任何一种落空——按钮点不动却不说为什么、失败了只给一句"请求失败"、被限流却不说等多久
 * ——人唯一的办法就是反复乱点。
 *
 * 曾经就是这样：填完码按钮点不动，底下一句让人先去会话页"选一场会话"，而那是什么动作
 * 没有任何地方说。
 */

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import i18n from '@/i18n';
import { TeamError } from '@/hooks/useTeam';

const joinTeam = vi.fn();

vi.mock('@/hooks/useTeam', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/hooks/useTeam')>();
  return {
    ...actual,
    joinTeam: (...args: unknown[]) => joinTeam(...args),
    usePeerRecords: () => ({
      records: [],
      status: null,
      loading: false,
      error: null,
      reload: () => {},
    }),
  };
});

// 挑会话那一整套是发起那边的，这里不重复验它，只盯"挑完之后发生什么"。
vi.mock('@/components/vibeTeaming/StartTeamPanel', () => ({
  default: ({
    commit,
    confirmLabel,
    lastStepLabel,
    onCancel,
  }: {
    commit: (sessionId: string) => Promise<unknown>;
    confirmLabel?: string;
    lastStepLabel?: string;
    onCancel: () => void;
  }) => (
    <div>
      <span data-testid="last-step">{lastStepLabel}</span>
      <button onClick={() => void commit('sid-1').catch(() => {})}>{confirmLabel}</button>
      <button onClick={onCancel}>回到填码</button>
    </div>
  ),
}));

import VibeTeamingPage from '../VibeTeamingPage';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

afterEach(() => {
  joinTeam.mockReset();
  vi.unstubAllGlobals();
});

/** 本机这一侧的状态：给几个已经在里面的 team。 */
function servingTeams(codes: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes('/api/team') && !path.includes('/join')) {
        return {
          ok: true,
          json: async () => ({
            member: 'm',
            prefix: '前缀 {code}：',
            interval_seconds: 15,
            teams: codes.map((code) => ({
              code,
              session_id: 'sid-old',
              side: 'A',
              active: true,
              pushed_seq: 0,
            })),
          }),
        } as Response;
      }
      // 双列那半边要会话清单与记录流。这一组用例不验它们，给空的即可——但形状必须
      // 对：清单那条回的是**数组**，给成对象的话整棵树在渲染时就炸，而报出来的错
      // 跟加入这件事毫无关系，排查要绕一大圈。
      if (path.includes('/workbench/sessions')) {
        return { ok: true, json: async () => [] } as unknown as Response;
      }
      if (path.includes('/records')) {
        return { ok: true, json: async () => ({ records: [], has_older: false }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }),
  );
}

/** 进到填码那一步。
 *
 * 入口有两个，长相不同：一个 team 都没有时是说明书上那张「我有别人给的码」的卡；
 * 已经在某个 team 里时是顶栏那个「用连接码加入」。两条都要能走到同一个地方。
 */
async function openJoin() {
  render(<VibeTeamingPage />);
  const entry = await screen.findByText(/用连接码加入|我有别人给的码/);
  fireEvent.click(entry.closest('button') ?? entry);
  return screen.findByPlaceholderText('十位连接码');
}

function type(input: HTMLElement, code: string) {
  fireEvent.change(input, { target: { value: code } });
}

/** 「下一步」那个按钮。这套仓库没装 jest-dom，所以直接看属性。 */
function nextButton(): HTMLButtonElement {
  return screen.getByText('下一步').closest('button') as HTMLButtonElement;
}

describe('加入一个 team', () => {
  it('码没填全时按钮点不动，并写明还差几位', async () => {
    servingTeams(['AAAAAAAAAA']);
    const input = await openJoin();

    type(input, 'BBBB');

    expect(nextButton().disabled).toBe(true);
    expect(screen.getByText(/还差|连接码是 10 位/)).toBeTruthy();
  });

  it('填全了就能往下走，不再要求先去别处选会话', async () => {
    servingTeams(['AAAAAAAAAA']);
    const input = await openJoin();

    type(input, 'BBBBBBBBBB');

    expect(nextButton().disabled).toBe(false);
    expect(screen.queryByText(/会话页/)).toBeNull();
  });

  it('已经在这个 team 里就当场说清，一个请求都不发', async () => {
    servingTeams(['AAAAAAAAAA']);
    const input = await openJoin();

    type(input, 'AAAAAAAAAA');

    expect(screen.getByText('你已经在这个 team 里了')).toBeTruthy();
    expect(nextButton().disabled).toBe(true);
    expect(joinTeam).not.toHaveBeenCalled();
  });

  it('加入那一侧末档写的是「拿这个码进去」，不是「朝中继要连接码」', async () => {
    servingTeams(['AAAAAAAAAA']);
    const input = await openJoin();
    type(input, 'BBBBBBBBBB');
    fireEvent.click(screen.getByText('下一步'));

    expect((await screen.findByTestId('last-step')).textContent).toBe('拿这个码进去');
  });

  it('码不可用时把码留着让人改，不给「再试一次」', async () => {
    servingTeams([]);
    joinTeam.mockRejectedValue(new TeamError('这个连接码在中继上不可用', 'bad_code'));
    const input = await openJoin();
    type(input, 'BBBBBBBBBB');
    fireEvent.click(screen.getByText('下一步'));

    fireEvent.click(await screen.findByText('用这一场加入'));

    expect(await screen.findByText('这个码用不了')).toBeTruthy();
    expect(screen.getByText('改那串码')).toBeTruthy();
    expect(screen.queryByText('再试一次')).toBeNull();
  });

  it('够不着中继时说清跟码无关，并给「再试一次」', async () => {
    servingTeams([]);
    joinTeam.mockRejectedValue(new TeamError('连不上中继 https://www.frago.ai', 'relay_down'));
    const input = await openJoin();
    type(input, 'BBBBBBBBBB');
    fireEvent.click(screen.getByText('下一步'));

    fireEvent.click(await screen.findByText('用这一场加入'));

    expect(await screen.findByText('连不上中继')).toBeTruthy();
    expect(screen.getByText('再试一次')).toBeTruthy();
  });

  it('被限流时说清还要等几秒，倒数没走完不给重试', async () => {
    servingTeams([]);
    joinTeam.mockRejectedValue(new TeamError('中继在限流，等一会儿再来', 'busy'));
    const input = await openJoin();
    type(input, 'BBBBBBBBBB');
    fireEvent.click(screen.getByText('下一步'));

    fireEvent.click(await screen.findByText('用这一场加入'));
    await screen.findByText('中继在限流，等一会儿');

    // 让人对着一个永远点不动的按钮猜要等多久，比不给按钮还糟。
    expect(screen.getByText(/10 秒后可以再试/)).toBeTruthy();
    expect(screen.queryByText('再试一次')).toBeNull();

    // 倒数一直在走，到点自己放行。
    await waitFor(() => expect(screen.getByText(/9 秒后可以再试/)).toBeTruthy(), {
      timeout: 3000,
    });
    expect(screen.getByText('改那串码')).toBeTruthy();
  });

  it('码不可用时不摆中继原话——界面已经用当前语言说过同一件事', async () => {
    servingTeams([]);
    joinTeam.mockRejectedValue(
      new TeamError('这个连接码在中继上不可用。它可能打错了', 'bad_code'),
    );
    const input = await openJoin();
    type(input, 'BBBBBBBBBB');
    fireEvent.click(screen.getByText('下一步'));

    fireEvent.click(await screen.findByText('用这一场加入'));
    await screen.findByText('这个码用不了');

    // 那一句出自服务端、恒为中文，摆在英文界面上就是一段没人要的中文，而它说的
    // 又正是上面那句已经说过的事。
    expect(screen.queryByText(/这个连接码在中继上不可用/)).toBeNull();
  });

  it('够不着中继时把原话留着——它带着地址和底层错误，排查时对得上', async () => {
    servingTeams([]);
    joinTeam.mockRejectedValue(new TeamError('连不上中继 https://www.frago.ai：timed out', 'relay_down'));
    const input = await openJoin();
    type(input, 'BBBBBBBBBB');
    fireEvent.click(screen.getByText('下一步'));

    fireEvent.click(await screen.findByText('用这一场加入'));

    expect(await screen.findByText(/timed out/)).toBeTruthy();
  });
});
