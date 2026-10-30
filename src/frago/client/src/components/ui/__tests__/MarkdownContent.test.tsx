/**
 * 回复正文里哪些代码块画成图。
 *
 * 判据只有语言标记：写 `mermaid` 的交给画图组件，其余一律照旧显示成代码。画图组件在
 * 测试环境里取不到 mermaid 脚本，停在「正在画图」那一步——这里只管分流对不对，图画得
 * 怎么样由浏览器里的实测负责。
 */

import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';

import '@/i18n';
import MarkdownContent, { FileLinkContext, parseFileUrl } from '../MarkdownContent';

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

  it('代码块右上角带复制按钮，点击写入剪贴板并在两秒后恢复', async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<MarkdownContent content={'```text\n【问题描述】\n长文本不换行\n```'} />);
    const btn = screen.getByTestId('code-block-copy');
    expect(btn.classList.contains('is-copied')).toBe(false);

    fireEvent.click(btn);
    expect(writeText).toHaveBeenCalledWith('【问题描述】\n长文本不换行');
    expect(btn.classList.contains('is-copied')).toBe(true);

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(btn.classList.contains('is-copied')).toBe(false);
    vi.useRealTimers();
  });
});

describe('MarkdownContent — file:// 本地文件链接', () => {
  it('保留 file:// 地址而非清空为 href=""，解析解码后的路径与行号锚点', () => {
    expect(
      parseFileUrl('file:///home/yammi/%E4%B8%8B%E8%BD%BD/agy.py#L84-L102')
    ).toEqual({
      path: '/home/yammi/下载/agy.py',
      line: 'L84-L102',
    });

    render(
      <MarkdownContent
        content={'见 [`agy.py`](file:///home/yammi/repos/frago/src/frago/agent_driver/drivers/agy.py#L84)'}
      />
    );
    const link = screen.getByRole('link', { name: 'agy.py' });
    expect(link.getAttribute('href')).toBe(
      'file:///home/yammi/repos/frago/src/frago/agent_driver/drivers/agy.py#L84'
    );
    expect(link.getAttribute('data-file-path')).toBe(
      '/home/yammi/repos/frago/src/frago/agent_driver/drivers/agy.py'
    );
    expect(link.getAttribute('data-file-line')).toBe('L84');
    expect(link.getAttribute('target')).toBeNull();
  });

  it('点击 file:// 链接时拦截默认跳转并通知 FileLinkContext 打开页内预览', () => {
    const onFileLink = vi.fn();
    render(
      <FileLinkContext.Provider value={onFileLink}>
        <MarkdownContent
          content={'[routes.ts](file:///home/yammi/repos/frago/src/frago/client/src/routes.ts#L12)'}
        />
      </FileLinkContext.Provider>
    );
    const link = screen.getByRole('link', { name: 'routes.ts' });
    const clickEvent = new MouseEvent('click', { bubbles: true, cancelable: true });
    const prevented = !link.dispatchEvent(clickEvent);
    expect(prevented).toBe(true);
    expect(onFileLink).toHaveBeenCalledWith({
      path: '/home/yammi/repos/frago/src/frago/client/src/routes.ts',
      line: 'L12',
    });
  });

  it('普通 https 链接照旧在新标签页打开', () => {
    render(<MarkdownContent content={'[文档](https://example.com/docs)'} />);
    const link = screen.getByRole('link', { name: '文档' });
    expect(link.getAttribute('href')).toBe('https://example.com/docs');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link, '点击 https 链接不走本地文件回调').toBeTruthy();
    fireEvent.click(link);
  });
});

