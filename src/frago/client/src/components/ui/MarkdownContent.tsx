import {
  Children,
  Fragment,
  cloneElement,
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from 'react';
import { Check, Copy } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import MermaidDiagram from './MermaidDiagram';
import {
  CitationInteractionContext,
  createRemarkCitationsPlugin,
  parseFileUrl,
  parseFootnoteDefinitionsFromMarkdown,
  type CiteDefinition,
  type FileLinkTarget,
} from './citations';

export { parseFileUrl, type FileLinkTarget };

/**
 * 会话记录流等宿主向内层 Markdown 注入的本地文件链接打开回调。
 * 未注入时点击 `file://` 链接只拦截浏览器默认跳转。
 */
export const FileLinkContext = createContext<((target: FileLinkTarget) => void) | null>(null);

const CitationDefsContext = createContext<Map<string, CiteDefinition>>(new Map());

interface MarkdownContentProps {
  content: string;
  className?: string;
  onFileLinkClick?: (target: FileLinkTarget) => void;
  /** 仅最后一条仍在流式输出的 agent 消息传 `true`，启用未定义 `[^N]` 中性占位。 */
  streaming?: boolean;
}

/**
 * `react-markdown` 默认白名单只放行 `http/https/irc/ircs/mailto/xmpp`，会把 `file://` 清成空串 `""`，
 * 导致浏览器把 `<a href="">` 解析成当前页自身地址（`http://localhost:8093/`）。
 * 这里保留 `file://` 地址交由链接组件拦截，其余协议照旧走默认白名单。
 */
export function markdownUrlTransform(value: string): string {
  const trimmed = value.trim();
  if (/^file:\/\//i.test(trimmed)) return trimmed;
  return defaultUrlTransform(value);
}

function MarkdownLink({
  href,
  children,
  onClick,
  ...props
}: ComponentPropsWithoutRef<'a'> & { node?: unknown }) {
  const onFileLink = useContext(FileLinkContext);
  const { node: _node, className, ...rest } = props;
  const fileTarget = parseFileUrl(href);
  if (fileTarget) {
    const hint = fileTarget.line ? `${fileTarget.path}#${fileTarget.line}` : fileTarget.path;
    const isDirHint = fileTarget.path.endsWith('/') || fileTarget.path.endsWith('\\');
    const mergedClass = ['markdown-file-link', className].filter(Boolean).join(' ');
    return (
      <a
        href={href}
        data-file-path={fileTarget.path}
        data-file-line={fileTarget.line}
        data-file-dir={isDirHint ? 'true' : undefined}
        title={rest.title ?? hint}
        {...rest}
        className={mergedClass}
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
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={onClick}
      className={className}
      {...rest}
    >
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
      <pre
        ref={preRef}
        className="code-block min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
        {...props}
      >
        {children}
      </pre>
    </div>
  );
}

const BR_TAG_RE = /<br\s*\/?>/i;
const BR_SPLIT_RE = /<br\s*\/?>/gi;

/**
 * 表格单元格里常以 `<br>` / `<br/>` 拆出多行命令或条目，而 `react-markdown` 默认不挂
 * `rehype-raw`，会把 `<br>` 当纯文本吐出来。这里只把单元格内非 `code` 节点里的 `<br>`
 * 转成真正的换行，行内代码里的 `` `<br>` `` 字面量照旧保留。
 */
function renderCellChildren(children: ReactNode): ReactNode {
  return Children.map(children, (child, childIdx) => {
    if (typeof child === 'string') {
      if (!BR_TAG_RE.test(child)) return child;
      const parts = child.split(BR_SPLIT_RE);
      return parts.map((part, partIdx) =>
        partIdx === 0 ? (
          part
        ) : (
          <Fragment key={`br-${childIdx}-${partIdx}`}>
            <br />
            {part}
          </Fragment>
        )
      );
    }
    if (isValidElement<{ children?: ReactNode; node?: { tagName?: string } }>(child)) {
      const tagName = child.props.node?.tagName;
      if (child.type === 'code' || tagName === 'code' || !child.props.children) {
        return child;
      }
      return cloneElement(child, undefined, renderCellChildren(child.props.children));
    }
    return child;
  });
}

function CiteSpanComponent({
  children,
  node: _node,
  ...props
}: ComponentPropsWithoutRef<'span'> & {
  node?: unknown;
  'data-cite-id'?: string;
}) {
  const citeId = props['data-cite-id'] ?? '';
  const defsById = useContext(CitationDefsContext);
  const interaction = useContext(CitationInteractionContext);
  const onFileLink = useContext(FileLinkContext);
  const def = citeId ? defsById.get(citeId) : undefined;
  const isActive = Boolean(def && interaction?.activeCiteId === def.id);
  const className = `cite-span${isActive ? ' active' : ''}`;

  return (
    <span
      className={className}
      data-cite-id={citeId}
      onMouseEnter={(e) => {
        if (def) interaction?.onCiteHover(def, e.currentTarget);
      }}
      onMouseLeave={() => {
        interaction?.onCiteLeave();
      }}
      onClick={(e) => {
        if (!def) return;
        e.stopPropagation();
        if (interaction) {
          interaction.onCiteClick(def, e.currentTarget);
        } else if (def.kind === 'local' && def.filePath) {
          onFileLink?.({ path: def.filePath, line: def.line });
        }
      }}
    >
      {children}
    </span>
  );
}

function CitePillComponent({
  node: _node,
  ...props
}: {
  node?: unknown;
  'data-cite-id'?: string;
  'data-cite-label'?: string;
  'data-cite-kind'?: string;
}) {
  const citeId = props['data-cite-id'] ?? '';
  const label = props['data-cite-label'] ?? citeId;
  const defsById = useContext(CitationDefsContext);
  const interaction = useContext(CitationInteractionContext);
  const onFileLink = useContext(FileLinkContext);
  const def = citeId ? defsById.get(citeId) : undefined;
  const kind = def?.kind ?? props['data-cite-kind'];
  const isWeb = kind === 'web';
  const isActive = Boolean(def && interaction?.activeCiteId === def.id);
  const className = `cite-pill${isWeb ? ' web' : ''}${isActive ? ' active' : ''}`;

  return (
    <button
      type="button"
      className={className}
      data-cite-id={citeId}
      data-testid={`cite-pill-${citeId}`}
      aria-label={def ? `[${label}] ${def.title}` : `[${label}]`}
      onMouseEnter={(e) => {
        if (def) interaction?.onCiteHover(def, e.currentTarget);
      }}
      onMouseLeave={() => {
        interaction?.onCiteLeave();
      }}
      onClick={(e) => {
        if (!def) return;
        e.stopPropagation();
        if (interaction) {
          interaction.onCiteClick(def, e.currentTarget);
        } else if (def.kind === 'local' && def.filePath) {
          onFileLink?.({ path: def.filePath, line: def.line });
        }
      }}
    >
      {label}
      {isWeb ? ' ↗' : ''}
    </button>
  );
}

function CitePendingComponent({
  node: _node,
  ...props
}: {
  node?: unknown;
  'data-cite-pending'?: string;
}) {
  const label = props['data-cite-pending'] ?? '';
  return (
    <span
      className="cite-pill pending"
      data-cite-pending={label}
      data-testid={`cite-pill-pending-${label}`}
    >
      {label}
    </span>
  );
}

const components = {
  pre: CodeBlockPre,
  blockquote({ children, node: _node, className, ...props }: ComponentPropsWithoutRef<'blockquote'> & { node?: unknown }) {
    return (
      <blockquote
        className={`min-w-0 max-w-full break-words [overflow-wrap:anywhere]${className ? ` ${className}` : ''}`}
        {...props}
      >
        {children}
      </blockquote>
    );
  },
  code({ children, className, ...props }: ComponentPropsWithoutRef<'code'> & { node?: unknown }) {
    const isInline = !className;
    if (isInline) {
      return (
        <code
          className="inline-code whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code
        className={`${className} whitespace-pre-wrap break-words [overflow-wrap:anywhere]`}
        {...props}
      >
        {children}
      </code>
    );
  },
  // 表格外包一层能横向滚的框：窄栏里放不下时在框内滚，不撑宽整栏。
  table({ children, node: _node, ...props }: ComponentPropsWithoutRef<'table'> & { node?: unknown }) {
    return (
      <div className="table-scroll">
        <table {...props}>{children}</table>
      </div>
    );
  },
  th({ children, node: _node, ...props }: ComponentPropsWithoutRef<'th'> & { node?: unknown }) {
    return <th {...props}>{renderCellChildren(children)}</th>;
  },
  td({ children, node: _node, ...props }: ComponentPropsWithoutRef<'td'> & { node?: unknown }) {
    return <td {...props}>{renderCellChildren(children)}</td>;
  },
  a: MarkdownLink,
  'frago-cite-span': CiteSpanComponent,
  'frago-cite-pill': CitePillComponent,
  'frago-cite-pending': CitePendingComponent,
} as Components;

export default function MarkdownContent({
  content,
  className = '',
  onFileLinkClick,
  streaming = false,
}: MarkdownContentProps) {
  const { t } = useTranslation();
  const inherited = useContext(FileLinkContext);
  const handler = onFileLinkClick ?? inherited;
  const citeInteraction = useContext(CitationInteractionContext);

  const definitions = useMemo(() => parseFootnoteDefinitionsFromMarkdown(content), [content]);
  const defsById = useMemo(() => new Map(definitions.map((d) => [d.id, d])), [definitions]);
  const remarkPlugins = useMemo(
    () => [remarkGfm, createRemarkCitationsPlugin({ definitions, streaming, rawSource: content })],
    [definitions, streaming, content]
  );

  const body = (
    <CitationDefsContext.Provider value={defsById}>
      <div className={`markdown-content ${className}`}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          urlTransform={markdownUrlTransform}
          components={components}
        >
          {content}
        </ReactMarkdown>
        {definitions.length > 0 ? (
          <div className="cite-sources-foot" data-testid="cite-sources-foot">
            <span className="cite-sources-label">
              {t('workbench.citations.sourcesLabel', { count: definitions.length })}
            </span>
            {definitions.map((def) =>
              def.kind === 'invalid' ? (
                <span
                  key={def.id}
                  className="cite-src-chip invalid"
                  data-testid={`cite-src-chip-${def.id}`}
                  title={t('workbench.citations.unsafeBadge')}
                >
                  <span className="cite-src-num">[{def.label}]</span>
                  <span className="cite-src-name">{def.title}</span>
                </span>
              ) : (
                <button
                  key={def.id}
                  type="button"
                  className={`cite-src-chip${citeInteraction?.activeCiteId === def.id ? ' active' : ''}`}
                  data-testid={`cite-src-chip-${def.id}`}
                  onMouseEnter={(e) => citeInteraction?.onCiteHover(def, e.currentTarget)}
                  onMouseLeave={() => citeInteraction?.onCiteLeave()}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (citeInteraction) {
                      citeInteraction.onCiteClick(def, e.currentTarget);
                    } else if (def.kind === 'local' && def.filePath) {
                      handler?.({ path: def.filePath, line: def.line });
                    }
                  }}
                >
                  <span className="cite-src-num">[{def.label}]</span>
                  <span className="cite-src-name">{def.title}</span>
                  {def.line ? <span className="cite-src-loc">:{def.line}</span> : null}
                  {def.kind === 'web' ? <span className="cite-src-loc">↗</span> : null}
                </button>
              )
            )}
          </div>
        ) : null}
      </div>
    </CitationDefsContext.Provider>
  );
  return handler ? (
    <FileLinkContext.Provider value={handler}>{body}</FileLinkContext.Provider>
  ) : (
    body
  );
}

