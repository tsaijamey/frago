/**
 * 输入框里敲 `/` 挑 skill。
 *
 * 盯的是人看得见的几件事：`/` 弹出集中管理的清单（名字加一截说明）、接着打的字能筛、
 * 挑中后框里的 `/…` 被抹掉换成一枚引用、发出去只带名字、路径里的斜杠不会误弹。
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Composer, { slashQuery } from '../Composer';
import { filterSkills, SKILL_MENU_DESC_CHARS } from '../SkillMenu';
import { useDataStore } from '@/stores/dataStore';
import type { SkillItem } from '@/types/api';
import i18n from '@/i18n';

const SID = '00a02979-7eb4-5c70-94ae-867c8281e3f6';

const LONG_DESC =
  '智能分析 Git 工作区文件改动，按功能相关性自动分组提交并推送。当用户提到提交、commit、push、推送代码时触发，并且还有很长很长的一段说明。';

const SKILLS: SkillItem[] = [
  { name: 'git-push', description: LONG_DESC, file_path: '/s/git-push/SKILL.md' },
  { name: 'git-linear-history', description: '配置 Git 线性历史', file_path: null },
  { name: 'superpowers:brainstorming', description: '先想清楚再动手', file_path: null },
  { name: 'pypi-publish', description: '发布到 PyPI，改动 git tag', file_path: null },
];

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

let fetchMock: ReturnType<typeof vi.fn>;

/** 数据仓里那份清单的形状多一个 `icon`（与桌面壳共用的类型），这里补上。 */
const STORE_SKILLS = SKILLS.map((s) => ({ ...s, icon: null, file_path: s.file_path ?? '' }));

beforeEach(() => {
  fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ sid: SID, status: 'warm', text: '' }),
  }));
  vi.stubGlobal('fetch', fetchMock);
  useDataStore.setState({ skills: STORE_SKILLS });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  useDataStore.setState({ skills: [] });
});

function input() {
  return screen.getByTestId('composer-input') as HTMLTextAreaElement;
}

function type(value: string) {
  fireEvent.focus(input());
  fireEvent.change(input(), { target: { value } });
}

describe('slashQuery', () => {
  it('行首或空白后的斜杠才算', () => {
    expect(slashQuery('/git', 4)).toEqual({ start: 0, query: 'git' });
    expect(slashQuery('先看 /py', 6)).toEqual({ start: 3, query: 'py' });
    expect(slashQuery('第一行\n/', 5)).toEqual({ start: 4, query: '' });
  });

  it('路径里的斜杠、打了空格之后都不算', () => {
    expect(slashQuery('src/frago', 9)).toBeNull();
    expect(slashQuery('/git push', 9)).toBeNull();
  });
});

describe('filterSkills', () => {
  it('名字开头对上的排前面，插件前缀后面的名字也认', () => {
    expect(filterSkills(SKILLS, 'git').map((s) => s.name)).toEqual([
      'git-linear-history',
      'git-push',
      'pypi-publish',
    ]);
    expect(filterSkills(SKILLS, 'brain').map((s) => s.name)).toEqual(['superpowers:brainstorming']);
  });
});

describe('Composer 里挑 skill', () => {
  it('敲斜杠弹出清单，每行名字加截断的说明', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('/');
    const items = screen.getAllByTestId('skill-menu-item');
    expect(items).toHaveLength(SKILLS.length);
    const first = items.find((el) => el.textContent?.includes('git-push'))!;
    expect(first.textContent).toContain(`${Array.from(LONG_DESC).slice(0, SKILL_MENU_DESC_CHARS).join('')}…`);
    expect(first.textContent).not.toContain('很长很长的一段说明');
  });

  it('接着打的字用来筛，一个都对不上时说明白', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('/brain');
    expect(screen.getAllByTestId('skill-menu-item').map((el) => el.textContent)).toEqual([
      expect.stringContaining('superpowers:brainstorming'),
    ]);
    type('/zzz');
    expect(screen.getByTestId('skill-menu-empty')).toBeTruthy();
  });

  it('回车挑中：框里的 /… 抹掉，换成一枚引用，名字加更短的说明', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('请 /git-p');
    fireEvent.keyDown(input(), { key: 'Enter' });

    expect(input().value).toBe('请 ');
    expect(screen.queryByTestId('skill-menu')).toBeNull();
    const quote = screen.getByTestId('skill-quote');
    expect(quote.getAttribute('data-skill')).toBe('git-push');
    expect(quote.textContent).toContain('/git-push');
    expect(quote.textContent).toContain('…');
  });

  it('上下键换选中那一行，Tab 也能挑', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('/git');
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    fireEvent.keyDown(input(), { key: 'Tab' });
    expect(screen.getByTestId('skill-quote').getAttribute('data-skill')).toBe('git-push');
  });

  it('Esc 关掉清单，框里的字不动', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('/git');
    fireEvent.keyDown(input(), { key: 'Escape' });
    expect(screen.queryByTestId('skill-menu')).toBeNull();
    expect(input().value).toBe('/git');
  });

  it('路径里的斜杠不弹清单', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('看看 src/frago');
    expect(screen.queryByTestId('skill-menu')).toBeNull();
  });

  it('只挑 skill、不打字也能发；出门只带名字，引用随之清掉', async () => {
    const onSent = vi.fn();
    render(<Composer sessionId={SID} family="codex" onSent={onSent} />);
    type('/pypi');
    fireEvent.keyDown(input(), { key: 'Enter' });
    fireEvent.click(screen.getByTestId('composer-send'));

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body).toEqual({ text: '', images: [], documents: [], skills: ['pypi-publish'] });
    expect(screen.queryByTestId('skill-quote')).toBeNull();
  });

  it('引用上的叉去掉那个 skill', () => {
    render(<Composer sessionId={SID} family="codex" onSent={() => {}} />);
    type('/pypi');
    fireEvent.keyDown(input(), { key: 'Enter' });
    fireEvent.click(screen.getByTestId('skill-quote-remove'));
    expect(screen.queryByTestId('skill-quote')).toBeNull();
  });

  it('发出去之后上方的气泡把 skill 名写出来', () => {
    render(
      <Composer
        sessionId={SID}
        family="codex"
        onSent={() => {}}
        outbound={[{ id: 'o1', text: '', skills: ['git-push'], attachments: 0, at: 1, state: 'sent' }]}
      />
    );
    expect(screen.getByTestId('composer-outbound-skill').textContent).toBe('/git-push');
    expect(screen.getByTestId('composer-outbound').textContent).not.toContain('只有附件');
  });
});
