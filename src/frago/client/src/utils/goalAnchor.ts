/**
 * 进展页（PROGRESS LEDGER）Goal Anchor 与 Current State 的清洗、提炼与折叠判定工具。
 *
 * 与服务端 `session_observer._strip_goal_scaffolding` / `extract_goal_summary` 保持对称：
 * 1. 剥离 `<image>`、`<frago-employee>`、`<must-use-skill>`、`<frago-async-callback>` 等前导注入块；
 * 2. 剥离 `[附带图片，请用读文件的工具逐一打开查看]: ...` 与 `[附带文档，请用读文件的工具逐一打开阅读]: ...`
 *    脚手架路径清单；
 * 3. 对长任务书提炼北极星摘要（保留完整干净正文供「展开全文」查看）。
 */

import { splitAllLeadingBlocks } from './asyncCallbackBlocks';
import { splitAttachedImages } from './attachedImages';
import { stripTextQuoteBlocks } from './textQuoteBlocks';
import { stripWebBridgeContext } from './webBridgeContext';

const LEADING_IMAGE_TAG_RE =
  /^\s*(?:<image\b[^>]*>[\s\S]*?<\/image>\s*|<image\b[^>]*\/>\s*)+/i;

const DOC_BLOCK_MARKER = '[附带文档，请用读文件的工具逐一打开阅读]:';

const ROLE_PREAMBLE_RE =
  /^(?:你是[^\n。！？]*?(?:专家|导演|开发者|管理员|助手|参谋)|先运行以下命令|frago\s+book\b|请用读文件的?工具|请查看以下(?:图片|附件)|Spec\s*内容（位于|用户需求[：:]?$)/;

function stripDocAttachmentBlock(raw: string): string {
  let current = raw;
  for (let pass = 0; pass < 4; pass += 1) {
    const idx = current.indexOf(DOC_BLOCK_MARKER);
    if (idx < 0) break;
    const afterStart = idx + DOC_BLOCK_MARKER.length;
    const after = current.slice(afterStart);
    if (!/^\r?\n/.test(after)) break;
    const restMatch = after.search(/\r?\n\s*\r?\n/);
    const rest = restMatch < 0 ? '' : after.slice(restMatch);
    const before = current.slice(0, idx).replace(/[\r\n]+$/, '');
    current = (before && rest ? `${before}${rest}` : before || rest).replace(/\n{3,}/g, '\n\n');
  }
  return current.trim();
}

/**
 * 清洗目标文本：剥除全部系统注入头尾脚手架与内部附件路径，返回纯净的人类需求正文。
 */
export function cleanGoalText(raw?: string | null): string | null {
  if (typeof raw !== 'string') return null;
  let current = raw.trim();
  for (let pass = 0; pass < 6; pass += 1) {
    const prev = current;
    current = current.replace(LEADING_IMAGE_TAG_RE, '').trim();
    current = splitAllLeadingBlocks(current).text.trim();
    if (current === prev) break;
  }
  current = splitAttachedImages(current).text;
  current = stripDocAttachmentBlock(current);
  current = stripWebBridgeContext(current);
  current = stripTextQuoteBlocks(current);
  current = current.replace(/\r?\n{3,}/g, '\n\n').trim();
  if (!current || current.startsWith('【answer】')) return null;
  return current;
}

function clipText(text: string, limit: number): string {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (normalized.length <= limit) return normalized;
  return `${normalized.slice(0, limit)}…`;
}

/**
 * 从清洗后的长 Prompt / 任务书中提炼北极星核心目标摘要；短文本直接原样返回。
 */
export function extractGoalSummary(raw?: string | null, limit = 180): string {
  const cleaned = cleanGoalText(raw);
  if (!cleaned) return '';

  const lines = cleaned.split(/\r?\n/);
  const nonEmptyLines = lines.map((ln) => ln.trim()).filter(Boolean);

  if (
    cleaned.length <= 110 &&
    nonEmptyLines.length <= 3 &&
    !nonEmptyLines.some((ln) => ln.startsWith('#'))
  ) {
    return cleaned;
  }

  let title = '';
  let taskLine = '';

  for (const ln of nonEmptyLines) {
    const namedMatch = /^#{1,3}\s*((?:任务书|任务|目标)[：:]\s*.+)$/.exec(ln);
    if (namedMatch) {
      title = namedMatch[1].replace(/\s+/g, ' ').trim();
      break;
    }
    if (!title) {
      const h1Match = /^#\s+(.+)$/.exec(ln);
      if (h1Match) {
        const cand = h1Match[1].replace(/\s+/g, ' ').trim();
        if (cand.length >= 3) title = cand;
      }
    }
  }

  for (const ln of nonEmptyLines) {
    const taskMatch = /^(?:任务|Task)[：:]\s*(.+)$/.exec(ln);
    if (taskMatch) {
      const cand = taskMatch[1].replace(/\s+/g, ' ').trim();
      if (cand && !title.includes(cand)) {
        taskLine = cand.startsWith('任务') ? cand : `任务：${cand}`;
        break;
      }
    }
  }

  let inCodeFence = false;
  const leadLines: string[] = [];
  let leadLen = 0;

  for (const rawLn of lines) {
    const ln = rawLn.trim();
    if (ln.startsWith('```')) {
      inCodeFence = !inCodeFence;
      continue;
    }
    if (inCodeFence || !ln) continue;
    if (ln.startsWith('#') || ln.startsWith('>') || /^[-*_]{3,}$/.test(ln)) continue;
    if (ROLE_PREAMBLE_RE.test(ln)) continue;
    if (taskLine && taskLine.includes(ln)) continue;
    if (title && title.includes(ln)) continue;

    const plain = ln.replace(/^[-*+]\s+/, '').trim();
    if (plain.length < 4) continue;
    if ((title || taskLine) && /[:：]$/.test(plain)) continue;

    const compact = plain.replace(/\s+/g, ' ');
    leadLines.push(compact);
    leadLen += compact.length;
    if (title || taskLine) break;
    if (leadLen >= limit) break;
  }

  const lead = leadLines.join(' ').trim();
  const parts: string[] = [];
  if (title) parts.push(title);
  if (taskLine && !parts.includes(taskLine) && (!title || !title.includes(taskLine))) {
    parts.push(taskLine);
  }
  if (lead && !parts.some((p) => p.includes(lead) || lead.includes(p))) {
    parts.push(lead);
  }

  if (!parts.length) return clipText(cleaned, limit);
  const joined = parts.join('\n');
  if (joined.length <= limit) return joined;
  if (parts.length >= 2 && parts[0].length < limit - 20) {
    const remain = limit - parts[0].length - 1;
    return `${parts[0]}\n${clipText(parts[1], remain)}`;
  }
  return clipText(joined, limit);
}

/**
 * 判断一段文本在 PROGRESS LEDGER 双栏卡片内是否超出紧凑展示阈值，需要默认折叠并提供「展开全文」。
 */
export function isLongLedgerText(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (trimmed.length > 110) return true;
  const lineCount = trimmed.split(/\r?\n/).filter((ln) => ln.trim().length > 0).length;
  return lineCount > 3;
}
