import { createContext } from 'react';

export interface FileLinkTarget {
  /** 解码后的本地文件绝对路径（不含 `file://` 前缀与 `#L...` 行号锚点）。 */
  path: string;
  /** 链接末尾附带的行号锚点（如 `L84`、`L314-L368`）。 */
  line?: string;
}

export type CitationKind = 'local' | 'web' | 'invalid';

export interface CiteDefinition {
  /** 脚注原始 identifier（如 `"1"`、`"note-a"`，小写归一化用于索引匹配）。 */
  id: string;
  /** 展示标签（通常为数字 `"1"` 或原 label）。 */
  label: string;
  /** 可读来源标题。 */
  title: string;
  /** 校验通过后的原始 URI；非法协议置空串。 */
  uri: string;
  /** 截取的原文摘录（来自链接 title 或尾部引文）。 */
  excerpt: string;
  /** 来源分类：仅放行 `file:///abs` (`local`) 与 `http(s)://` (`web`)。 */
  kind: CitationKind;
  /** 本地文件路径（`kind === 'local'` 时存在）。 */
  filePath?: string;
  /** 起始行号（1-based）。 */
  hlStart?: number;
  /** 结束行号（1-based）。 */
  hlEnd?: number;
  /** 行号锚点串（如 `L69-L74`）。 */
  line?: string;
  /** 是否被危险协议/缺失 URL 拦截。 */
  unsafeUri?: boolean;
}

export interface CitationInteractionContextValue {
  activeCiteId: string | null;
  onCiteHover: (def: CiteDefinition, anchorEl: HTMLElement) => void;
  onCiteLeave: () => void;
  onCiteClick: (def: CiteDefinition, anchorEl?: HTMLElement) => void;
}

export const CitationInteractionContext =
  createContext<CitationInteractionContextValue | null>(null);

function safeDecodeUri(raw: string): string {
  return raw.replace(/(?:%[0-9A-Fa-f]{2})+/g, (seq) => {
    try {
      return decodeURIComponent(seq);
    } catch {
      return seq;
    }
  });
}

/**
 * 解析 `#L69` / `#L69-L74` / `L69` / `L69-L74` 为 1-based 整数区间。
 */
export function parseLineAnchorRange(
  line?: string | null
): { startLine: number; endLine: number } | null {
  if (!line) return null;
  const trimmed = line.trim().replace(/^#/, '');
  const m = /^L?(\d+)(?:-L?(\d+))?$/i.exec(trimmed);
  if (!m) return null;
  const start = Number.parseInt(m[1], 10);
  const end = m[2] ? Number.parseInt(m[2], 10) : start;
  if (!Number.isFinite(start) || start <= 0) return null;
  const safeEnd = Number.isFinite(end) && end >= start ? end : start;
  return { startLine: start, endLine: safeEnd };
}

/**
 * 从 `file://` 链接里拆出本地文件路径与可选的行号锚点（`#L84`、`#L314-L368` 或末尾 `:42`）。
 */
export function parseFileUrl(href: string | undefined): FileLinkTarget | null {
  if (!href) return null;
  const trimmed = href.trim();
  if (!/^file:\/\//i.test(trimmed)) return null;
  let rest = trimmed.replace(/^file:\/\/(?:localhost)?/i, '');
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
  rest = safeDecodeUri(rest);
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

/**
 * 严格来源白名单校验：仅放行 `file:///绝对路径`、`https://`、`http://`。
 * 显式拒绝 `javascript:`、`data:`、`vbscript:`、空串及其他未知协议。
 */
export function validateCitationUri(rawUri: string | undefined | null): {
  kind: CitationKind;
  uri: string;
  filePath?: string;
  line?: string;
  hlStart?: number;
  hlEnd?: number;
  unsafeUri: boolean;
} {
  if (!rawUri) {
    return { kind: 'invalid', uri: '', unsafeUri: true };
  }
  const trimmed = rawUri.trim();
  if (!trimmed) {
    return { kind: 'invalid', uri: '', unsafeUri: true };
  }
  const schemeMatch = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(trimmed);
  if (!schemeMatch) {
    return { kind: 'invalid', uri: '', unsafeUri: true };
  }
  const scheme = schemeMatch[1].toLowerCase();
  if (scheme === 'https' || scheme === 'http') {
    try {
      const parsed = new URL(trimmed);
      if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
        return { kind: 'invalid', uri: '', unsafeUri: true };
      }
      return { kind: 'web', uri: trimmed, unsafeUri: false };
    } catch {
      return { kind: 'invalid', uri: '', unsafeUri: true };
    }
  }
  if (scheme === 'file') {
    const target = parseFileUrl(trimmed);
    if (!target) {
      return { kind: 'invalid', uri: '', unsafeUri: true };
    }
    const isAbs = target.path.startsWith('/') || /^[A-Za-z]:[\\/]/.test(target.path);
    if (!isAbs) {
      return { kind: 'invalid', uri: '', unsafeUri: true };
    }
    const range = parseLineAnchorRange(target.line);
    return {
      kind: 'local',
      uri: trimmed,
      filePath: target.path,
      line: target.line,
      hlStart: range?.startLine,
      hlEnd: range?.endLine,
      unsafeUri: false,
    };
  }
  return { kind: 'invalid', uri: '', unsafeUri: true };
}

interface ParsedLinkBody {
  title: string;
  url: string;
  excerpt: string;
}

/**
 * 从单行或多行合并后的 GFM 脚注定义正文里提取 `[title](url "excerpt")` 或裸 URL。
 */
function parseFootnoteDefBody(rawBody: string): ParsedLinkBody {
  const body = rawBody.trim();
  // [title](url "excerpt") 或 [title](url 'excerpt') 或 [title](<url> "excerpt")
  if (body.startsWith('[')) {
    let depth = 0;
    let labelEnd = -1;
    for (let i = 0; i < body.length; i += 1) {
      const ch = body[i];
      if (ch === '\\') {
        i += 1;
        continue;
      }
      if (ch === '[') depth += 1;
      else if (ch === ']') {
        depth -= 1;
        if (depth === 0) {
          labelEnd = i;
          break;
        }
      }
    }
    if (labelEnd > 0 && body[labelEnd + 1] === '(') {
      const title = body.slice(1, labelEnd).trim();
      let parenDepth = 0;
      let parenEnd = -1;
      let inQuote: '"' | "'" | null = null;
      for (let i = labelEnd + 1; i < body.length; i += 1) {
        const ch = body[i];
        if (ch === '\\') {
          i += 1;
          continue;
        }
        if (inQuote) {
          if (ch === inQuote) inQuote = null;
          continue;
        }
        if (ch === '"' || ch === "'") {
          inQuote = ch;
          continue;
        }
        if (ch === '(') parenDepth += 1;
        else if (ch === ')') {
          parenDepth -= 1;
          if (parenDepth === 0) {
            parenEnd = i;
            break;
          }
        }
      }
      if (parenEnd > labelEnd + 1) {
        const inner = body.slice(labelEnd + 2, parenEnd).trim();
        let url = inner;
        let excerpt = '';
        const titleMatch = /^(<[^>]+>|\S+)\s+(?:"([\s\S]*)"|'([\s\S]*)')$/.exec(inner);
        if (titleMatch) {
          url = titleMatch[1];
          excerpt = (titleMatch[2] ?? titleMatch[3] ?? '').replace(/\\(["'])/g, '$1').trim();
        }
        if (url.startsWith('<') && url.endsWith('>')) {
          url = url.slice(1, -1).trim();
        }
        const trailing = body.slice(parenEnd + 1).trim();
        if (!excerpt && trailing) {
          excerpt = trailing.replace(/^[—\-:：\s]+/, '').trim();
        }
        return { title: title || url, url, excerpt };
      }
    }
  }
  const bareUrlMatch = /^<?((?:https?|file|javascript|data|vbscript):[^\s>]+)>?(?:\s+(.*))?$/i.exec(
    body
  );
  if (bareUrlMatch) {
    const url = bareUrlMatch[1];
    const rest = (bareUrlMatch[2] ?? '').trim();
    return { title: url, url, excerpt: rest };
  }
  return { title: body, url: '', excerpt: '' };
}

/**
 * 在忽略围栏代码块与缩进代码块的前提下，提取全部标准 GFM 脚注定义 `[^N]: ...`。
 */
export function parseFootnoteDefinitionsFromMarkdown(content: string): CiteDefinition[] {
  if (!content || !content.includes('[^')) return [];
  const lines = content.split(/\r?\n/);
  const defs: CiteDefinition[] = [];
  const seen = new Map<string, number>();

  let fenceChar: '`' | '~' | null = null;
  let fenceLen = 0;

  let currentId: string | null = null;
  let currentLabel = '';
  let currentChunks: string[] = [];

  const flushCurrent = () => {
    if (!currentId) return;
    const rawBody = currentChunks.join(' ').trim();
    const parsed = parseFootnoteDefBody(rawBody);
    const checked = validateCitationUri(parsed.url);
    const fallbackTitle =
      checked.filePath?.split(/[\\/]/).filter(Boolean).pop() ||
      checked.uri ||
      parsed.title ||
      `[${currentLabel}]`;
    const def: CiteDefinition = {
      id: currentId,
      label: currentLabel,
      title: parsed.title || fallbackTitle,
      uri: checked.uri,
      excerpt: parsed.excerpt,
      kind: checked.kind,
      filePath: checked.filePath,
      hlStart: checked.hlStart,
      hlEnd: checked.hlEnd,
      line: checked.line,
      unsafeUri: checked.unsafeUri,
    };
    const existingIdx = seen.get(currentId);
    if (existingIdx === undefined) {
      seen.set(currentId, defs.length);
      defs.push(def);
    } else {
      defs[existingIdx] = def;
    }
    currentId = null;
    currentLabel = '';
    currentChunks = [];
  };

  for (const line of lines) {
    const fenceMatch = /^(?: {0,3})(`{3,}|~{3,})/.exec(line);
    if (fenceMatch) {
      const marker = fenceMatch[1];
      if (!fenceChar) {
        flushCurrent();
        fenceChar = marker[0] as '`' | '~';
        fenceLen = marker.length;
        continue;
      }
      if (marker[0] === fenceChar && marker.length >= fenceLen && line.trim() === marker) {
        fenceChar = null;
        fenceLen = 0;
        continue;
      }
    }
    if (fenceChar) continue;

    // 缩进代码块（非当前脚注续行时）
    if (!currentId && /^(?: {4}|\t)/.test(line)) {
      continue;
    }

    const defMatch = /^ {0,3}\[\^([A-Za-z0-9_-]{1,32})\]:\s*(.*)$/.exec(line);
    if (defMatch) {
      flushCurrent();
      currentLabel = defMatch[1];
      currentId = currentLabel.toLowerCase();
      if (defMatch[2].trim()) {
        currentChunks.push(defMatch[2].trim());
      }
      continue;
    }

    if (currentId) {
      if (!line.trim()) {
        // 空行结束当前脚注，除非后续缩进续行；这里简洁收口避免吞掉正文段落
        flushCurrent();
      } else if (/^(?: {2,}|\t)/.test(line)) {
        currentChunks.push(line.trim());
      } else {
        flushCurrent();
      }
    }
  }
  flushCurrent();
  return defs;
}

// ── Remark AST Plugin ────────────────────────────────────────────────────

interface MdastPosition {
  start?: { offset?: number };
  end?: { offset?: number };
}

interface MdastNode {
  type: string;
  value?: string;
  identifier?: string;
  label?: string;
  url?: string;
  title?: string | null;
  position?: MdastPosition;
  children?: MdastNode[];
  data?: {
    hName?: string;
    hProperties?: Record<string, unknown>;
  };
}

function extractPlainText(node: MdastNode): string {
  if (typeof node.value === 'string') return node.value;
  if (Array.isArray(node.children)) {
    return node.children.map(extractPlainText).join('');
  }
  return '';
}

function findFirstLink(node: MdastNode): MdastNode | null {
  if (node.type === 'link') return node;
  if (!Array.isArray(node.children)) return null;
  for (const child of node.children) {
    const found = findFirstLink(child);
    if (found) return found;
  }
  return null;
}

/**
 * 判断文本节点内从右往左最近一个分句断点（中文/英文句号、分号、逗号、换行）。
 * 返回应切入 `.cite-span` 的起始字符下标；返回 -1 表示整段节点都属于当前分句。
 */
function findClauseSplitIndex(text: string): number {
  for (let i = text.length - 1; i >= 0; i -= 1) {
    const ch = text[i];
    if (ch === '。' || ch === '；' || ch === ';' || ch === '，' || ch === '\n') {
      return i + 1;
    }
    if (ch === ',' && (i === text.length - 1 || /\s|[\u4e00-\u9fff]/.test(text[i + 1]))) {
      return i + 1;
    }
    if (ch === '.' && (i === text.length - 1 || /\s/.test(text[i + 1]))) {
      return i + 1;
    }
  }
  return -1;
}

const WRAPPABLE_INLINE_TYPES = new Set([
  'text',
  'inlineCode',
  'strong',
  'emphasis',
  'delete',
]);

function makeCiteSpan(citeId: string, children: MdastNode[]): MdastNode {
  return {
    type: 'fragoCiteSpan',
    children,
    data: {
      hName: 'frago-cite-span',
      hProperties: {
        'data-cite-id': citeId,
      },
    },
  };
}

function makeCitePill(citeId: string, label: string, kind: CitationKind): MdastNode {
  return {
    type: 'fragoCitePill',
    children: [],
    data: {
      hName: 'frago-cite-pill',
      hProperties: {
        'data-cite-id': citeId,
        'data-cite-label': label,
        'data-cite-kind': kind,
      },
    },
  };
}

function makeCitePending(label: string): MdastNode {
  return {
    type: 'fragoCitePending',
    children: [],
    data: {
      hName: 'frago-cite-pending',
      hProperties: {
        'data-cite-pending': label,
      },
    },
  };
}

/**
 * 扫描原始 Markdown 切片里的 `[^N]` 出现，返回每个匹配前是否有未闭合奇数的反斜杠转义（如 `\[^1]`）。
 */
function detectEscapedFootnoteMarkers(rawSlice: string): boolean[] {
  const flags: boolean[] = [];
  const re = /\[\^([A-Za-z0-9_-]{1,32})\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(rawSlice)) !== null) {
    let slashCount = 0;
    for (let i = m.index - 1; i >= 0 && rawSlice[i] === '\\'; i -= 1) {
      slashCount += 1;
    }
    // 兼容 `[\^1]` 写法：如果 `[` 后紧跟 `\`，remark-parse 已把它还原成 `[^1]`
    flags.push(slashCount % 2 === 1);
  }
  return flags;
}

function splitPendingTextNode(
  node: MdastNode,
  rawSource: string,
  defsById: Map<string, CiteDefinition>
): MdastNode[] {
  const val = node.value ?? '';
  if (!val.includes('[^')) return [node];

  const startOff = node.position?.start?.offset;
  const endOff = node.position?.end?.offset;
  const rawSlice =
    typeof startOff === 'number' && typeof endOff === 'number'
      ? rawSource.slice(startOff, endOff)
      : val;

  // 若 rawSlice 包含 `[\^` 形式转义，也视为全部不可解析以避免误伤
  const hasBracketEscape = rawSlice.includes('[\\^');
  const escapedFlags = detectEscapedFootnoteMarkers(rawSlice);

  const re = /\[\^([A-Za-z0-9_-]{1,32})\]/g;
  const out: MdastNode[] = [];
  let cursor = 0;
  let matchIdx = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(val)) !== null) {
    const label = m[1];
    const id = label.toLowerCase();
    const isEscaped = hasBracketEscape || Boolean(escapedFlags[matchIdx]);
    matchIdx += 1;

    if (isEscaped || defsById.has(id)) {
      continue;
    }

    if (m.index > cursor) {
      out.push({ type: 'text', value: val.slice(cursor, m.index) });
    }
    out.push(makeCitePending(label));
    cursor = m.index + m[0].length;
  }

  if (out.length === 0) return [node];
  if (cursor < val.length) {
    out.push({ type: 'text', value: val.slice(cursor) });
  }
  return out;
}

/**
 * 为安全可包裹的前置同句内联兄弟节点套上 `frago-cite-span`。
 * 遇 `link`、已有引用节点或块级边界即止，绝不破坏已有 Markdown DOM 节点结构。
 */
function wrapPrecedingClause(siblings: MdastNode[], citeId: string): void {
  if (siblings.length === 0) return;
  const last = siblings[siblings.length - 1];
  // 同一论断连续多个引用（如 `[^1][^2]`）：保留首位已经包好的 `.cite-span`
  if (last.type === 'fragoCitePill') return;

  const collected: MdastNode[] = [];
  while (siblings.length > 0) {
    const cur = siblings[siblings.length - 1];
    if (!WRAPPABLE_INLINE_TYPES.has(cur.type)) break;

    if (cur.type === 'text') {
      const txt = cur.value ?? '';
      const splitIdx = findClauseSplitIndex(txt);
      if (splitIdx >= 0) {
        const before = txt.slice(0, splitIdx);
        let clause = txt.slice(splitIdx);
        const leadingWs = /^\s+/.exec(clause)?.[0] ?? '';
        const prefix = before + leadingWs;
        clause = clause.slice(leadingWs.length);
        siblings.pop();
        if (prefix) {
          siblings.push({ type: 'text', value: prefix });
        }
        if (clause) {
          collected.unshift({ type: 'text', value: clause });
        }
        break;
      }
    }
    siblings.pop();
    collected.unshift(cur);
  }

  const hasVisibleText = collected.some((n) => extractPlainText(n).trim().length > 0);
  if (!hasVisibleText) {
    siblings.push(...collected);
    return;
  }
  siblings.push(makeCiteSpan(citeId, collected));
}

export interface RemarkCitationsOptions {
  definitions: CiteDefinition[];
  streaming: boolean;
  rawSource: string;
}

const SKIP_CONTAINER_TYPES = new Set([
  'code',
  'inlineCode',
  'link',
  'footnoteDefinition',
  'fragoCiteSpan',
  'fragoCitePill',
  'fragoCitePending',
]);

export function createRemarkCitationsPlugin(options: RemarkCitationsOptions) {
  return function remarkCitations() {
    return (tree: MdastNode) => {
      const defsById = new Map<string, CiteDefinition>();
      for (const d of options.definitions) {
        defsById.set(d.id, d);
      }

      // 补齐或确认 AST 中的 footnoteDefinition，并将其从 root 移除以隐藏冗余默认 footnotes 列表
      if (Array.isArray(tree.children)) {
        const kept: MdastNode[] = [];
        for (const child of tree.children) {
          if (child.type === 'footnoteDefinition' && child.identifier) {
            const id = child.identifier.toLowerCase();
            if (!defsById.has(id)) {
              const linkNode = findFirstLink(child);
              const rawUrl = linkNode?.url ?? '';
              const checked = validateCitationUri(rawUrl);
              const linkTitle = linkNode ? extractPlainText(linkNode).trim() : '';
              const fullText = extractPlainText(child).trim();
              const def: CiteDefinition = {
                id,
                label: child.label || child.identifier,
                title: linkTitle || fullText || `[${child.identifier}]`,
                uri: checked.uri,
                excerpt: (linkNode?.title ?? '').trim(),
                kind: checked.kind,
                filePath: checked.filePath,
                hlStart: checked.hlStart,
                hlEnd: checked.hlEnd,
                line: checked.line,
                unsafeUri: checked.unsafeUri,
              };
              defsById.set(id, def);
            }
            continue;
          }
          kept.push(child);
        }
        tree.children = kept;
      }

      const transformChildren = (parent: MdastNode) => {
        if (!Array.isArray(parent.children) || SKIP_CONTAINER_TYPES.has(parent.type)) {
          return;
        }
        const nextChildren: MdastNode[] = [];
        for (const child of parent.children) {
          if (child.type === 'footnoteReference' && child.identifier) {
            const id = child.identifier.toLowerCase();
            const def = defsById.get(id);
            if (!def) {
              if (options.streaming) {
                nextChildren.push(makeCitePending(child.label || child.identifier));
              } else {
                nextChildren.push({
                  type: 'text',
                  value: `[^${child.label || child.identifier}]`,
                });
              }
              continue;
            }
            if (def.kind === 'invalid') {
              // 危险或无效 URI：剥离交互与下划线，仅留不可点击纯文本角标
              nextChildren.push({
                type: 'text',
                value: `[${def.label}]`,
              });
              continue;
            }
            wrapPrecedingClause(nextChildren, def.id);
            nextChildren.push(makeCitePill(def.id, def.label, def.kind));
            continue;
          }

          if (child.type === 'text' && options.streaming) {
            const expanded = splitPendingTextNode(child, options.rawSource, defsById);
            nextChildren.push(...expanded);
            continue;
          }

          transformChildren(child);
          nextChildren.push(child);
        }
        parent.children = nextChildren;
      };

      transformChildren(tree);
    };
  };
}
