/**
 * `InlineMarkdown` 的边界行为。
 *
 * 这个组件接的是人的输入（配方描述、技能说明、事务摘要），所以重点不在「粗体好不好看」，
 * 而在两件容易出事的地方：认不出的写法必须原样吐回去（不能吃掉人的字），以及输出
 * 永远是一个节点（散成多个会把宿主容器的 gap 与截断行数打乱）。
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import InlineMarkdown from '../InlineMarkdown';

describe('InlineMarkdown', () => {
  it('把 **强调** 渲染成粗体，星号不再出现在文本里', () => {
    const { container } = render(<InlineMarkdown content="看板：**只展示，不计算**。" />);
    const strong = container.querySelector('strong');
    expect(strong).not.toBeNull();
    expect(strong!.textContent).toBe('只展示，不计算');
    expect(container.textContent).toBe('看板：只展示，不计算。');
    expect(container.textContent).not.toContain('**');
  });

  it('把 `代码` 渲染成行内 code', () => {
    const { container } = render(<InlineMarkdown content="跑 `uv run frago` 就行" />);
    const code = container.querySelector('code');
    expect(code).not.toBeNull();
    expect(code!.textContent).toBe('uv run frago');
    expect(container.textContent).toBe('跑 uv run frago 就行');
  });

  it('同一段里粗体与代码可以并存', () => {
    const { container } = render(<InlineMarkdown content="**结论**：见 `report.md`" />);
    expect(container.querySelector('strong')!.textContent).toBe('结论');
    expect(container.querySelector('code')!.textContent).toBe('report.md');
    expect(container.textContent).toBe('结论：见 report.md');
  });

  it('没有记号时原样输出，且不多套一层 span', () => {
    const { container } = render(<InlineMarkdown content="一条没有任何记号的普通说明" />);
    expect(container.innerHTML).toBe('一条没有任何记号的普通说明');
  });

  it('跨行不成对时按普通文本处理，绝不吞掉原文', () => {
    // 半截星号是人的输入里真实存在的（写了一半、粘错了）。宁可原样显示。
    const raw = '**没写完的强调\n下一行';
    const { container } = render(<InlineMarkdown content={raw} />);
    expect(container.textContent).toBe(raw);
  });

  it('单个星号不当作记号', () => {
    const { container } = render(<InlineMarkdown content="5 * 3 = 15" />);
    expect(container.querySelector('strong')).toBeNull();
    expect(container.textContent).toBe('5 * 3 = 15');
  });

  it('空内容不渲染任何东西', () => {
    const { container } = render(<InlineMarkdown content="" />);
    expect(container.innerHTML).toBe('');
  });

  it('有记号时输出收在一个节点里，不散成多个兄弟节点', () => {
    // 宿主容器有 flex + gap 的，也有 -webkit-line-clamp 的盒，多一个兄弟节点就会走形。
    const { container } = render(<InlineMarkdown content="前 **中** 后" />);
    expect(container.childNodes).toHaveLength(1);
  });
});
