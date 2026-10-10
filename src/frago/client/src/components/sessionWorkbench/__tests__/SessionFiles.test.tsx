/**
 * 「这场改过哪些文件」那份清单。
 *
 * 盯五件事：按目录归组、新建／改／删各是哪一枚标、点一行交出去的是**整份里的下标**（浮窗按
 * 它翻页，差一位就翻错文件）、删掉的那些点不开、以及「还不知道」与「没有」不许摆成同一个
 * 样子。
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import SessionFiles, { groupByDirectory } from '../SessionFiles';
import type { SessionFileAction, SessionFileRow } from '@/types/api';
import i18n from '@/i18n';

beforeAll(async () => {
  await i18n.changeLanguage('zh');
});

function file(path: string, action: SessionFileAction = 'modified', count = 1): SessionFileRow {
  return { path, action, count, first_seq: 0 };
}

describe('按目录归组', () => {
  it('同一目录的收在一组，组的先后照第一次出现的位置', () => {
    const groups = groupByDirectory([
      file('/w/src/a.py'),
      file('/w/docs/x.md'),
      file('/w/src/b.py'),
    ]);

    expect(groups.map((g) => g.dir)).toEqual(['/w/src', '/w/docs']);
    expect(groups[0].rows.map((r) => r.file.path)).toEqual(['/w/src/a.py', '/w/src/b.py']);
  });

  it('交出去的下标是按整份清单算的，不是组内位置', () => {
    const groups = groupByDirectory([file('/w/src/a.py'), file('/w/docs/x.md'), file('/w/src/b.py')]);

    // b.py 是整份里的第三个，尽管它在第一组里排第二。
    expect(groups[0].rows.map((r) => r.index)).toEqual([0, 2]);
    expect(groups[1].rows.map((r) => r.index)).toEqual([1]);
  });
});

describe('清单摆出来是什么样', () => {
  const files = [
    file('/Users/frago/Repos/frago/src/frago/session/session_files.py', 'created', 1),
    file('/Users/frago/Repos/frago/src/frago/session/record_reader.py', 'modified', 3),
  ];

  it('顶上说清这份清单是什么，组头说清几个改的、几个新建的', () => {
    render(
      <SessionFiles files={files} loading={false} error={null} onOpen={() => {}} onReload={() => {}} />
    );

    expect(screen.getByText('2 个文件')).toBeTruthy();
    // 下界那句话必须说出来：不说，人会拿它当全集用。
    expect(screen.getByTestId('session-files').textContent).toContain('下界');
    expect(screen.getAllByTestId('session-files-group')).toHaveLength(1);
    expect(screen.getByTestId('session-files-group-head').textContent).toContain('1 个改的 · 1 个新建');
  });

  it('新建与改各有一枚标，颜色不是唯一通道', () => {
    render(
      <SessionFiles files={files} loading={false} error={null} onOpen={() => {}} onReload={() => {}} />
    );

    const rows = screen.getAllByTestId('session-files-row');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('session_files.py');
    // 只动过一次的不写次数，动过三次的写出来。
    expect(rows[0].textContent).not.toContain('×1');
    expect(rows[1].textContent).toContain('×3');
    // 字母标在，悬停里写着全称（跨语言也认得出这一档是什么）。
    expect(screen.getByTitle('新建').textContent).toBe('A');
    expect(screen.getByTitle('改过').textContent).toBe('M');
  });

  it('点一行交出去的是它在整份里的下标', () => {
    const onOpen = vi.fn();
    render(
      <SessionFiles files={files} loading={false} error={null} onOpen={onOpen} onReload={() => {}} />
    );

    fireEvent.click(screen.getAllByTestId('session-files-row')[1]);
    expect(onOpen).toHaveBeenCalledWith(1);
  });

  it('组头点一下把这一组折起来，再点一下铺开', () => {
    render(
      <SessionFiles files={files} loading={false} error={null} onOpen={() => {}} onReload={() => {}} />
    );

    fireEvent.click(screen.getByTestId('session-files-group-head'));
    expect(screen.queryAllByTestId('session-files-row')).toHaveLength(0);
    expect(screen.getByTestId('session-files-group-head').getAttribute('aria-expanded')).toBe('false');

    fireEvent.click(screen.getByTestId('session-files-group-head'));
    expect(screen.getAllByTestId('session-files-row')).toHaveLength(2);
  });
});

describe('被删掉的那一档', () => {
  // 同一组里改的与删的混着，组头那句要两档都写出来。
  const files = [file('/w/src/keep.py'), file('/w/src/gone.py', 'deleted')];

  it('带 D 标，名字划掉——颜色不是唯一通道', () => {
    render(
      <SessionFiles files={files} loading={false} error={null} onOpen={() => {}} onReload={() => {}} />
    );

    const badge = screen.getByTestId('session-files-badge-deleted');
    expect(badge.textContent).toBe('D');
    expect(badge.getAttribute('title')).toBe('删掉');
    // 划掉是第二通道：光靠底色，色觉不同的人看不出来。
    expect(screen.getAllByTestId('session-files-row')[1].querySelector('.line-through')).toBeTruthy();
  });

  it('不给按钮也不接点击：文件已经不在，点开只会取不到内容', () => {
    const onOpen = vi.fn();
    render(
      <SessionFiles files={files} loading={false} error={null} onOpen={onOpen} onReload={() => {}} />
    );

    const rows = screen.getAllByTestId('session-files-row');
    expect(rows[1].getAttribute('data-deleted')).toBe('true');
    expect(rows[1].tagName).toBe('DIV');
    expect(rows[1].querySelector('button')).toBeNull();
    // 改过的那一行照旧能点。
    expect(rows[0].tagName).toBe('BUTTON');

    fireEvent.click(rows[1]);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('组头把两档都写出来，没删过的组不多一句「0 个删的」', () => {
    render(
      <SessionFiles
        files={[...files, file('/w/other/x.py', 'created')]}
        loading={false}
        error={null}
        onOpen={() => {}}
        onReload={() => {}}
      />
    );

    const heads = screen.getAllByTestId('session-files-group-head');
    expect(heads[0].textContent).toContain('1 个改的 · 1 个删的');
    expect(heads[1].textContent).toContain('1 个新建');
    expect(heads[1].textContent).not.toContain('0 个删的');
  });
});

describe('取不到与没有不是一件事', () => {
  it('还没取（files 为 null 且在取）：说在数，不说这一场没动过', () => {
    render(
      <SessionFiles files={null} loading error={null} onOpen={() => {}} onReload={() => {}} />
    );

    expect(screen.getByTestId('session-files-loading')).toBeTruthy();
    expect(screen.queryByTestId('session-files-row')).toBeNull();
    expect(screen.getByTestId('session-files').textContent).not.toContain('没有动过文件');
  });

  it('取回来了、确实没动过：把「没有」说清楚', () => {
    render(
      <SessionFiles files={[]} loading={false} error={null} onOpen={() => {}} onReload={() => {}} />
    );

    expect(screen.getByTestId('session-files').textContent).toContain('没有动过文件');
    // 一份都没有时不摆那行下界说明：它说的是「这几个是怎么来的」，一个都没有时没有意义。
    expect(screen.queryByText('0 个文件')).toBeNull();
  });

  it('取不到：原因摆出来，点重试再取一次', () => {
    const onReload = vi.fn();
    render(
      <SessionFiles
        files={null}
        loading={false}
        error="Failed to fetch"
        onOpen={() => {}}
        onReload={onReload}
      />
    );

    expect(screen.getByTestId('session-files').textContent).toContain('Failed to fetch');
    fireEvent.click(screen.getByTestId('session-files-retry'));
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
