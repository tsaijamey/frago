/**
 * 行内 Markdown —— 只认 `**粗体**` 与 `` `代码` `` 两种记号，产出纯行内元素。
 *
 * 为什么不用 `MarkdownContent`：用它的那些位置外壳是 `<button>`（清单卡、事务行），
 * 按 HTML 规范按钮里只允许行内内容。`MarkdownContent` 会产出 `<p>` / `<ul>` 这类
 * 块级元素，塞进按钮里既是非法嵌套，也会把卡片固定的 clamp 行高打乱。
 *
 * 记号的来源是人的输入：配方描述、技能说明、事务摘要都是人写的，里面常带
 * `**只展示，不计算**` 这种强调。原样印出来就是一对光秃秃的星号，看着像渲染坏了。
 * 输出永远包在一个行内 `<span>` 里，不散成多个并列节点：宿主容器有的是 flex
 * （`.tdp-row-sub` 带 `gap`），有的是 `-webkit-line-clamp` 的盒（配方卡描述），
 * 多出几个兄弟节点会把间距和截断行数一起打乱。
 */
import { type ReactNode } from 'react';

/** 一次扫出全部记号：粗体优先，行内代码次之。 */
const TOKEN_RE = /(\*\*[^*\n]+\*\*|`[^`\n]+`)/g;

interface InlineMarkdownProps {
  /** 允许 null / undefined：调用点常常直接把可空字段递进来。 */
  content: string | null | undefined;
}

/** 行内代码的样式自带：宿主页面不在 `.markdown-content` 里，那边的规则够不着。 */
const CODE_CLASS =
  'font-mono text-[0.9em] px-[0.4em] py-[0.15em] rounded-[3px] bg-[var(--code-bg)] text-[var(--text-primary)]';

export default function InlineMarkdown({ content }: InlineMarkdownProps) {
  if (!content) return null;

  const parts: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  TOKEN_RE.lastIndex = 0;

  for (let m = TOKEN_RE.exec(content); m !== null; m = TOKEN_RE.exec(content)) {
    if (m.index > cursor) parts.push(content.slice(cursor, m.index));
    const token = m[0];
    if (token.startsWith('**')) {
      parts.push(
        <strong key={key++} className="font-semibold text-[var(--text-primary)]">
          {token.slice(2, -2)}
        </strong>,
      );
    } else {
      parts.push(
        <code key={key++} className={CODE_CLASS}>
          {token.slice(1, -1)}
        </code>,
      );
    }
    cursor = m.index + token.length;
  }

  // 一个记号都没认出来时原样返回，省掉多余的一层 span。
  if (cursor === 0) return <>{content}</>;
  if (cursor < content.length) parts.push(content.slice(cursor));
  return <span>{parts}</span>;
}
