import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import MermaidDiagram from './MermaidDiagram';

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * 语言标记写 `mermaid` 的代码块画成图，其余照旧。
 *
 * 在 `pre` 这一层接管而不是在 `code` 里：图是块级的，落在 `<pre>` 里会继承等宽字与
 * 保留空白，还会套上代码块的底色和内距。
 */
function mermaidSource(node: unknown): string | null {
  const code = (node as { children?: unknown[] } | undefined)?.children?.[0] as
    | { tagName?: string; properties?: { className?: unknown }; children?: { value?: unknown }[] }
    | undefined;
  if (code?.tagName !== 'code') return null;
  const classes = code.properties?.className;
  if (!Array.isArray(classes) || !classes.includes('language-mermaid')) return null;
  return (code.children ?? []).map((c) => (typeof c.value === 'string' ? c.value : '')).join('');
}

const components: Components = {
  pre({ children, node, ...props }) {
    const diagram = mermaidSource(node);
    if (diagram !== null) return <MermaidDiagram source={diagram.trimEnd()} />;
    return (
      <pre className="code-block" {...props}>
        {children}
      </pre>
    );
  },
  code({ children, ...props }) {
    const isInline = !props.className;
    if (isInline) {
      return (
        <code className="inline-code" {...props}>
          {children}
        </code>
      );
    }
    return <code {...props}>{children}</code>;
  },
  a({ href, children, ...props }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    );
  },
};

export default function MarkdownContent({ content, className = '' }: MarkdownContentProps) {
  return (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
