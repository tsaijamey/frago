/**
 * 地址与页面的对应关系。
 *
 * 这份用例守的是"刷新之后还停在原处"这件事本身：每一页要能写出一个地址，那个地址
 * 要能读回同一页。任何一头断掉，人在子页面按一下刷新就会被弹回首页——这正是这套
 * 表要终结的那个毛病。
 */

import { describe, expect, it } from 'vitest';
import { HOME_PAGE, parsePath, pathForPage } from '@/routes';
import type { PageType } from '@/stores/pageStore';

describe('pathForPage', () => {
  it('清单页写成一段', () => {
    expect(pathForPage('recipes')).toBe('/recipes');
    expect(pathForPage('todos')).toBe('/todos');
    expect(pathForPage('session_workbench')).toBe('/sessions');
  });

  it('详情页把编号缀在同一段后面', () => {
    expect(pathForPage('recipe_detail', 'my-recipe')).toBe('/recipes/my-recipe');
    expect(pathForPage('todo_detail', '20260627-fix-todo-id')).toBe('/todos/20260627-fix-todo-id');
  });

  it('编号里的特殊字符要转义，否则地址会被读成多一层', () => {
    expect(pathForPage('todo_detail', 'a/b')).toBe('/todos/a%2Fb');
  });
});

describe('parsePath', () => {
  it('地址栏是空的就落在首页', () => {
    expect(parsePath('')).toEqual({ page: HOME_PAGE, id: null });
    expect(parsePath('#')).toEqual({ page: HOME_PAGE, id: null });
    expect(parsePath('#/')).toEqual({ page: HOME_PAGE, id: null });
  });

  it('一段读成清单页，不是缺了编号的详情页', () => {
    expect(parsePath('#/recipes')).toEqual({ page: 'recipes', id: null });
    expect(parsePath('#/todos')).toEqual({ page: 'todos', id: null });
  });

  it('两段读成详情页', () => {
    expect(parsePath('#/recipes/my-recipe')).toEqual({ page: 'recipe_detail', id: 'my-recipe' });
    expect(parsePath('#/todos/20260627-x')).toEqual({ page: 'todo_detail', id: '20260627-x' });
    expect(parsePath('#/workspace/run-9')).toEqual({ page: 'project_detail', id: 'run-9' });
  });

  it('认不出来的地址回首页，NEVER 留一张白页', () => {
    // 从聊天记录里粘来的地址、手敲错一个字母都会走到这里。白屏比回首页糟得多。
    expect(parsePath('#/根本没有这一页')).toEqual({ page: HOME_PAGE, id: null });
  });

  it('没有详情页的那一段，多出来的一截不当编号', () => {
    expect(parsePath('#/settings/oauth')).toEqual({ page: 'settings', id: null });
  });

  it('前面的井号可有可无', () => {
    expect(parsePath('/todos/abc')).toEqual({ page: 'todo_detail', id: 'abc' });
  });

  it('查询串不参与判定', () => {
    expect(parsePath('#/todos?from=mail')).toEqual({ page: 'todos', id: null });
  });

  it('半截百分号编码不该把整页搞崩', () => {
    expect(() => parsePath('#/todos/%E4')).not.toThrow();
  });
});

describe('写出去再读回来', () => {
  const cases: [PageType, string | null][] = [
    ['session_workbench', null],
    ['recipes', null],
    ['recipe_detail', 'my-recipe'],
    ['todos', null],
    ['todo_detail', '20260627-fix-todo-id-slug-pinyin-garbage'],
    ['data_repo', null],
    ['skills', null],
    ['settings', null],
    ['workspace', null],
    ['project_detail', 'run-9'],
    ['tasks', null],
    ['task_detail', 't-1'],
    ['guide', null],
    ['newTask', null],
  ];

  it.each(cases)('%s 写出去的地址读回来还是同一页', (page, id) => {
    expect(parsePath(pathForPage(page, id))).toEqual({ page, id });
  });

  it('编号里带斜杠也转得回来', () => {
    expect(parsePath(pathForPage('todo_detail', 'a/b'))).toEqual({
      page: 'todo_detail',
      id: 'a/b',
    });
  });
});
