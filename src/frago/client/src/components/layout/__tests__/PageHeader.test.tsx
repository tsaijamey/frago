/**
 * 统一页头的用例：守的是「一个标题、至多一个主动作、展开时退成中性、没有计数就不留空」
 * 这几条规矩本身，不是具体长什么样。
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import PageHeader from '../PageHeader';

describe('PageHeader', () => {
  it('只渲染一个 h1', () => {
    render(<PageHeader title="Todos" meta="81 open" />);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Todos');
  });

  it('有主动作时恰好一个带主动作样式的按钮', () => {
    const { container } = render(
      <PageHeader
        title="Todos"
        secondary={
          <button type="button" className="page-header-btn">
            Categories
          </button>
        }
        primary={{ label: 'Add', onClick: vi.fn() }}
      />
    );
    expect(container.querySelectorAll('.page-header-primary')).toHaveLength(1);
    expect(screen.getByTestId('page-header-primary').textContent).toBe('Add');
  });

  it('pressed 时主动作样式撤掉，退成中性', () => {
    const { container } = render(
      <PageHeader title="Todos" primary={{ label: 'Add', onClick: vi.fn(), pressed: true }} />
    );
    expect(container.querySelectorAll('.page-header-primary')).toHaveLength(0);
    expect(screen.getByTestId('page-header-primary').className).toContain('page-header-btn--pressed');
  });

  it('没有 meta 时不渲染空节点', () => {
    const { container } = render(<PageHeader title="Settings" />);
    expect(container.querySelector('.page-header-meta')).toBeNull();
    expect(container.querySelector('.page-header-actions')).toBeNull();
  });
});
