/**
 * 左栏那颗「复制续接命令」按钮的用例。
 *
 * 盯三件事：
 *
 * 1. **五家各复制自己那一种写法。** 从前这里是 `switch` 的 default 分支兜住一切，于是每接
 *    一家新内核就复制出 claude 的命令一次：CoreAgent 那回是 `claude --resume core_…`，
 *    antigravity 这回落进同一条分支。那个编号在 claude 的档案里根本不存在，粘到终端里
 *    claude 会拿它当新编号开一场空白会话，人以为自己接上了原来那场。
 * 2. **CoreAgent 那条必须带工作目录。** 它的会话记录按工作目录分开放，`--resume` 只在当初
 *    那个目录下找得到；目录拿不到就不出这条命令，NEVER 退化成不带目录的那一种。
 * 3. **按钮跟着命令走。** 拼得出命令的才有这一项，拼不出的没有。
 */

import { describe, expect, it, beforeAll } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import SessionItem, { resumeCommand } from '../SessionItem';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

const NOOP = () => {};

function session(
  over: Partial<WorkbenchSession> & Pick<WorkbenchSession, 'session_id'>
): WorkbenchSession {
  return {
    family: 'claude-code',
    title: `会话 ${over.session_id}`,
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

describe('复制续接命令', () => {
  it('五家各给自己那一种写法', () => {
    expect(resumeCommand(session({ session_id: 'abc-123' }))).toBe('claude --resume abc-123');
    expect(resumeCommand(session({ session_id: 'ses_09', family: 'opencode' }))).toBe(
      'opencode -s ses_09'
    );
    expect(resumeCommand(session({ session_id: 'cx-09', family: 'codex' }))).toBe(
      'codex resume cx-09'
    );
    expect(resumeCommand(session({ session_id: 'agy-09', family: 'agy' }))).toBe(
      'agy --conversation agy-09'
    );
    expect(resumeCommand(session({ session_id: 'core_0a1b', family: 'coreagent' }))).toBe(
      'frago-core --resume core_0a1b --cwd /Users/frago/Repos/frago'
    );
  });

  it('antigravity NEVER 退回 claude 那一种', () => {
    // 落进 claude 分支的那一版，复制出来的是 `claude --resume <agy 编号>`——
    // 那个编号在 claude 的档案里不存在，粘到终端会开一场空白会话。
    const cmd = resumeCommand(session({ session_id: 'agy-09', family: 'agy' }));
    expect(cmd).not.toBe('claude --resume agy-09');
    expect(cmd).toBe('agy --conversation agy-09');
  });

  it('CoreAgent 那条必须带工作目录，NEVER 退回不带目录的那一种', () => {
    // 会话记录按工作目录分开放，`--resume` 只在当初那个目录下找得到：换个目录跑，frago-core
    // 不报错，静默开一场空白会话，还在新目录下用同一个编号另写一份记录。
    const cmd = resumeCommand(session({ session_id: 'core_0a1b', family: 'coreagent' }));
    expect(cmd).not.toBe('claude --resume core_0a1b');
    expect(cmd).not.toBe('frago-core --resume core_0a1b');
    expect(cmd).toBe('frago-core --resume core_0a1b --cwd /Users/frago/Repos/frago');
  });

  it('CoreAgent 拿不到工作目录就不出命令', () => {
    const cmd = resumeCommand(
      session({ session_id: 'core_0a1b', family: 'coreagent', directory: '' })
    );
    expect(cmd).toBeNull();
  });

  it('工作目录带空格时裹单引号，粘进终端不会被拆成两个参数', () => {
    expect(
      resumeCommand(
        session({ session_id: 'core_0a1b', family: 'coreagent', directory: '/Users/a b/项目' })
      )
    ).toBe("frago-core --resume core_0a1b --cwd '/Users/a b/项目'");
  });

  it('「…」菜单里这一项跟着命令走', () => {
    const { rerender } = render(
      <SessionItem
        session={session({ session_id: 'abc-123' })}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.getByTestId('copy-resume')).toBeTruthy();
    fireEvent.click(screen.getByTestId('session-menu-button'));

    // CoreAgent 带得出目录，这一项就在——它从前是这页里唯一不长这一项的一家。
    rerender(
      <SessionItem
        session={session({ session_id: 'core_0a1b', family: 'coreagent' })}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.getByTestId('copy-resume')).toBeTruthy();
    fireEvent.click(screen.getByTestId('session-menu-button'));

    // 目录拿不到，命令拼不出来，这一项也不长。
    rerender(
      <SessionItem
        session={session({ session_id: 'core_0a1b', family: 'coreagent', directory: '' })}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    fireEvent.click(screen.getByTestId('session-menu-button'));
    expect(screen.queryByTestId('copy-resume')).toBeNull();
  });

  it('五家会话在卡片右下角各自显示对应的程序图标，CoreAgent 采用 frago 图标', () => {
    const cases: Array<{ family: WorkbenchSession['family']; src: string; alt: string }> = [
      { family: 'claude-code', src: '/icons/claude-code.svg', alt: 'Claude Code' },
      { family: 'codex', src: '/icons/codex.svg', alt: 'Codex' },
      { family: 'opencode', src: '/icons/opencode.svg', alt: 'OpenCode' },
      { family: 'agy', src: '/icons/antigravity.png', alt: 'Antigravity' },
      { family: 'coreagent', src: '/icons/coreagent.png', alt: 'CoreAgent' },
    ];
    const { rerender } = render(
      <SessionItem
        session={session({ session_id: 's-0', family: cases[0].family })}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    for (const c of cases) {
      rerender(
        <SessionItem
          session={session({ session_id: `s-${c.family}`, family: c.family })}
          selected={false}
          copied={false}
          onSelect={NOOP}
          onCopy={NOOP}
        />
      );
      const img = screen.getByTestId('session-family-icon') as HTMLImageElement;
      expect(img.getAttribute('src')).toBe(c.src);
      expect(img.getAttribute('alt')).toBe(c.alt);
      expect(img.getAttribute('data-family')).toBe(c.family);
    }
  });
});
