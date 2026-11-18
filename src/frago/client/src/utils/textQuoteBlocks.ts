/**
 * 解析、序列化与剥离会话及输入框中的文本引用块（Quote Blocks）。
 *
 * 引用块的纯文本传输契约（与 `Composer`、`StackPanel`、`workbench_branch.py`、`useFileAnnotations` 对齐）：
 * ```
 * """
 * <被引用的原文>
 * """
 * >>> <用户的追问或批注>
 * ```
 *
 * - 发送给后端与 Agent 时保持该纯文本语义格式，既不破坏大模型理解，也保持与 `quotesAboard` /
 *   `marksAboard` / `bringBack` 留痕机制的 100% 兼容；
 * - 在前端输入框（Composer / PromptComposerBox）与会话消息（RecordCard / SessionLaunchPanel）中
 *   解析并渲染为统一的特定引用卡片样式；
 * - 在会话标题、左栏摘要与 Progress Goal Anchor 中剥离裸 `"""` 与 `>>>` 标记，避免长引用撑乱标题。
 */

export interface ComposerQuoteItem {
  id: string;
  text: string;
}

export interface TextQuoteBlockItem {
  /** 引用序号（从 1 开始）。 */
  index: number;
  /** 引用原文正文。 */
  text: string;
  /** 字符数（按 Unicode 码点计）。 */
  charCount: number;
  /** 行数。 */
  lineCount: number;
}

export type TextQuoteSegment =
  | { type: 'quote'; item: TextQuoteBlockItem }
  | { type: 'prose'; text: string };

export interface ParsedTextQuotes {
  hasQuotes: boolean;
  quotes: TextQuoteBlockItem[];
  segments: TextQuoteSegment[];
  /** 剥离全部 `""" ... """` 引用块与 `>>>` 引导符后的纯用户发言文本。 */
  userPrompt: string;
}

const FENCE_RE = /^\s*(`{3,}|~{3,})/;
const QUOTE_DELIM_RE = /^\s*"""\s*$/;
const REPLY_PREFIX_RE = /^\s*>>>\s?(.*)$/;
const COLLAPSED_INLINE_QUOTE_RE = /^\s*"""[^\r\n]+?"""/;

/**
 * 将输入框内挂载的引用列表与用户输入的正文序列化为标准纯文本引用格式。
 */
export function serializeQuotesWithPrompt(
  quotes: ReadonlyArray<{ id?: string; text: string }>,
  userText: string
): string {
  const validQuotes = quotes
    .map((q) => q.text.trim())
    .filter((t) => t.length > 0);
  if (validQuotes.length === 0) {
    return userText.trim();
  }
  const blocks = validQuotes.map((t) => `"""\n${t}\n"""`).join('\n');
  const trimmedUser = userText.trim().replace(/^>>>\s*/, '');
  return trimmedUser ? `${blocks}\n>>> ${trimmedUser}` : `${blocks}\n>>> `;
}

/**
 * 解析一条用户消息中的 `""" ... """` 引用块与 `>>>` 追问文本。
 * 自动跳过 Markdown 代码围栏（``` / ~~~）内部的 `"""`（如 Python docstring），防止误判。
 */
export function parseTextQuoteBlocks(rawText: string): ParsedTextQuotes {
  const src = rawText ?? '';
  if (!src.includes('"""')) {
    return {
      hasQuotes: false,
      quotes: [],
      segments: src.trim() ? [{ type: 'prose', text: src }] : [],
      userPrompt: src,
    };
  }

  const lines = src.split(/\r?\n/);
  const quotes: TextQuoteBlockItem[] = [];
  const segments: TextQuoteSegment[] = [];
  let proseLines: string[] = [];
  let activeFence: string | null = null;
  let hadEmptyQuoteBlock = false;

  const flushProse = () => {
    if (proseLines.length === 0) return;
    const joined = proseLines.join('\n').trim();
    proseLines = [];
    if (joined) {
      segments.push({ type: 'prose', text: joined });
    }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fenceMatch = FENCE_RE.exec(line);
    if (fenceMatch) {
      const marker = fenceMatch[1];
      if (!activeFence) {
        activeFence = marker[0];
      } else if (marker[0] === activeFence) {
        activeFence = null;
      }
      proseLines.push(line);
      i += 1;
      continue;
    }

    if (!activeFence && QUOTE_DELIM_RE.test(line)) {
      let closeIdx = -1;
      for (let j = i + 1; j < lines.length; j += 1) {
        if (QUOTE_DELIM_RE.test(lines[j])) {
          closeIdx = j;
          break;
        }
      }
      if (closeIdx !== -1) {
        const quoteBody = lines
          .slice(i + 1, closeIdx)
          .join('\n')
          .trim();
        if (quoteBody) {
          flushProse();
          const item: TextQuoteBlockItem = {
            index: quotes.length + 1,
            text: quoteBody,
            charCount: Array.from(quoteBody).length,
            lineCount: quoteBody.split(/\r?\n/).length,
          };
          quotes.push(item);
          segments.push({ type: 'quote', item });
        } else {
          hadEmptyQuoteBlock = true;
        }
        i = closeIdx + 1;
        while (i < lines.length) {
          const replyMatch = REPLY_PREFIX_RE.exec(lines[i]);
          if (!replyMatch) break;
          const afterArrow = replyMatch[1];
          if (afterArrow.trim()) {
            proseLines.push(afterArrow);
          }
          i += 1;
        }
        continue;
      }
    }

    proseLines.push(line);
    i += 1;
  }

  flushProse();

  if (quotes.length === 0) {
    if (hadEmptyQuoteBlock) {
      const cleanedPrompt = segments
        .filter((s): s is { type: 'prose'; text: string } => s.type === 'prose')
        .map((s) => s.text)
        .join('\n\n')
        .trim();
      return {
        hasQuotes: false,
        quotes: [],
        segments: cleanedPrompt ? [{ type: 'prose', text: cleanedPrompt }] : [],
        userPrompt: cleanedPrompt,
      };
    }
    return {
      hasQuotes: false,
      quotes: [],
      segments: src.trim() ? [{ type: 'prose', text: src }] : [],
      userPrompt: src,
    };
  }

  const userPrompt = segments
    .filter((s): s is { type: 'prose'; text: string } => s.type === 'prose')
    .map((s) => s.text)
    .join('\n\n')
    .trim();

  return {
    hasQuotes: true,
    quotes,
    segments,
    userPrompt,
  };
}

/**
 * 剥离消息或标题中的 `""" ... """` 引用包裹与 `>>>` 引导符：
 * - 若存在用户追问正文（`userPrompt`），优先返回干净的用户追问正文；
 * - 若用户仅发送了引用而无追问文字，返回去除 `"""` 与 `>>>` 后的单行引用摘要；
 * - 兼容服务端生成会话标题时已将换行压平为空格的 `""" ... """ >>> ...` 形态。
 */
export function stripTextQuoteBlocks(rawText: string): string {
  const src = rawText ?? '';
  if (!src.includes('"""')) return src;

  const parsed = parseTextQuoteBlocks(src);
  if (parsed.hasQuotes) {
    if (parsed.userPrompt) return parsed.userPrompt;
    return parsed.quotes[0]?.text.replace(/\s+/g, ' ').trim() ?? '';
  }

  if (!src.includes('\n') && COLLAPSED_INLINE_QUOTE_RE.test(src)) {
    const withoutQuotes = src
      .replace(/"""[^\r\n]*?"""\s*(?:>>>\s*)?/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    if (withoutQuotes) return withoutQuotes;
    const firstQuote = /"""([^\r\n]*?)"""/.exec(src)?.[1]?.replace(/\s+/g, ' ').trim();
    if (firstQuote) return firstQuote;
  }

  return src;
}
