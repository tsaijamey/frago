/**
 * 回复正文里哪些代码块画成图。
 *
 * 判据只有语言标记：写 `mermaid` 的交给画图组件，其余一律照旧显示成代码。画图组件在
 * 测试环境里取不到 mermaid 脚本，停在「正在画图」那一步——这里只管分流对不对，图画得
 * 怎么样由浏览器里的实测负责。
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import '@/i18n';
import MarkdownContent from '../MarkdownContent';

describe('MarkdownContent — mermaid 代码块', () => {
  it('语言标记写 mermaid 的代码块交给画图组件，不再显示成代码', () => {
    const { container } = render(
      <MarkdownContent content={'```mermaid\nflowchart LR\n  A --> B\n```'} />
    );
    expect(screen.queryByTestId('mermaid-diagram')).not.toBeNull();
    expect(container.querySelector('pre')).toBeNull();
  });

  it('别的语言照旧是代码块', () => {
    const { container } = render(<MarkdownContent content={'```python\nprint(1)\n```'} />);
    expect(screen.queryByTestId('mermaid-diagram')).toBeNull();
    expect(container.querySelector('pre.code-block code')?.textContent).toContain('print(1)');
  });

  it('没写语言标记的代码块也照旧，不被当成图', () => {
    const { container } = render(<MarkdownContent content={'```\nflowchart LR\n```'} />);
    expect(screen.queryByTestId('mermaid-diagram')).toBeNull();
    expect(container.querySelector('pre')).not.toBeNull();
  });
});
