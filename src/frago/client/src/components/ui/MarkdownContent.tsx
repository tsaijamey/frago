import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
} from 'react';
import { Check, Copy } from 'lucide-react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import MermaidDiagram from './MermaidDiagram';

export interface FileLinkTarget {
  /** 解码后的本地文件绝对路径（不含 `file://` 前缀与 `#L...` 行号锚点）。 */
  path: string;
  /** 链接末尾附带的行号锚点（如 `L84`、`L314-L368`）。 */
  line?: string;
}

/**
 * 会话记录流等宿主向内层 Markdown 注入的本地文件链接打开回调。
 * 未注入时点击 `file://` 链接只拦截浏览器默认跳转。
 */
export const FileLinkContext = createContext<((target: FileLinkTarget) => void) | null>(null);

interface MarkdownContentProps {
  content: string;
  className?: string;
  onFileLinkClick?: (target: FileLinkTarget) => void;
}

/**
 * `react-markdown` 默认白名单只放行 `http/https/irc/ircs/mailto/xmpp`，会把 `file://` 清成空串 `""`，
 * 导致浏览器把 `<a href="">` 解析成当前页自身地址（`http://localhost:8093/`）。
 * 这里保留 `file://` 地址交由链接组件拦截，其余协议照旧走默认白名单。
 */
export function markdownUrlTransform(value: string): string {
  if (/^file:\/\//i.test(value)) return value;
  return defaultUrlTransform(value);
}

/**
 * 从 `file://` 链接里拆出本地文件路径与可选的行号锚点（`#L84`、`#L314-L368` 或末尾 `:42`）。
 */
export function parseFileUrl(href: string | undefined): FileLinkTarget | null {
  if (!href || !/^file:\/\//i.test(href)) return null;
  let rest = href.replace(/^file:\/\/(?:localhost)?/i, '');
  let hash = '';
  const hashIdx = rest.indexOf('#');
  if (hashIdx !== -1) {
    hash = rest.slice(hashIdx + 1);
    rest = rest.slice(0, hashIdx);
  }
  const queryIdx = rest.indexOf('?');
  if (queryIdx !== -1) {
    rest = rest.slice(0, queryIdx);
  }
  try {
    rest = decodeURIComponent(rest);
  } catch {
    // 百分号编码不完整时保留原串
  }
  if (/^\/[A-Za-z]:[\\/]/.test(rest)) {
    rest = rest.slice(1);
  }
  let line: string | undefined;
  if (hash) {
    const m = /^L?(\d+(?:-L?\d+)?)$/i.exec(hash.trim());
    if (m) line = `L${m[1].toUpperCase()}`;
  } else {
    const suffix = /:(\d+)(?::\d+)?$/.exec(rest);
    if (suffix) {
      line = `L${suffix[1]}`;
      rest = rest.slice(0, suffix.index);
    }
  }
  const path = rest.trim();
  if (!path) return null;
  return line ? { path, line } : { path };
}

function MarkdownLink({
  href,
  children,
  onClick,
  ...props
}: ComponentPropsWithoutRef<'a'> & { node?: unknown }) {
  const onFileLink = useContext(FileLinkContext);
  const { node: _node, ...rest } = props;
  const fileTarget = parseFileUrl(href);
  if (fileTarget) {
    const hint = fileTarget.line ? `${fileTarget.path}#${fileTarget.line}` : fileTarget.path;
    return (
      <a
        href={href}
        data-file-path={fileTarget.path}
        data-file-line={fileTarget.line}
        title={rest.title ?? hint}
        {...rest}
        onClick={(e) => {
          onClick?.(e);
          e.preventDefault();
          onFileLink?.(fileTarget);
        }}
      >
        {children}
      </a>
    );
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" onClick={onClick} {...rest}>
      {children}
    </a>
  );
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

function extractNodeText(node: unknown): string {
  if (!node || typeof node !== 'object') return '';
  const n = node as { value?: unknown; children?: unknown[] };
  if (typeof n.value === 'string') return n.value;
  if (Array.isArray(n.children)) {
    return n.children.map(extractNodeText).join('');
  }
  return '';
}

function CodeBlockPre({
  children,
  node,
  ...props
}: ComponentPropsWithoutRef<'pre'> & { node?: unknown }) {
  const [copied, setCopied] = useState(false);
  const preRef = useRef<HTMLPreElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const diagram = mermaidSource(node);
  if (diagram !== null) return <MermaidDiagram source={diagram.trimEnd()} />;

  const handleCopy = () => {
    const raw = extractNodeText(node) || preRef.current?.textContent || '';
    const text = raw.replace(/\r?\n$/, '');
    if (!navigator.clipboard?.writeText) return;
    void navigator.clipboard.writeText(text);
    setCopied(true);
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      setCopied(false);
      timerRef.current = null;
    }, 2000);
  };

  return (
    <div className="code-block-wrap">
      <button
        type="button"
        className={`code-block-copy${copied ? ' is-copied' : ''}`}
        onClick={handleCopy}
        aria-label={copied ? 'Copied' : 'Copy'}
        title={copied ? 'Copied' : 'Copy'}
        data-testid="code-block-copy"
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
      <pre ref={preRef} className="code-block" {...props}>
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  pre: CodeBlockPre,
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
  // 表格外包一层能横向滚的框：窄栏里放不下时在框内滚，不撑宽整栏。
  table({ children, node: _node, ...props }) {
    return (
      <div className="table-scroll">
        <table {...props}>{children}</table>
      </div>
    );
  },
  a: MarkdownLink,
};

export default function MarkdownContent({
  content,
  className = '',
  onFileLinkClick,
}: MarkdownContentProps) {
  const inherited = useContext(FileLinkContext);
  const handler = onFileLinkClick ?? inherited;
  const body = (
    <div className={`markdown-content ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={markdownUrlTransform}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
  return handler ? (
    <FileLinkContext.Provider value={handler}>{body}</FileLinkContext.Provider>
  ) : (
    body
  );
}

