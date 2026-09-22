/**
 * 左栏那颗「复制续接命令」按钮的用例。
 *
 * 盯两件事：
 *
 * 1. **三家各复制自己那一种写法。** 从前这里是 `switch` 的 default 分支兜住一切，于是
 *    CoreAgent 的会话也复制出 `claude --resume core_…`——那个编号在 claude 的档案里不
 *    存在，粘到终端里 claude 会拿它当新编号开一场空白会话，人以为自己接上了原来那场。
 * 2. **CoreAgent 那一家不长这颗按钮。** 它没有能挂在终端里的交互界面，没有这样一条命令。
 */

import { describe, expect, it, beforeAll } from 'vitest';
import { render, screen } from '@testing-library/react';

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
  it('三家各给自己那一种写法', () => {
    expect(resumeCommand(session({ session_id: 'abc-123' }))).toBe('claude --resume abc-123');
    expect(resumeCommand(session({ session_id: 'ses_09', family: 'opencode' }))).toBe(
      'opencode -s ses_09'
    );
    expect(resumeCommand(session({ session_id: 'cx-09', family: 'codex' }))).toBe(
      'codex resume cx-09'
    );
  });

  it('CoreAgent 没有这样一条命令，NEVER 退回 claude 那一种', () => {
    const cmd = resumeCommand(session({ session_id: 'core_0a1b', family: 'coreagent' }));
    expect(cmd).toBeNull();
  });

  it('有命令的那几家长按钮，CoreAgent 不长', () => {
    const { rerender } = render(
      <SessionItem
        session={session({ session_id: 'abc-123' })}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    expect(screen.getByTestId('copy-resume')).toBeTruthy();

    rerender(
      <SessionItem
        session={session({ session_id: 'core_0a1b', family: 'coreagent' })}
        selected={false}
        copied={false}
        onSelect={NOOP}
        onCopy={NOOP}
      />
    );
    expect(screen.queryByTestId('copy-resume')).toBeNull();
  });
});
