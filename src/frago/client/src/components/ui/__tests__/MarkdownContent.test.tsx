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

  it('支持中文、%20 空格、括号、孤立百分号及目录末尾斜杠 file:// 链接并挂上 markdown-file-link 类', () => {
    expect(
      parseFileUrl('file:///Users/frago/My%20Docs/00_%E4%B8%8B%E8%BD%BD(v1)/')
    ).toEqual({
      path: '/Users/frago/My Docs/00_下载(v1)/',
      line: undefined,
    });

    // 含孤立 % 字符时不因 decodeURIComponent 抛异常而放弃解码 %20
    expect(parseFileUrl('file:///Users/frago/100%%20Done/notes.md#L5')).toEqual({
      path: '/Users/frago/100% Done/notes.md',
      line: 'L5',
    });

    const onFileLink = vi.fn();
    render(
      <FileLinkContext.Provider value={onFileLink}>
        <MarkdownContent
          content={
            '目录：[00_下载原件/](file:///Users/frago/.frago/data/test%20dir/00_%E4%B8%8B%E8%BD%BD%E5%8E%9F%E4%BB%B6/) 和代码 [`x.ts`](file:///Users/frago/x.ts)'
          }
        />
      </FileLinkContext.Provider>
    );

    const dirLink = screen.getByRole('link', { name: '00_下载原件/' });
    expect(dirLink.className).toContain('markdown-file-link');
    expect(dirLink.getAttribute('data-file-dir')).toBe('true');
    expect(dirLink.getAttribute('data-file-path')).toBe(
      '/Users/frago/.frago/data/test dir/00_下载原件/'
    );

    const codeLink = screen.getByRole('link', { name: 'x.ts' });
    expect(codeLink.className).toContain('markdown-file-link');
    expect(codeLink.getAttribute('data-file-dir')).toBeNull();
    expect(codeLink.querySelector('code.inline-code')).not.toBeNull();

    fireEvent.click(dirLink);
    expect(onFileLink).toHaveBeenCalledWith({
      path: '/Users/frago/.frago/data/test dir/00_下载原件/',
      line: undefined,
    });
  });
});

describe('MarkdownContent — 表格单元格内 <br> 换行', () => {
  it('把单元格里非 code 节点的 <br> 与 <br/> 渲染成换行元素，保留行内代码里的 <br> 字面量', () => {
    const md = [
      '| 维度 | 具体设计 | 说明 |',
      '|---|---|---|',
      '| **三条调用** | `cmd1`<br>`cmd2`<br/>`cmd3` | 支持 `<br>` 标签换行<br>第二行说明 |',
    ].join('\n');

    const { container } = render(<MarkdownContent content={md} />);
    const cells = container.querySelectorAll('tbody td');
    expect(cells.length).toBe(3);

    // 第二列：两个 <br> 被转换成真 <br> 元素
    expect(cells[1].querySelectorAll('br').length).toBe(2);
    expect(cells[1].querySelectorAll('code.inline-code').length).toBe(3);

    // 第三列：行内代码里的 `<br>` 保持字面量，外层的 <br> 转为真 <br> 元素
    expect(cells[2].querySelectorAll('br').length).toBe(1);
    expect(cells[2].querySelector('code.inline-code')?.textContent).toBe('<br>');
  });
});

describe('MarkdownContent — quote 与 code 自动按页面宽度换行（防止单行无限向右撑开）', () => {
  it('blockquote、pre.code-block、代码块内 code 与 inline-code 均具备自动换行与宽度约束类', () => {
    const longSingleLine =
      '/Users/frago/.frago/data/frago-dev/20261117-details-quote-code-wrap-fix/very_long_unbroken_identifier_without_spaces_that_used_to_grow_infinitely_horizontally';
    const md = [
      `> 引用段落包含超长行内代码 \`${longSingleLine}\``,
      '>',
      '> ```bash',
      `> echo "${longSingleLine}" --flag="${longSingleLine}"`,
      '> ```',
    ].join('\n');

    const { container } = render(<MarkdownContent content={md} />);
    const blockquote = container.querySelector('blockquote');
    const pre = container.querySelector('pre.code-block');
    const blockCode = container.querySelector('pre.code-block code');
    const inlineCode = container.querySelector('code.inline-code');

    expect(blockquote).not.toBeNull();
    expect(blockquote?.className).toContain('min-w-0');
    expect(blockquote?.className).toContain('max-w-full');
    expect(blockquote?.className).toContain('break-words');
    expect(blockquote?.className).toContain('[overflow-wrap:anywhere]');

    expect(pre).not.toBeNull();
    expect(pre?.className).toContain('min-w-0');
    expect(pre?.className).toContain('max-w-full');
    expect(pre?.className).toContain('whitespace-pre-wrap');
    expect(pre?.className).toContain('break-words');
    expect(pre?.className).toContain('[overflow-wrap:anywhere]');

    expect(blockCode).not.toBeNull();
    expect(blockCode?.className).toContain('whitespace-pre-wrap');
    expect(blockCode?.className).toContain('break-words');
    expect(blockCode?.className).toContain('[overflow-wrap:anywhere]');

    expect(inlineCode).not.toBeNull();
    expect(inlineCode?.className).toContain('whitespace-pre-wrap');
    expect(inlineCode?.className).toContain('break-words');
    expect(inlineCode?.className).toContain('[overflow-wrap:anywhere]');
  });
});

describe('MarkdownContent — 标准 GFM 脚注句段引用溯源（[^N]）', () => {
  it('解析标准 GFM [^N] 并渲染 .cite-span、.cite-pill 与 .cite-sources-foot，禁止输出原生 <section data-footnotes>', () => {
    const md = [
      '服务端对路径进行了沙箱校验[^1]，外部文档说明见 RFC[^2]。',
      '',
      '[^1]: [workbench.py](file:///Users/frago/Repos/frago/src/frago/server/routes/workbench.py#L1430-L1455 "仅放行会话触达文件或引用路径")',
      '[^2]: [MDN Security](https://developer.mozilla.org/en-US/docs/Web/Security "同源与外链隔离说明")',
    ].join('\n');

    const { container } = render(<MarkdownContent content={md} />);

    expect(container.querySelector('section[data-footnotes]')).toBeNull();

    const spans = container.querySelectorAll('.cite-span');
    expect(spans.length).toBe(2);
    expect(spans[0].textContent).toContain('服务端对路径进行了沙箱校验');

    const pills = container.querySelectorAll('.cite-pill');
    expect(pills.length).toBe(2);
    expect(pills[0].textContent).toBe('1');
    expect(pills[1].textContent).toBe('2 ↗');
    expect(pills[1].classList.contains('web')).toBe(true);

    const foot = container.querySelector('[data-testid="cite-sources-foot"]');
    expect(foot).not.toBeNull();
    const chips = container.querySelectorAll('.cite-src-chip');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toContain('workbench.py');
    expect(chips[1].textContent).toContain('MDN Security');
  });

  it('严格执行 URI 白名单，拦截 javascript:/data:/vbscript: 为不可点击的 .cite-src-chip.invalid，行内退化为纯文本 [N]', () => {
    const md = [
      '危险脚本测试[^1]，数据协议测试[^2]，VBS 测试[^3]，合法协议[^4]。',
      '',
      '[^1]: [XSS](javascript:alert(1) "bad")',
      '[^2]: [DataURI](data:text/html,<script>alert(1)</script>)',
      '[^3]: [VBS](vbscript:msgbox(1))',
      '[^4]: [LocalFile](file:///tmp/safe.ts#L10)',
    ].join('\n');

    const { container } = render(<MarkdownContent content={md} />);

    const validPills = container.querySelectorAll('.cite-pill');
    expect(validPills.length).toBe(1);
    expect(validPills[0].textContent).toBe('4');

    const invalidChips = container.querySelectorAll('.cite-src-chip.invalid');
    expect(invalidChips.length).toBe(3);
    expect(invalidChips[0].tagName).toBe('SPAN');
    expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(container.querySelector('a[href^="data:"]')).toBeNull();
    expect(container.querySelector('a[href^="vbscript:"]')).toBeNull();
    expect(container.textContent).toContain('[1]');
    expect(container.textContent).toContain('[2]');
    expect(container.textContent).toContain('[3]');
  });

  it('隔离 fenced 代码块、缩进代码块、行内反引号 `[^1]` 与反斜杠转义 \\[^1]，均不解析为引用气泡', () => {
    const md = [
      '行内代码 `[^1]` 与转义 \\[^1] 不解析，下面代码块也不解析：',
      '',
      '```markdown',
      '代码里的句子[^1]',
      '[^1]: [ignored.py](file:///tmp/ignored.py#L1)',
      '```',
      '',
      '    缩进代码块里的[^1]',
      '',
      '正文里的合法引用[^2]。',
      '',
      '[^2]: [real.py](file:///tmp/real.py#L3)',
    ].join('\n');

    const { container } = render(<MarkdownContent content={md} />);

    const pills = container.querySelectorAll('.cite-pill');
    expect(pills.length).toBe(1);
    expect(pills[0].textContent).toBe('2');
    expect(container.querySelectorAll('.cite-src-chip').length).toBe(1);
    expect(container.querySelector('pre.code-block code')?.textContent).toContain('[^1]');
    expect(container.querySelector('code.inline-code')?.textContent).toBe('[^1]');
  });

  it('流式阶段未定义 [^1] 渲染为 .cite-pill.pending；流式结束后未定义退化为纯文本 [^1]；孤立定义仍在底部展示索引条', () => {
    const streamingMd = '正在流式输出[^1]，且转义 \\[^2] 不变。';
    const { container, rerender } = render(
      <MarkdownContent content={streamingMd} streaming={true} />
    );

    const pendingPills = container.querySelectorAll('.cite-pill.pending');
    expect(pendingPills.length).toBe(1);
    expect(pendingPills[0].textContent).toBe('1');

    rerender(<MarkdownContent content={streamingMd} streaming={false} />);
    expect(container.querySelectorAll('.cite-pill').length).toBe(0);
    expect(container.textContent).toContain('[^1]');

    const orphanDefMd = [
      '正文没有引用脚注。',
      '',
      '[^9]: [orphan.ts](file:///tmp/orphan.ts#L5 "孤立定义")',
    ].join('\n');
    rerender(<MarkdownContent content={orphanDefMd} streaming={false} />);
    expect(container.querySelectorAll('.cite-pill').length).toBe(0);
    const footChips = container.querySelectorAll('.cite-src-chip');
    expect(footChips.length).toBe(1);
    expect(footChips[0].textContent).toContain('orphan.ts');
  });

  it('严禁支持已废止的私有标签 [[[!ref_1]]]', () => {
    const legacy = '旧语法 [[[!ref_1]]] 绝不解析为引用胶囊。';
    const { container } = render(<MarkdownContent content={legacy} />);
    expect(container.querySelectorAll('.cite-pill').length).toBe(0);
    expect(container.querySelectorAll('.cite-span').length).toBe(0);
    expect(container.textContent).toContain('[[[!ref_1]]]');
  });
});




