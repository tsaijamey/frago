/**
 * 解析并剥离浏览器扩展（Frago Browser Extension）回传到会话的网页上下文与 Focus 焦点块。
 *
 * 兼容 `shared/message_composer.js` 的标准拼装结构及历史/变体标题：
 * - 前导用户指令（在第一个桥接分隔线 `---` + 桥接三级标题之前）；
 * - Focus 焦点区块：`### 🎯 Focus 焦点内容...` / `### 来自网页的参考内容...`
 *   内含若干 `#### [FOCUS #N] <页面标题>（<类型> · `<selector>`）` 与 `- 来源：<url>`；
 * - 整页可见上下文区块：`### 📄 网页完整可见上下文...` / `### 网页完整可见上下文...`
 *   内含若干 `#### [页面 K] <页面标题>（约 N 字）`、`- URL：<url>`、关联 Focus / 超长附件元信息，
 *   以及正文中原地嵌入的 `<<< 🎯 FOCUS #N 开始 >>> ... <<< 🎯 FOCUS #N 结束 >>>` 锚点标记。
 */

export interface WebBridgeFocusItem {
  /** Focus 编号（来自 `[FOCUS #N]`）。 */
  index: number;
  /** 来源页面标题。 */
  title: string;
  /** 焦点类型标签，如 `划词焦点` / `网页区块`。 */
  kindLabel: string;
  /** 可选 CSS 选择器。 */
  selector: string;
  /** 原始来源 URL。 */
  url: string;
  /** 可安全用于 `<a href>` 的 http(s) URL；非 http(s) 时为空串。 */
  safeUrl: string;
  /** 展示用域名（解析失败时回退原 URL）。 */
  domain: string;
  /** 剥离内部元信息行后的焦点引用正文。 */
  body: string;
}

export interface WebBridgePageContext {
  /** 页面序号（来自 `[页面 K]`）。 */
  pageIndex: number;
  /** 页面标题。 */
  title: string;
  /** 原始 URL。 */
  url: string;
  /** 可安全用于 `<a href>` 的 http(s) URL。 */
  safeUrl: string;
  /** 展示用域名。 */
  domain: string;
  /** 声明的字数（来自 `（约 N 字）`），未声明时按正文长度计算。 */
  charCount: number;
  /** 本页关联的 Focus 编号列表（合并元信息与正文锚点扫描结果，升序去重）。 */
  focusNumbers: number[];
  /** 未能精确回位的 Focus 编号列表。 */
  unmatchedFocusNumbers: number[];
  /** 超长页面保护挂载的 `.md` 附件文件名（如有）。 */
  offloadedAttachmentName: string | null;
  /** 剥离头部元信息列表后的整页 Markdown 正文。 */
  markdown: string;
}

export interface ParsedWebBridgeContext {
  hasBridgeContext: boolean;
  userPrompt: string;
  focusItems: WebBridgeFocusItem[];
  pages: WebBridgePageContext[];
}

export type FocusAnchorSegment =
  | { type: 'markdown'; content: string }
  | { type: 'focus'; focusNumber: number; content: string };

const BRIDGE_START_RE =
  /(?:^|\r?\n)---\s*\r?\n(?:###\s+(?:🎯\s*Focus\s*焦点内容[^\r\n]*|来自网页的参考内容[^\r\n]*|📄\s*网页完整可见上下文[^\r\n]*|网页完整可见上下文[^\r\n]*))/;

const COLLAPSED_BRIDGE_TAIL_RE =
  /(?:^|\s)---\s+###\s+(?:🎯(?:\s*Focus[^\r\n]*)?|来自网页(?:的参考内容)?[^\r\n]*|📄(?:\s*网页完整可见上下文)?[^\r\n]*|网页完整可见上下文[^\r\n]*)[\s\S]*$/i;

const FOCUS_SECTION_HEAD_RE =
  /^###\s+(?:🎯\s*Focus\s*焦点内容[^\r\n]*|来自网页的参考内容[^\r\n]*)$/;

const PAGE_SECTION_HEAD_RE =
  /^###\s+(?:📄\s*)?网页完整可见上下文[^\r\n]*$/;

const FOCUS_ITEM_HEAD_RE = /^####\s+\[?FOCUS\s+#(\d+)\]?\s*(.*)$/i;
const PAGE_ITEM_HEAD_RE = /^####\s+\[页面\s+(\d+)\]\s*(.*)$/;
const FOCUS_ANCHOR_TAG_RE = /<<<\s*🎯\s*FOCUS\s*#(\d+)\s*(开始|结束)\s*>>>/g;

export function toSafeHttpUrl(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (!trimmed) return '';
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.toString();
    }
  } catch {
    // ignore invalid URL
  }
  return '';
}

export function extractDomainLabel(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (!trimmed) return '';
  try {
    const parsed = new URL(trimmed);
    return parsed.hostname || trimmed;
  } catch {
    return trimmed;
  }
}

function parseFocusHeadingRest(rest: string): {
  title: string;
  kindLabel: string;
  selector: string;
} {
  const trimmed = rest.trim();
  if (!trimmed) {
    return { title: '未命名页面', kindLabel: '', selector: '' };
  }
  // 匹配末尾的 `（划词焦点）` 或 `（网页区块 · `.foo > .bar`）`
  const parenMatch = /^(.*?)[（(]([^（）()]+)[）)]$/.exec(trimmed);
  if (!parenMatch) {
    return { title: trimmed, kindLabel: '', selector: '' };
  }
  const title = parenMatch[1].trim() || '未命名页面';
  const meta = parenMatch[2].trim();
  const dotIdx = meta.indexOf('·');
  if (dotIdx < 0) {
    return { title, kindLabel: meta, selector: '' };
  }
  const kindLabel = meta.slice(0, dotIdx).trim();
  const rawSelector = meta.slice(dotIdx + 1).trim();
  const selector = rawSelector.replace(/^`+|`+$/g, '').trim();
  return { title, kindLabel, selector };
}

function parsePageHeadingRest(rest: string): {
  title: string;
  declaredCharCount: number | null;
} {
  const trimmed = rest.trim();
  if (!trimmed) {
    return { title: '当前网页', declaredCharCount: null };
  }
  const charMatch = /^(.*?)[（(]约\s*(\d+)\s*字[）)]$/.exec(trimmed);
  if (!charMatch) {
    return { title: trimmed, declaredCharCount: null };
  }
  const count = Number.parseInt(charMatch[2], 10);
  return {
    title: charMatch[1].trim() || '当前网页',
    declaredCharCount: Number.isFinite(count) ? count : null,
  };
}

function parseFocusNumbersList(raw: string): number[] {
  const nums: number[] = [];
  const re = /#(\d+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    const n = Number.parseInt(m[1], 10);
    if (Number.isFinite(n) && !nums.includes(n)) nums.push(n);
  }
  return nums;
}

function collectAnchorNumbersFromText(text: string): number[] {
  const nums: number[] = [];
  FOCUS_ANCHOR_TAG_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = FOCUS_ANCHOR_TAG_RE.exec(text)) !== null) {
    const n = Number.parseInt(m[1], 10);
    if (Number.isFinite(n) && !nums.includes(n)) nums.push(n);
  }
  return nums;
}

function parseFocusSection(lines: string[]): WebBridgeFocusItem[] {
  const items: WebBridgeFocusItem[] = [];
  let current: {
    index: number;
    title: string;
    kindLabel: string;
    selector: string;
    url: string;
    bodyLines: string[];
    inMeta: boolean;
  } | null = null;

  const flush = () => {
    if (!current) return;
    const body = current.bodyLines.join('\n').trim();
    const safeUrl = toSafeHttpUrl(current.url);
    const domain = extractDomainLabel(current.url);
    items.push({
      index: current.index,
      title: current.title,
      kindLabel: current.kindLabel,
      selector: current.selector,
      url: current.url,
      safeUrl,
      domain,
      body,
    });
    current = null;
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const headMatch = FOCUS_ITEM_HEAD_RE.exec(trimmed);
    if (headMatch) {
      flush();
      const index = Number.parseInt(headMatch[1], 10);
      const { title, kindLabel, selector } = parseFocusHeadingRest(headMatch[2] ?? '');
      current = {
        index,
        title,
        kindLabel,
        selector,
        url: '',
        bodyLines: [],
        inMeta: true,
      };
      continue;
    }

    if (!current) continue;

    if (current.inMeta) {
      if (!trimmed) {
        if (current.url) current.inMeta = false;
        continue;
      }
      const sourceMatch = /^-\s*(?:来源|URL)[：:]\s*(.+)$/i.exec(trimmed);
      if (sourceMatch) {
        current.url = sourceMatch[1].trim();
        continue;
      }
      if (/^-\s*(?:类型|选择器|Selector)[：:]/i.test(trimmed)) {
        continue;
      }
      current.inMeta = false;
    }

    current.bodyLines.push(line);
  }

  flush();
  return items;
}

function parsePageSection(lines: string[]): WebBridgePageContext[] {
  const pages: WebBridgePageContext[] = [];
  let current: {
    pageIndex: number;
    title: string;
    declaredCharCount: number | null;
    url: string;
    metaFocusNumbers: number[];
    unmatchedFocusNumbers: number[];
    offloadedAttachmentName: string | null;
    bodyLines: string[];
    inMeta: boolean;
  } | null = null;

  const flush = () => {
    if (!current) return;
    const markdown = current.bodyLines.join('\n').trim();
    const anchorNums = collectAnchorNumbersFromText(markdown);
    const mergedFocus = Array.from(
      new Set([...current.metaFocusNumbers, ...anchorNums])
    ).sort((a, b) => a - b);
    const safeUrl = toSafeHttpUrl(current.url);
    const domain = extractDomainLabel(current.url);
    pages.push({
      pageIndex: current.pageIndex,
      title: current.title,
      url: current.url,
      safeUrl,
      domain,
      charCount: current.declaredCharCount ?? markdown.length,
      focusNumbers: mergedFocus,
      unmatchedFocusNumbers: current.unmatchedFocusNumbers,
      offloadedAttachmentName: current.offloadedAttachmentName,
      markdown,
    });
    current = null;
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const headMatch = PAGE_ITEM_HEAD_RE.exec(trimmed);
    if (headMatch) {
      flush();
      const pageIndex = Number.parseInt(headMatch[1], 10);
      const { title, declaredCharCount } = parsePageHeadingRest(headMatch[2] ?? '');
      current = {
        pageIndex,
        title,
        declaredCharCount,
        url: '',
        metaFocusNumbers: [],
        unmatchedFocusNumbers: [],
        offloadedAttachmentName: null,
        bodyLines: [],
        inMeta: true,
      };
      continue;
    }

    if (!current) continue;

    if (current.inMeta) {
      if (!trimmed) {
        if (current.url || current.metaFocusNumbers.length > 0) {
          current.inMeta = false;
        }
        continue;
      }
      const urlMatch = /^-\s*(?:URL|来源)[：:]\s*(.+)$/i.exec(trimmed);
      if (urlMatch) {
        current.url = urlMatch[1].trim();
        continue;
      }
      const focusMetaMatch = /^-\s*本页关联\s*Focus[：:]\s*(.+)$/i.exec(trimmed);
      if (focusMetaMatch) {
        current.metaFocusNumbers = parseFocusNumbersList(focusMetaMatch[1]);
        continue;
      }
      const unmatchedMatch = /^-\s*提示[：:]\s*Focus\s+([^未]+)未在/.exec(trimmed);
      if (unmatchedMatch) {
        current.unmatchedFocusNumbers = parseFocusNumbersList(unmatchedMatch[1]);
        continue;
      }
      const offloadMatch = /^-\s*超长页面保护[：:].*?`([^`]+\.md)`/.exec(trimmed);
      if (offloadMatch) {
        current.offloadedAttachmentName = offloadMatch[1].trim();
        continue;
      }
      current.inMeta = false;
    }

    current.bodyLines.push(line);
  }

  flush();
  return pages;
}

/**
 * 解析一条用户消息中的浏览器扩展上下文。
 * 未命中标准桥接结构时返回 `hasBridgeContext: false`，原样保留 `userPrompt`。
 */
export function parseWebBridgeContext(rawText: string): ParsedWebBridgeContext {
  const raw = rawText ?? '';
  if (!raw.trim()) {
    return {
      hasBridgeContext: false,
      userPrompt: raw,
      focusItems: [],
      pages: [],
    };
  }

  const startMatch = BRIDGE_START_RE.exec(raw);
  if (!startMatch) {
    return {
      hasBridgeContext: false,
      userPrompt: raw,
      focusItems: [],
      pages: [],
    };
  }

  const splitIdx = startMatch.index;
  const userPrompt = raw.slice(0, splitIdx).trim();
  const tail = raw.slice(splitIdx);

  const lines = tail.split(/\r?\n/);
  let mode: 'none' | 'focus' | 'page' = 'none';
  const focusLines: string[] = [];
  const pageLines: string[] = [];

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (FOCUS_SECTION_HEAD_RE.test(trimmed)) {
      mode = 'focus';
      continue;
    }
    if (PAGE_SECTION_HEAD_RE.test(trimmed)) {
      mode = 'page';
      continue;
    }

    // 跳过分隔 Focus 区块与整页区块的 `---`
    if (trimmed === '---') {
      let nextNonEmpty = '';
      for (let j = i + 1; j < lines.length; j += 1) {
        const candidate = lines[j].trim();
        if (candidate) {
          nextNonEmpty = candidate;
          break;
        }
      }
      if (FOCUS_SECTION_HEAD_RE.test(nextNonEmpty) || PAGE_SECTION_HEAD_RE.test(nextNonEmpty)) {
        continue;
      }
    }

    if (mode === 'focus') {
      focusLines.push(line);
    } else if (mode === 'page') {
      pageLines.push(line);
    }
  }

  const focusItems = parseFocusSection(focusLines);
  const pages = parsePageSection(pageLines);

  if (focusItems.length === 0 && pages.length === 0) {
    return {
      hasBridgeContext: false,
      userPrompt: raw,
      focusItems: [],
      pages: [],
    };
  }

  return {
    hasBridgeContext: true,
    userPrompt,
    focusItems,
    pages,
  };
}

/**
 * 仅保留干净的用户指令正文，剥离末尾浏览器扩展拼装的 Focus 与整页上下文。
 */
export function stripWebBridgeContext(rawText: string): string {
  const src = rawText ?? '';
  const parsed = parseWebBridgeContext(src);
  if (parsed.hasBridgeContext) return parsed.userPrompt;
  const collapsedMatch = COLLAPSED_BRIDGE_TAIL_RE.exec(src);
  if (collapsedMatch) {
    return src.slice(0, collapsedMatch.index).trim();
  }
  return src;
}

/**
 * 将整页 Markdown 中的 `<<< 🎯 FOCUS #N 开始 >>> ... <<< 🎯 FOCUS #N 结束 >>>`
 * 切分为普通 Markdown 段与带焦点编号的高亮段；同时清理任何残余孤立锚点标签。
 */
export function splitFocusAnchorSegments(markdown: string): FocusAnchorSegment[] {
  const text = markdown ?? '';
  if (!text) return [];

  const matchedBlockRe =
    /<<<\s*🎯\s*FOCUS\s*#(\d+)\s*开始\s*>>>\r?\n?([\s\S]*?)\r?\n?<<<\s*🎯\s*FOCUS\s*#\1\s*结束\s*>>>/g;
  const orphanTagRe = /<<<\s*🎯\s*FOCUS\s*#\d+\s*(?:开始|结束)\s*>>>\r?\n?/g;

  const segments: FocusAnchorSegment[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = matchedBlockRe.exec(text)) !== null) {
    if (match.index > cursor) {
      const before = text.slice(cursor, match.index).replace(orphanTagRe, '').trim();
      if (before) {
        segments.push({ type: 'markdown', content: before });
      }
    }
    const focusNumber = Number.parseInt(match[1], 10);
    const body = (match[2] ?? '').replace(orphanTagRe, '').trim();
    if (body) {
      segments.push({ type: 'focus', focusNumber, content: body });
    }
    cursor = match.index + match[0].length;
  }

  if (cursor < text.length) {
    const rest = text.slice(cursor).replace(orphanTagRe, '').trim();
    if (rest) {
      segments.push({ type: 'markdown', content: rest });
    }
  }

  return segments;
}
