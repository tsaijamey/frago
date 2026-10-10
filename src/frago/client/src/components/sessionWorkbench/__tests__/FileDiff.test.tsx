/**
 * 改动档那两列的行结构。
 *
 * 主人 10-10 报的「乱码」不是编码坏了，是**长行折行时两行画在同一处**：整张网格铺到底的
 * 写法里，行高按不换行时的字宽算出来，长行折成两行、格子仍只有一行高，折下来的那半截压在
 * 下一行上。
 *
 * jsdom 不做排版，量不出高矮，所以这里钉的是**结构**：每一行自己一张网格（一行一个盒子），
 * 而不是所有格子平铺在同一张网格里。摊平回去，这条就红。
 */

import { beforeAll, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import FileDiff from '../FileDiff';
import type { FileDiffCell, SessionFileDiff } from '@/types/api';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function cell(sign: FileDiffCell['sign'], no: number, text: string): FileDiffCell {
  return { sign, no, text };
}

/** 一格长到会折行的行：真文件里那种顶到边上的注释。 */
const LONG = '* Type definitions live in `@/types/api`; they are imported here for use in the HTTP';

function diff(rows: SessionFileDiff['rows'], over: Partial<SessionFileDiff> = {}): SessionFileDiff {
  return {
    path: '/w/a.ts',
    size: 100,
    reason: null,
    before: null,
    source: 'git HEAD',
    rows,
    ...over,
  };
}

function rowBoxes(): HTMLElement[] {
  return [...screen.getByTestId('file-diff-rows').children] as HTMLElement[];
}

describe('两列的行结构', () => {
  it('一行一个盒子：左右两格在同一个盒子里，不是平铺在同一张网格上', () => {
    render(
      <FileDiff
        diff={diff([
          [cell('-', 1, 'x = 1'), cell('+', 1, 'x = 2')],
          [cell(' ', 2, LONG), cell(' ', 2, LONG)],
          [cell(' ', 3, 'y = 2'), cell(' ', 3, 'y = 2')],
        ])}
        loading={false}
        error={null}
      />
    );

    const boxes = rowBoxes();
    expect(boxes).toHaveLength(3);
    for (const box of boxes) {
      expect(box.querySelectorAll('.diff-cell')).toHaveLength(2);
    }
    // 折行那一行两边都还在，文字一个字不少。
    expect(boxes[1].textContent).toContain('they are imported here for use in the HTTP');
  });

  it('没有左边那一侧（这场会话新建的）时，一行只有一个盒子、一格', () => {
    render(
      <FileDiff
        diff={diff(
          [
            [null, cell('+', 1, 'one')],
            [null, cell('+', 2, 'two')],
          ],
          { before: 'new' }
        )}
        loading={false}
        error={null}
      />
    );

    const boxes = rowBoxes();
    expect(boxes).toHaveLength(2);
    for (const box of boxes) {
      expect(box.querySelectorAll('.diff-cell')).toHaveLength(1);
    }
  });

  it('每一格都带着它的行号与增删记号', () => {
    render(
      <FileDiff
        diff={diff([[cell('-', 7, 'old'), cell('+', 7, 'new')]])}
        loading={false}
        error={null}
      />
    );

    const [box] = rowBoxes();
    const cells = [...box.querySelectorAll('.diff-cell')] as HTMLElement[];
    expect(cells.map((c) => c.getAttribute('data-sign'))).toEqual(['-', '+']);
    expect(cells[0].textContent).toBe('7old');
    expect(cells[1].textContent).toBe('7new');
  });
});
