/**
 * 识别并剥离用户消息开头的异步回传块：
 * - 单条 `<frago-async-callback ...>...</frago-async-callback>`；
 * - 批信封 `<frago-async-callbacks count="N" delivery="..." ...>...</frago-async-callbacks>`
 *   （含内部的 1 条或多条 `<frago-async-callback>`、超长降级紧凑摘要与极窄预算索引行）。
 *
 * 下属 Worker 或同侪员工在后台跑完后，异步派发守护进程（`async_dispatch.py`）或
 * `CallbackInbox` 投递器会把交付结果包裹在回调标签内，经终端 / SDK / Hook 注入父会话，
 * 在统一记录中落为 `user.say`（或排队期间的 `queued_command` / `session.state` 入队行、
 * `context.inject` / `reminders`）。
 *
 * 与 `<frago-employee>`、`<must-use-skill>` 同理：真实注入的回调块一定出现在消息开头（紧跟可选的
 * 员工/技能块之后）；用户在正文或分支引用里提到的 `<frago-async-callback>` / `<frago-async-callbacks>`
 * 字面量不在消息开头，不会被误拆。
 */

import { splitAttachedImages } from './attachedImages';
import { splitEmployeeBlocks } from './employeeBlocks';
import { splitSkillBlocks } from './skillBlocks';

export interface AsyncCallbackBlockItem {
  /** 回传来源类型：`worker`（下属 Worker）或 `employee`（同侪员工）。 */
  kind: 'worker' | 'employee' | string;
  /** 派发模式：`new` | `resume` | `send` | `invoke` | `ask` 等。 */
  mode: string;
  /** 异步派发单号，如 `disp-beaa67f7b8ea`。 */
  jobId: string;
  /** 目标会话 ID（Worker 的 `worker_session_id` 或同侪员工的 `session_id`）。 */
  targetSessionId: string;
  /** 同侪员工 ID（仅 `kind === 'employee'` 时有值）。 */
  employeeId: string;
  /** Worker 执行内核（如 `claude-code`、`coreagent`、`agy`，从正文头解析）。 */
  agentKernel: string;
  /** 执行状态：`completed` | `failed` 等。 */
  status: 'completed' | 'failed' | string;
  /** 退出码（从 `- 执行状态：\`...\` (exit_code=N)` 或紧凑摘要状态行解析）。 */
  exitCode: number | null;
  /** 完整任务摘要或原始诉求文本。 */
  taskSummary: string;
  /** 任务摘要的单行纯文本标题预览（去掉 Markdown 标题井号与列表前缀）。 */
  taskTitle: string;
  /** 剥离头部元数据与尾部管理者复核样板话术后的交付正文（Markdown）。 */
  resultBody: string;
  /** 批信封投递通道（仅来自 `<frago-async-callbacks delivery="...">` 时填充，如 `idle-batch` / `turn-submit-hitchhike`）。 */
  delivery?: string;
  /** 批信封声明的总条数（仅来自 `<frago-async-callbacks count="N">` 时填充）。 */
  batchCount?: number;
  /** 批信封超长降级时的省略尾项提示（如有）。 */
  batchNotice?: string;
}

const BATCH_OPEN_RE = /^<frago-async-callbacks(?:\s+([^>]*))?>/i;
const SINGLE_OPEN_RE = /^<frago-async-callback(?:\s+([^>]*))?>/i;
const STRAY_CLOSE_TAGS_RE = /^[ \t\r\n]*(?:<\/frago-async-callbacks?>[ \t\r\n]*)+/i;
const STRAY_STANDALONE_CLOSE_LINE_RE = /^[ \t]*<\/frago-async-callbacks?>[ \t]*$/gim;

const ATTR_PAIR_RE = /([a-zA-Z0-9_-]+)="([^"]*)"/g;

const WORKER_KERNEL_RE = /【下属 Worker 异步回传】[^\r\n]*?内核：`([^`]+)`/;
const EMPLOYEE_FROM_RE = /【同侪员工异步回传】来自\s*`([^`]+)`/;
const JOB_ID_LINE_RE = /^-\s*派发单号：`([^`]+)`/m;
const COMPACT_JOB_ID_RE = /\|\s*派发单号：`([^`]+)`/;
const COMPACT_SOURCE_RE = /^-\s*来源：(同侪|Worker)\s*`([^`]+)`/m;
const STATUS_LINE_RE = /^-\s*执行状态：`([^`]+)`(?:\s*\(exit_code=(-?\d+)\))?/m;
const COMPACT_STATUS_RE = /\|\s*状态：`([^`]+)`(?:\s*\(exit_code=(-?\d+)\))?/;
const SUMMARY_BLOCK_RE =
  /^-\s*(?:任务摘要|原始诉求)：([\s\S]*?)(?=\r?\n-\s*执行状态：|\r?\n###\s+(?:Worker 交付结果|同侪员工返回结论)|(?![\s\S]))/m;
const COMPACT_SUMMARY_RE = /^-\s*诉求：([^\r\n]+)/m;
const RESULT_SECTION_RE =
  /(?:^|\r?\n)###\s+(?:Worker 交付结果|同侪员工返回结论)\r?\n([\s\S]*)$/;
const TRAILING_MANAGER_PROMPT_RE =
  /\r?\n---\r?\n请(?:作为管理者（Employee）结合领域知识与执行准则审核上述 Worker 产出|基于上述同侪员工回传结论，结合你掌握的领域背景与事务围栏进行复核)[\s\S]*$/;

const BATCH_PREAMBLE_HITCHHIKE_RE =
  /^【优先主线声明】[\s\S]*?(?=\r?\n\r?\n|$)/;
const BATCH_PREAMBLE_IDLE_RE =
  /^【后台异步派发回执汇总】[^\r\n]*/;
const BATCH_OMITTED_FOOTER_RE =
  /（因上下文预算上限，其余\s*\d+\s*条回执已省略详情[；;][^）]*）/;
const NARROW_BUDGET_LINE_RE =
  /^-\s*job_id=(\S+)\s+status=(\S+)(?:\s+report=(.+))?$/gm;
const FENCE_LINE_RE = /^[ \t]*(`{3,}|~{3,})/;

function parseAttributes(attrString: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  if (!attrString) return attrs;
  ATTR_PAIR_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = ATTR_PAIR_RE.exec(attrString)) !== null) {
    attrs[m[1]] = m[2].trim();
  }
  return attrs;
}

function extractTaskTitle(summary: string): string {
  if (!summary) return '';
  const lines = summary
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^\s*#+\s*/, '')
        .replace(/^\s*[-*+]\s+/, '')
        .trim()
    )
    .filter(Boolean);
  if (!lines.length) return '';
  const first = lines[0];
  return first.length > 120 ? `${first.slice(0, 117)}...` : first;
}

/**
 * 判断一行文本中 `pos` 处的反引号串是否有同长度的闭合反引号；若有则返回闭合之后的位置，否则返回 -1。
 */
function skipInlineCodeSpan(line: string, start: number): number {
  let runEnd = start;
  while (runEnd < line.length && line[runEnd] === '`') runEnd += 1;
  const runLen = runEnd - start;
  let idx = runEnd;
  while (idx < line.length) {
    if (line[idx] === '`') {
      let closeEnd = idx;
      while (closeEnd < line.length && line[closeEnd] === '`') closeEnd += 1;
      if (closeEnd - idx === runLen) {
        return closeEnd;
      }
      idx = closeEnd;
    } else {
      idx += 1;
    }
  }
  return -1;
}

/**
 * 查找与 `tagName` 对应的闭合标签位置，跳过 Markdown 围栏代码块与行内反引号中的字面量引用。
 * 优先匹配行尾 / 独立行 / 紧邻下一个回调标签的闭合标签，避免正文未加反引号提及标签名时提前截断。
 */
function findClosingTag(
  text: string,
  contentStart: number,
  tagName: 'frago-async-callbacks' | 'frago-async-callback'
): { closeStart: number; closeEnd: number } | null {
  const openPrefix = `<${tagName}`;
  const closeTag = `</${tagName}>`;
  let pos = contentStart;
  let lineIdx = 0;
  let fenceChar = '';
  let fenceLen = 0;
  let depth = 1;
  let fallbackMatch: { closeStart: number; closeEnd: number } | null = null;

  while (pos <= text.length) {
    const nl = text.indexOf('\n', pos);
    const rawLineEnd = nl === -1 ? text.length : nl;
    const lineEnd = rawLineEnd > pos && text[rawLineEnd - 1] === '\r' ? rawLineEnd - 1 : rawLineEnd;
    const line = text.slice(pos, lineEnd);
    const lowerLine = line.toLowerCase();
    const atLineStart = lineIdx > 0 || pos === 0 || text[pos - 1] === '\n';

    let skipLine = false;
    if (atLineStart) {
      const fenceMatch = FENCE_LINE_RE.exec(line);
      if (!fenceChar) {
        if (fenceMatch) {
          const ch = fenceMatch[1][0];
          const rest = line.slice(fenceMatch[0].length);
          if (ch === '~' || !rest.includes('`')) {
            fenceChar = ch;
            fenceLen = fenceMatch[1].length;
            skipLine = true;
          }
        }
      } else {
        if (
          fenceMatch &&
          fenceMatch[1][0] === fenceChar &&
          fenceMatch[1].length >= fenceLen &&
          line.slice(fenceMatch[0].length).trim() === ''
        ) {
          fenceChar = '';
          fenceLen = 0;
        }
        skipLine = true;
      }
    } else if (fenceChar) {
      skipLine = true;
    }

    if (!skipLine) {
      for (let i = 0; i < line.length; i += 1) {
        if (line[i] === '`') {
          const next = skipInlineCodeSpan(line, i);
          if (next !== -1) {
            i = next - 1;
            continue;
          }
        }
        if (line[i] !== '<') continue;

        if (lowerLine.startsWith(closeTag, i)) {
          depth -= 1;
          if (depth === 0) {
            const absStart = pos + i;
            const absEnd = absStart + closeTag.length;
            const afterOnLine = lowerLine.slice(i + closeTag.length).trim();
            const isCleanBoundary =
              lineIdx === 0 ||
              afterOnLine === '' ||
              afterOnLine.startsWith('<frago-async-callback') ||
              afterOnLine.startsWith('</frago-async-callback');
            if (isCleanBoundary) {
              return { closeStart: absStart, closeEnd: absEnd };
            }
            if (!fallbackMatch) {
              fallbackMatch = { closeStart: absStart, closeEnd: absEnd };
            }
            depth = 1;
          }
          i += closeTag.length - 1;
          continue;
        }

        if (lowerLine.startsWith(openPrefix, i)) {
          const nextCh = lowerLine[i + openPrefix.length];
          if (nextCh === '>' || nextCh === ' ' || nextCh === '\t') {
            const gt = line.indexOf('>', i + openPrefix.length);
            if (gt !== -1) {
              depth += 1;
              i = gt;
            }
          }
        }
      }
    }

    if (nl === -1) break;
    pos = nl + 1;
    lineIdx += 1;
  }

  return fallbackMatch;
}

/**
 * 查找 `text` 中从 `fromIndex` 起的下一个 `<frago-async-callback ...>` 起始标签（跳过代码块与行内代码）。
 */
function findNextSingleOpenTag(
  text: string,
  fromIndex: number
): { start: number; end: number; attrString: string } | null {
  let pos = fromIndex;
  let lineIdx = 0;
  let fenceChar = '';
  let fenceLen = 0;

  while (pos <= text.length) {
    const nl = text.indexOf('\n', pos);
    const rawLineEnd = nl === -1 ? text.length : nl;
    const lineEnd = rawLineEnd > pos && text[rawLineEnd - 1] === '\r' ? rawLineEnd - 1 : rawLineEnd;
    const line = text.slice(pos, lineEnd);
    const lowerLine = line.toLowerCase();
    const atLineStart = lineIdx > 0 || pos === 0 || text[pos - 1] === '\n';

    let skipLine = false;
    if (atLineStart) {
      const fenceMatch = FENCE_LINE_RE.exec(line);
      if (!fenceChar) {
        if (fenceMatch) {
          const ch = fenceMatch[1][0];
          const rest = line.slice(fenceMatch[0].length);
          if (ch === '~' || !rest.includes('`')) {
            fenceChar = ch;
            fenceLen = fenceMatch[1].length;
            skipLine = true;
          }
        }
      } else {
        if (
          fenceMatch &&
          fenceMatch[1][0] === fenceChar &&
          fenceMatch[1].length >= fenceLen &&
          line.slice(fenceMatch[0].length).trim() === ''
        ) {
          fenceChar = '';
          fenceLen = 0;
        }
        skipLine = true;
      }
    } else if (fenceChar) {
      skipLine = true;
    }

    if (!skipLine) {
      for (let i = 0; i < line.length; i += 1) {
        if (line[i] === '`') {
          const next = skipInlineCodeSpan(line, i);
          if (next !== -1) {
            i = next - 1;
            continue;
          }
        }
        if (line[i] !== '<') continue;
        if (lowerLine.startsWith('<frago-async-callback', i)) {
          const m = SINGLE_OPEN_RE.exec(line.slice(i));
          if (m) {
            return {
              start: pos + i,
              end: pos + i + m[0].length,
              attrString: m[1] ?? '',
            };
          }
        }
      }
    }

    if (nl === -1) break;
    pos = nl + 1;
    lineIdx += 1;
  }

  return null;
}

function stripStrayCloseTagsOutsideCode(raw: string): string {
  if (!raw.includes('</frago-async-callback')) return raw;
  const lines = raw.split(/\r?\n/);
  const out: string[] = [];
  let fenceChar = '';
  let fenceLen = 0;

  for (const line of lines) {
    const fenceMatch = FENCE_LINE_RE.exec(line);
    if (!fenceChar) {
      if (fenceMatch) {
        const ch = fenceMatch[1][0];
        const rest = line.slice(fenceMatch[0].length);
        if (ch === '~' || !rest.includes('`')) {
          fenceChar = ch;
          fenceLen = fenceMatch[1].length;
          out.push(line);
          continue;
        }
      }
    } else {
      if (
        fenceMatch &&
        fenceMatch[1][0] === fenceChar &&
        fenceMatch[1].length >= fenceLen &&
        line.slice(fenceMatch[0].length).trim() === ''
      ) {
        fenceChar = '';
        fenceLen = 0;
      }
      out.push(line);
      continue;
    }

    if (/^[ \t]*<\/frago-async-callbacks?>[ \t]*$/i.test(line)) {
      continue;
    }
    out.push(line);
  }

  return out.join('\n').trim();
}

function parseCallbackBlock(attrString: string, rawInner: string): AsyncCallbackBlockItem {
  const attrs = parseAttributes(attrString);
  const body = stripStrayCloseTagsOutsideCode(rawInner.trim());
  const bodyWithoutFooter = body.replace(TRAILING_MANAGER_PROMPT_RE, '').trim();

  const kernelMatch = WORKER_KERNEL_RE.exec(bodyWithoutFooter);
  const employeeMatch = EMPLOYEE_FROM_RE.exec(bodyWithoutFooter);
  const compactSourceMatch = COMPACT_SOURCE_RE.exec(bodyWithoutFooter);
  const jobLineMatch = JOB_ID_LINE_RE.exec(bodyWithoutFooter) ?? COMPACT_JOB_ID_RE.exec(bodyWithoutFooter);
  const statusLineMatch =
    STATUS_LINE_RE.exec(bodyWithoutFooter) ?? COMPACT_STATUS_RE.exec(bodyWithoutFooter);
  const summaryMatch =
    SUMMARY_BLOCK_RE.exec(bodyWithoutFooter) ?? COMPACT_SUMMARY_RE.exec(bodyWithoutFooter);
  const resultMatch = RESULT_SECTION_RE.exec(bodyWithoutFooter);

  const kind =
    attrs.kind ||
    (employeeMatch || compactSourceMatch?.[1] === '同侪' ? 'employee' : 'worker');
  const mode = attrs.mode || '';
  const jobId = attrs.job_id || (jobLineMatch ? jobLineMatch[1].trim() : '');
  const targetSessionId =
    attrs.worker_session_id ||
    attrs.session_id ||
    attrs.target_session_id ||
    (compactSourceMatch?.[1] === 'Worker' ? compactSourceMatch[2].trim() : '');
  const employeeId =
    attrs.employee_id ||
    (employeeMatch
      ? employeeMatch[1].trim()
      : compactSourceMatch?.[1] === '同侪'
        ? compactSourceMatch[2].trim()
        : '');
  const agentKernel = attrs.kernel || (kernelMatch ? kernelMatch[1].trim() : '');
  const status = attrs.status || (statusLineMatch ? statusLineMatch[1].trim() : 'completed');

  let exitCode: number | null = null;
  if (statusLineMatch && statusLineMatch[2] !== undefined) {
    const parsed = Number.parseInt(statusLineMatch[2], 10);
    if (Number.isFinite(parsed)) exitCode = parsed;
  }

  const taskSummary = summaryMatch ? summaryMatch[1].trim() : '';
  const taskTitle = extractTaskTitle(taskSummary);

  let resultBody: string;
  if (resultMatch) {
    resultBody = resultMatch[1].trim();
  } else if (compactSourceMatch) {
    // 紧凑降级格式：已将来源、单号、状态、诉求提炼至卡片头部与摘要区，正文区保留摘要片段与完整交付指引
    const compactBodyLines = bodyWithoutFooter
      .split(/\r?\n/)
      .filter((line) => !/^-\s*来源：/.test(line) && !/^-\s*诉求：/.test(line))
      .map((line) => line.replace(/^-\s*摘要：/, '').trim())
      .filter(Boolean);
    resultBody = compactBodyLines.length > 0 ? compactBodyLines.join('\n\n') : bodyWithoutFooter;
  } else {
    resultBody = bodyWithoutFooter;
  }

  return {
    kind,
    mode,
    jobId,
    targetSessionId,
    employeeId,
    agentKernel,
    status,
    exitCode,
    taskSummary,
    taskTitle,
    resultBody,
  };
}

function attachBatchMeta(
  items: AsyncCallbackBlockItem[],
  meta: { delivery?: string; batchCount?: number; batchNotice?: string }
): AsyncCallbackBlockItem[] {
  return items.map((item, idx) => {
    const next: AsyncCallbackBlockItem = { ...item };
    if (meta.delivery) next.delivery = meta.delivery;
    if (meta.batchCount !== undefined) next.batchCount = meta.batchCount;
    if (meta.batchNotice && idx === items.length - 1) {
      next.batchNotice = meta.batchNotice;
    }
    return next;
  });
}

function stripBatchBoilerplate(raw: string): { cleaned: string; batchNotice?: string } {
  let current = raw.trim();
  let batchNotice: string | undefined;
  const noticeMatch = BATCH_OMITTED_FOOTER_RE.exec(current);
  if (noticeMatch) {
    batchNotice = noticeMatch[0].trim();
    current = current.replace(noticeMatch[0], '').trim();
  }
  current = current.replace(BATCH_PREAMBLE_HITCHHIKE_RE, '').trim();
  current = current.replace(BATCH_PREAMBLE_IDLE_RE, '').trim();
  current = current
    .replace(/<\/?frago-async-callbacks?(?:\s+[^>]*)?>/gi, '')
    .replace(STRAY_STANDALONE_CLOSE_LINE_RE, '')
    .trim();
  return { cleaned: current, batchNotice };
}

function parseBatchInner(
  outerAttrString: string,
  rawInner: string
): AsyncCallbackBlockItem[] {
  const outerAttrs = parseAttributes(outerAttrString);
  const delivery = outerAttrs.delivery || undefined;
  const parsedCount = outerAttrs.count ? Number.parseInt(outerAttrs.count, 10) : Number.NaN;
  const batchCount =
    Number.isFinite(parsedCount) && parsedCount > 0 ? parsedCount : undefined;

  const items: AsyncCallbackBlockItem[] = [];
  let searchPos = 0;
  let lastConsumedEnd = 0;

  while (searchPos < rawInner.length) {
    const open = findNextSingleOpenTag(rawInner, searchPos);
    if (!open) break;
    const close = findClosingTag(rawInner, open.end, 'frago-async-callback');
    if (close) {
      items.push(parseCallbackBlock(open.attrString, rawInner.slice(open.end, close.closeStart)));
      searchPos = close.closeEnd;
      lastConsumedEnd = close.closeEnd;
    } else {
      // 未闭合的子项：消费到批信封尾部，确保不崩且不外泄标签
      items.push(parseCallbackBlock(open.attrString, rawInner.slice(open.end)));
      searchPos = rawInner.length;
      lastConsumedEnd = rawInner.length;
      break;
    }
  }

  const trailingAfterItems = rawInner.slice(lastConsumedEnd);
  const noticeMatch = BATCH_OMITTED_FOOTER_RE.exec(trailingAfterItems);
  const batchNotice = noticeMatch ? noticeMatch[0].trim() : undefined;

  if (items.length > 0) {
    return attachBatchMeta(items, { delivery, batchCount, batchNotice });
  }

  // 无内部 <frago-async-callback>：处理极窄预算索引行（`- job_id=... status=... report=...`）或纯文本摘要降级
  const { cleaned, batchNotice: fallbackNotice } = stripBatchBoilerplate(rawInner);
  const indexItems: AsyncCallbackBlockItem[] = [];
  NARROW_BUDGET_LINE_RE.lastIndex = 0;
  let idxMatch: RegExpExecArray | null;
  while ((idxMatch = NARROW_BUDGET_LINE_RE.exec(cleaned)) !== null) {
    const jobId = idxMatch[1].trim();
    const status = idxMatch[2].trim();
    const report = (idxMatch[3] ?? '').trim();
    indexItems.push({
      kind: 'worker',
      mode: '',
      jobId,
      targetSessionId: '',
      employeeId: '',
      agentKernel: '',
      status,
      exitCode: null,
      taskSummary: '',
      taskTitle: '',
      resultBody:
        report && report !== '-'
          ? `交付报告：\`${report}\``
          : `派发单号：\`${jobId}\``,
    });
  }

  if (indexItems.length > 0) {
    return attachBatchMeta(indexItems, {
      delivery,
      batchCount,
      batchNotice: batchNotice ?? fallbackNotice,
    });
  }

  return attachBatchMeta(
    [
      {
        kind: 'worker',
        mode: '',
        jobId: '',
        targetSessionId: '',
        employeeId: '',
        agentKernel: '',
        status: 'completed',
        exitCode: null,
        taskSummary: '',
        taskTitle: '',
        resultBody: cleaned || '（后台异步派发回执汇总）',
      },
    ],
    { delivery, batchCount, batchNotice: batchNotice ?? fallbackNotice }
  );
}

/**
 * 剥离消息文本开头的 `<frago-async-callback>` 与 `<frago-async-callbacks>` 块，
 * 返回剩余文本与结构化回调列表。
 */
export function splitAsyncCallbackBlocks(text: string): {
  text: string;
  callbacks: AsyncCallbackBlockItem[];
} {
  if (!text) return { text: '', callbacks: [] };

  const callbacks: AsyncCallbackBlockItem[] = [];
  let cursor = 0;

  while (cursor < text.length) {
    const wsMatch = /^[ \t\r\n]+/.exec(text.slice(cursor));
    const afterWs = wsMatch ? cursor + wsMatch[0].length : cursor;
    const slice = text.slice(afterWs);

    // 1. 优先匹配复数批信封 <frago-async-callbacks ...>
    const batchOpen = BATCH_OPEN_RE.exec(slice);
    if (batchOpen) {
      const outerAttrString = batchOpen[1] ?? '';
      const contentStart = afterWs + batchOpen[0].length;
      const close = findClosingTag(text, contentStart, 'frago-async-callbacks');
      if (close) {
        callbacks.push(...parseBatchInner(outerAttrString, text.slice(contentStart, close.closeStart)));
        cursor = close.closeEnd;
      } else {
        // 畸形/未闭合外层批信封：若内部存在闭合子项且尾部无未闭合子项，则尽量保留尾部人类正文
        const rest = text.slice(contentStart);
        let probePos = 0;
        let lastClosedEnd = -1;
        let hasUnclosedInner = false;
        while (probePos < rest.length) {
          const open = findNextSingleOpenTag(rest, probePos);
          if (!open) break;
          const innerClose = findClosingTag(rest, open.end, 'frago-async-callback');
          if (innerClose) {
            lastClosedEnd = innerClose.closeEnd;
            probePos = innerClose.closeEnd;
          } else {
            hasUnclosedInner = true;
            break;
          }
        }

        if (lastClosedEnd !== -1 && !hasUnclosedInner) {
          let consumedEnd = lastClosedEnd;
          // 跳过可选的省略尾项说明与残留孤立闭合标签
          const afterInner = rest.slice(consumedEnd);
          const leadWs = /^[ \t\r\n]*/.exec(afterInner)?.[0].length ?? 0;
          const afterWsTail = afterInner.slice(leadWs);
          const footerMatch = new RegExp(`^${BATCH_OMITTED_FOOTER_RE.source}`).exec(afterWsTail);
          if (footerMatch) {
            consumedEnd += leadWs + footerMatch[0].length;
          }
          callbacks.push(...parseBatchInner(outerAttrString, rest.slice(0, consumedEnd)));
          cursor = contentStart + consumedEnd;
        } else {
          callbacks.push(...parseBatchInner(outerAttrString, rest));
          cursor = text.length;
        }
      }

      const stray = STRAY_CLOSE_TAGS_RE.exec(text.slice(cursor));
      if (stray) {
        cursor += stray[0].length;
      }
      continue;
    }

    // 2. 匹配单条 <frago-async-callback ...>
    const singleOpen = SINGLE_OPEN_RE.exec(slice);
    if (singleOpen) {
      const attrString = singleOpen[1] ?? '';
      const contentStart = afterWs + singleOpen[0].length;
      const close = findClosingTag(text, contentStart, 'frago-async-callback');
      if (close) {
        callbacks.push(parseCallbackBlock(attrString, text.slice(contentStart, close.closeStart)));
        cursor = close.closeEnd;
      } else {
        // 未闭合单条回调：优雅降级消费到末尾，避免原始标签外泄
        callbacks.push(parseCallbackBlock(attrString, text.slice(contentStart)));
        cursor = text.length;
      }

      const stray = STRAY_CLOSE_TAGS_RE.exec(text.slice(cursor));
      if (stray) {
        cursor += stray[0].length;
      }
      continue;
    }

    break;
  }

  if (callbacks.length === 0) {
    return { text, callbacks: [] };
  }

  const remaining = text.slice(cursor).replace(/^(?:[ \t]*\r?\n)+|^[ \t]+/, '');
  return { text: remaining, callbacks };
}

/**
 * 依次剥离消息开头的员工语境块、技能块与异步回传块（容忍三者在消息头的任意排列顺序）。
 */
export function splitAllLeadingBlocks(rawText: string) {
  let current = rawText || '';
  const employees: ReturnType<typeof splitEmployeeBlocks>['employees'] = [];
  const skills: string[] = [];
  const callbacks: AsyncCallbackBlockItem[] = [];

  for (let pass = 0; pass < 4; pass += 1) {
    let progressed = false;
    const empRes = splitEmployeeBlocks(current);
    if (empRes.employees.length > 0) {
      for (const item of empRes.employees) {
        if (!employees.some((e) => e.id === item.id)) employees.push(item);
      }
      current = empRes.text;
      progressed = true;
    }
    const skillRes = splitSkillBlocks(current);
    if (skillRes.skills.length > 0) {
      for (const name of skillRes.skills) {
        if (!skills.includes(name)) skills.push(name);
      }
      current = skillRes.text;
      progressed = true;
    }
    const cbRes = splitAsyncCallbackBlocks(current);
    if (cbRes.callbacks.length > 0) {
      callbacks.push(...cbRes.callbacks);
      current = cbRes.text;
      progressed = true;
    }
    if (!progressed) break;
  }

  return { text: current, employees, skills, callbacks };
}

/**
 * 判断一条记录是否属于「纯异步回传卡片」（即含 `<frago-async-callback>` 且剥离后无人类输入文字、命令或附图）。
 * 用于缩略滚动条（不画代表人类开口的绿条）、Watcher 提问计数与阶段目标提取。
 */
export function isPureAsyncCallbackRecord(record: {
  kind: string;
  payload: Record<string, unknown>;
}): boolean {
  let rawText = '';
  if (record.kind === 'user.say') {
    if (typeof record.payload.command === 'string' && record.payload.command) return false;
    if (Array.isArray(record.payload.images) && record.payload.images.length > 0) return false;
    rawText = typeof record.payload.text === 'string' ? record.payload.text : '';
  } else if (
    record.kind === 'context.inject' &&
    record.payload.channel === 'queued_command'
  ) {
    rawText = typeof record.payload.body === 'string' ? record.payload.body : '';
  } else {
    return false;
  }

  if (!rawText) return false;
  const { text: withoutBlocks, callbacks } = splitAllLeadingBlocks(rawText);
  if (callbacks.length === 0) return false;
  const { text: humanText, images } = splitAttachedImages(withoutBlocks);
  return !humanText.trim() && images.length === 0;
}

export interface DeduplicatedAsyncCallback {
  callback: AsyncCallbackBlockItem;
  dedupeCount: number;
}

/**
 * 同一批次/来源的异步回传归并键：优先按 `kind + targetSessionId + employeeId` 归并同源回传，
 * 若缺失会话号则退回 `jobId`。
 */
export function asyncCallbackGroupKey(cb: AsyncCallbackBlockItem): string {
  if (cb.targetSessionId) {
    return `${cb.kind}|${cb.targetSessionId}|${cb.employeeId}`;
  }
  return `${cb.kind}|job:${cb.jobId}|${cb.employeeId}`;
}

/**
 * 将同源/同批次的多条异步回传合并为单条代表条目（保留最新一条内容并累计去重次数）。
 */
export function dedupeAsyncCallbacks(
  callbacks: AsyncCallbackBlockItem[]
): DeduplicatedAsyncCallback[] {
  if (callbacks.length <= 1) {
    return callbacks.map((callback) => ({ callback, dedupeCount: 1 }));
  }
  const order: string[] = [];
  const grouped = new Map<string, DeduplicatedAsyncCallback>();
  for (const cb of callbacks) {
    const key = asyncCallbackGroupKey(cb);
    const existing = grouped.get(key);
    if (existing) {
      grouped.set(key, {
        callback: cb,
        dedupeCount: existing.dedupeCount + 1,
      });
    } else {
      order.push(key);
      grouped.set(key, { callback: cb, dedupeCount: 1 });
    }
  }
  return order.map((key) => grouped.get(key)!);
}
