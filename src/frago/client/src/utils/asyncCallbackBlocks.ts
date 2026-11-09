/**
 * 识别并剥离用户消息开头的 `<frago-async-callback ...>...</frago-async-callback>` 块。
 *
 * 下属 Worker 或同侪员工在后台跑完后，异步派发守护进程（`async_dispatch.py`）会把交付结果与
 * 管理者复核提示词包裹在 `<frago-async-callback>` 标签内，经终端 / SDK 注入父会话，在统一记录中
 * 落为 `user.say`（或排队期间的 `queued_command` / `session.state` 入队行）。
 *
 * 与 `<frago-employee>`、`<must-use-skill>` 同理：真实注入的回调块一定出现在消息开头（紧跟可选的
 * 员工/技能块之后）；用户在正文或分支引用里提到的 `<frago-async-callback>` 字面量不在消息开头，
 * 不会被误拆。
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
  /** 退出码（从 `- 执行状态：\`...\` (exit_code=N)` 解析）。 */
  exitCode: number | null;
  /** 完整任务摘要或原始诉求文本。 */
  taskSummary: string;
  /** 任务摘要的单行纯文本标题预览（去掉 Markdown 标题井号与列表前缀）。 */
  taskTitle: string;
  /** 剥离头部元数据与尾部管理者复核样板话术后的交付正文（Markdown）。 */
  resultBody: string;
}

const LEADING_ASYNC_CALLBACK_RE =
  /^\s*(?:<frago-async-callback\s+[^>]*>[\s\S]*?<\/frago-async-callback>\s*)+/;

const SINGLE_ASYNC_CALLBACK_RE =
  /<frago-async-callback\s+([^>]*)>([\s\S]*?)<\/frago-async-callback>/g;

const ATTR_PAIR_RE = /([a-zA-Z0-9_-]+)="([^"]*)"/g;

const WORKER_KERNEL_RE = /【下属 Worker 异步回传】[^\r\n]*?内核：`([^`]+)`/;
const EMPLOYEE_FROM_RE = /【同侪员工异步回传】来自\s*`([^`]+)`/;
const JOB_ID_LINE_RE = /^-\s*派发单号：`([^`]+)`/m;
const STATUS_LINE_RE = /^-\s*执行状态：`([^`]+)`(?:\s*\(exit_code=(-?\d+)\))?/m;
const SUMMARY_BLOCK_RE =
  /^-\s*(?:任务摘要|原始诉求)：([\s\S]*?)(?=\r?\n-\s*执行状态：|\r?\n###\s+(?:Worker 交付结果|同侪员工返回结论)|(?![\s\S]))/m;
const RESULT_SECTION_RE =
  /(?:^|\r?\n)###\s+(?:Worker 交付结果|同侪员工返回结论)\r?\n([\s\S]*)$/;
const TRAILING_MANAGER_PROMPT_RE =
  /\r?\n---\r?\n请(?:作为管理者（Employee）结合领域知识与执行准则审核上述 Worker 产出|基于上述同侪员工回传结论，结合你掌握的领域背景与事务围栏进行复核)[\s\S]*$/;

function parseAttributes(attrString: string): Record<string, string> {
  const attrs: Record<string, string> = {};
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

function parseCallbackBlock(attrString: string, rawInner: string): AsyncCallbackBlockItem {
  const attrs = parseAttributes(attrString);
  const body = rawInner.trim();
  const bodyWithoutFooter = body.replace(TRAILING_MANAGER_PROMPT_RE, '').trim();

  const kernelMatch = WORKER_KERNEL_RE.exec(bodyWithoutFooter);
  const employeeMatch = EMPLOYEE_FROM_RE.exec(bodyWithoutFooter);
  const jobLineMatch = JOB_ID_LINE_RE.exec(bodyWithoutFooter);
  const statusLineMatch = STATUS_LINE_RE.exec(bodyWithoutFooter);
  const summaryMatch = SUMMARY_BLOCK_RE.exec(bodyWithoutFooter);
  const resultMatch = RESULT_SECTION_RE.exec(bodyWithoutFooter);

  const kind = attrs.kind || (employeeMatch ? 'employee' : 'worker');
  const mode = attrs.mode || '';
  const jobId = attrs.job_id || (jobLineMatch ? jobLineMatch[1].trim() : '');
  const targetSessionId = attrs.worker_session_id || attrs.session_id || '';
  const employeeId = attrs.employee_id || (employeeMatch ? employeeMatch[1].trim() : '');
  const agentKernel = attrs.kernel || (kernelMatch ? kernelMatch[1].trim() : '');
  const status = attrs.status || (statusLineMatch ? statusLineMatch[1].trim() : 'completed');

  let exitCode: number | null = null;
  if (statusLineMatch && statusLineMatch[2] !== undefined) {
    const parsed = Number.parseInt(statusLineMatch[2], 10);
    if (Number.isFinite(parsed)) exitCode = parsed;
  }

  const taskSummary = summaryMatch ? summaryMatch[1].trim() : '';
  const taskTitle = extractTaskTitle(taskSummary);
  const resultBody = resultMatch ? resultMatch[1].trim() : bodyWithoutFooter;

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

/**
 * 剥离消息文本开头的 `<frago-async-callback>` 块，返回剩余文本与结构化回调列表。
 */
export function splitAsyncCallbackBlocks(text: string): {
  text: string;
  callbacks: AsyncCallbackBlockItem[];
} {
  if (!text) return { text: '', callbacks: [] };

  const leadingMatch = LEADING_ASYNC_CALLBACK_RE.exec(text);
  if (!leadingMatch) {
    return { text, callbacks: [] };
  }

  const leadingSegment = leadingMatch[0];
  const callbacks: AsyncCallbackBlockItem[] = [];
  SINGLE_ASYNC_CALLBACK_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = SINGLE_ASYNC_CALLBACK_RE.exec(leadingSegment)) !== null) {
    callbacks.push(parseCallbackBlock(match[1] ?? '', match[2] ?? ''));
  }

  if (callbacks.length === 0) {
    return { text, callbacks: [] };
  }

  const remaining = text.slice(leadingSegment.length).replace(/^\r?\n+/, '');
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
