/**
 * RecordStream — 中栏：记录流、滚动状态机、同一次回复的视觉归组。
 *
 * 三条纪律：
 *
 * 1. **打开会话落在最新内容上。** 数据侧尾部优先（先取最后两百条，往上翻才前插旧页），
 *    视口在首屏渲染时沉到底。最新内容永远在底部，跟所有聊天界面一个方向。
 * 2. **自动滚动是个会听人话的状态机。** 默认武装：新条目进来时视口跟着沉到底。人手动
 *    滚动（滚轮、触摸、拖滚动条、翻页键）离开底部就解除；手动回到底部立即重新武装；
 *    解除后超过十秒没再手动滚动，新条目进来时自动滚动复活。程序自己滚的（沉底、前插
 *    锚定）不算手动，NEVER 因此解除——平滑滚动一路经过的中间位置全都不在底部，被当成
 *    人滚的就会把跟随解除掉，症状是「滚着滚着就不跟了」，而且极难复现。反过来，人一
 *    伸手（滚轮/触摸/按键）就立刻作废程序那次滚动的余波，不许拿动画挡住人的意图。
 * 2b. **跟到底这件事，近处滑、远处落。** 一条新记录通常只把内容顶高几百像素，那一段用
 *    动画滑过去，人眼跟得住"又来了一条"；一次前插或整流重取动辄上万像素，那种距离拿
 *    动画滑等于让人干等半秒还看不清落点，直接落位反而清楚。
 * 3. **同一次模型回复要视觉归组，分组编号不显示。** `group_id` 是三十几位的机器标识，
 *    对人零意义。归组只体现为一个包住多张卡的容器，容器头写模型名与本组条数。
 * 4. **默认只看对话，看哪一类由人挑，条数照实报。** 一场会话里对话只占几十分之一，其余
 *    是工具、旁路注入和引擎记账。全都铺开是"什么都在"，也是"什么都找不着"，所以打开
 *    就落在**对话**那一档上。顶上给一排镜头，每一档带真实条数——**筛掉的东西必须在条数
 *    上看得见**，否则筛完像是那些事没发生过。
 */

import {
  Fragment,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  type UIEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowDown,
  ArrowUpRight,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  ExternalLink,
  Inbox,
  Loader2,
  X,
} from 'lucide-react';
import { DecisionCard, DecisionCardContext } from './DecisionCard';
import { jumpToPendingCard } from './ReportPanel';
import RecordCard, {
  KIND_GROUP,
  RecordStreamActionsContext,
  SystemRun,
  ToolRun,
  formatClock,
  formatDuration,
  previewArgs,
  type DeliveryTriadData,
  type DeliveryTriadFile,
  type RecordStreamActions,
  type ToolRow,
} from './RecordCard';
import SelectionQuote, {
  HIGHLIGHT_PRIORITY,
  RECORD_BODY_ATTR,
  findMarkRange,
  flatten,
  markSpan,
  paintHighlight,
  rangeOf,
  type BranchExtras,
  type MarkAnchor,
} from './SelectionQuote';
import FileViewer, {
  type FileEditSendPayload,
  type PackedAnnotationsPayload,
} from './FileViewer';
import { revealPath } from '@/api';
import type { SessionChildrenResponse, SessionFileRow } from '@/types/api';
import { FileLinkContext, type FileLinkTarget } from '@/components/ui/MarkdownContent';
import EmptyState from '@/components/ui/EmptyState';
import type { LocateState } from './StackPanel';
import type { ComposerUsage } from './Composer';
import { formatTokensK, formatTokensM } from './filePaths';
import {
  asyncCallbackGroupKey,
  isPureAsyncCallbackRecord,
  splitAllLeadingBlocks,
} from '@/utils/asyncCallbackBlocks';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import SendProgress from './SendProgress';
import StreamMinimap from './StreamMinimap';
import {
  AGENT_ACTIVITY,
  MAX_BACKFILL_PAGES,
  MIN_TALK_RECORDS,
  PAGE_SIZE,
  isLifecycleStopRecord,
  queueOpOf,
  queueOutcomes,
  trailSettled,
  type SendTrail,
  type WorkbenchRecord,
} from '@/hooks/useWorkbenchRecords';
import {
  parseUiComponentOutput,
  splitTrailingBlock,
  trailingDecision,
  type DecisionBlock,
} from '@/utils/decisionBlock';
import { parseAllImageGridOutputs } from '@/utils/imageGridBlock';
import { cleanGoalText, extractGoalSummary, isLongLedgerText } from '@/utils/goalAnchor';
import { isCompletedWatcherTask, partitionTasksForOverview } from '@/utils/tasksOverview';
import { computeProgressBadge, matchActorToChildSession } from '@/utils/sessionChildrenTree';
import { ProgressDelegationSection, ProgressOriginStrip } from './ProgressChildrenSection';
import { parseTextQuoteBlocks } from '@/utils/textQuoteBlocks';
import { parseWebBridgeContext } from '@/utils/webBridgeContext';
import { scrollBehavior } from '@/utils/reducedMotion';
import type { ObserverTail, ObserverTaskItem, SessionObserverView } from '@/hooks/useSessionObserver';

/** 中栏的镜头。一次只看一类，条数照实报。 */
export type StreamLens = 'all' | 'talk' | 'hook' | 'tool' | 'system';

/** 每一档的**词表键**。取字在渲染时做，换语言这一排跟着变。 */
export const LENS_LABEL_KEY: Record<StreamLens, string> = {
  all: 'workbench.stream.lens.all',
  talk: 'workbench.stream.lens.talk',
  hook: 'workbench.stream.lens.hook',
  tool: 'workbench.stream.lens.tool',
  system: 'workbench.stream.lens.system',
};

export const LENS_ORDER: StreamLens[] = ['all', 'talk', 'hook', 'tool', 'system'];

/** 这条记录归哪个镜头。一条只归一档，加起来正好是全部。 */
export function lensOf(record: WorkbenchRecord): Exclude<StreamLens, 'all'> {
  if (record.kind === 'user.say' || record.kind === 'agent.say' || record.kind === 'agent.think') {
    return 'talk';
  }
  if (record.kind === 'context.inject') {
    // 插话归**对话**，不归系统。人在 agent 干活时打的那句话在会话记录里没有「用户消息」
    // 那种形态，这张卡是它唯一的痕迹；把它摆进系统那一档，等于让它跟引擎记账混在一起。
    // 后果不是不好看：切到「对话」看这段会话，会看到 agent 突然转向去做另一件事，而
    // 没有任何东西解释它为什么转向——那句话明明是人说的，却在人的发言里找不到。
    if (record.payload.channel === 'queued_command') return 'talk';
    // 后台任务通知同理：agent 常常是读到"任务失败了"才转去查原因，把它筛掉，对话里
    // 就只剩一次没头没尾的转向。
    if (record.payload.source === 'task-notification') return 'talk';
    return record.payload.source === 'hook' ? 'hook' : 'system';
  }
  // 插话队列里还在排的那句话归**对话**：agent 正忙，那句话此刻只有入队这一行痕迹，
  // 输入区的信封见到它就退场了，对话里再不摆，人就找不到自己刚说的话。等它被并入或
  // 发出，插话卡或那一轮的「你说」会接着站，这一行退回系统档，免得同一句话摆两遍。
  // 后台任务的通知也走这条队列，那不是人说的话，不进对话。
  const q = queueOpOf(record);
  if (
    q?.op === 'enqueue' &&
    record.payload.queue_state === 'pending' &&
    !q.content.startsWith('<task-notification>')
  ) {
    return 'talk';
  }
  return KIND_GROUP[record.kind] === 'tool' ? 'tool' : 'system';
}

/**
 * 判断一条（已经过 `withQueueOutcomes` 归一化的）记录在「对话（Talk）」镜头下是否画成
 * 独立可见的对话气泡。
 *
 * `agent.think` 在 Talk 镜头下由 `buildTalkSegments` 与 `tool.call` 一起折叠进响应前的
 * `{num}次工具调用 · {num}次thinking` 聚合行，不作为独立气泡渲染；而当轮尚无 `agent.say`
 * 接管时，未移交的 UI 交互卡 / 图片网格 `tool.result` 会在 Talk 里兜底画成气泡。
 */
export function isTalkBubbleRecord(record: WorkbenchRecord): boolean {
  if (record.kind === 'agent.think') return false;
  if (
    record.kind === 'tool.result' &&
    !record.agent_path.length &&
    record.payload.ui_component_delegated !== true
  ) {
    const body = typeof record.payload.body === 'string' ? record.payload.body : '';
    const uiCard = body
      ? parseUiComponentOutput(body, record.payload.ui_component_broken === true)
      : null;
    const imageGrids =
      record.payload.status !== 'error' && body ? parseAllImageGridOutputs(body) : [];
    if (uiCard !== null || imageGrids.length > 0) return true;
  }
  return lensOf(record) === 'talk';
}

const ASK_CMD_CALL_RE = /\bfrago(?:\.exe)?\s+(?:app\s+)?ask\b/;
const ASK_CMD_HELP_RE = /\s(?:-h|--help)\b/;

function isAskToolCall(record: WorkbenchRecord): boolean {
  if (record.kind !== 'tool.call' || record.agent_path.length > 0) return false;
  const args = record.payload.args;
  if (!args || typeof args !== 'object' || Array.isArray(args)) return false;
  const obj = args as Record<string, unknown>;
  const cmd =
    typeof obj.command === 'string'
      ? obj.command
      : typeof obj.cmd === 'string'
        ? obj.cmd
        : '';
  return Boolean(cmd && ASK_CMD_CALL_RE.test(cmd) && !ASK_CMD_HELP_RE.test(cmd));
}

/**
 * 正文类记录：人发言、代理回复、思考、插话。
 *
 * 引用与暂存的标注只在这几种里记锚点、着色、找原处；工具调用、钩子、系统记录大多是折叠
 * 的卡，文字时有时无，定位不稳（spec 20260928-webui-session-stack「不做什么」第 5 条）。
 */
export function isBodyRecord(record: WorkbenchRecord): boolean {
  if (record.kind === 'user.say' || record.kind === 'agent.say' || record.kind === 'agent.think') {
    return true;
  }
  return record.kind === 'context.inject' && record.payload.channel === 'queued_command';
}

/**
 * 将每一轮（两次主会话用户发言之间）中 `frago ask` 工具结果产出的交互卡数据，
 * 挂载到该轮最后一条主会话 `agent.say`（即收尾 Stop 消息）的末尾渲染。
 *
 * 工具调用在物理时序上必定发生在收尾回复之前；若把卡片直接原位画在 `tool.result` 上，
 * 卡片就会出现在收尾消息上方，而收尾消息里写的却是「请在下方卡片中选择」。
 * 挂载到当轮最后一条 `agent.say` 后，卡片永远紧贴在收尾消息正文的最下方；仅当该轮尚无
 * 任何 `agent.say` 时，才保留在最后一条 `tool.result` 上兜底显示。
 * 当轮若无有效卡片但存在报错的 `frago ask` 输出，同样挂载到收尾回复（或原位兜底）展示代码块与报错说明。
 */
const FILE_EDIT_TOOLS = new Set([
  'write',
  'edit',
  'multiedit',
  'notebookedit',
  'create_file',
  'write_file',
  'edit_file',
  'write_to_file',
  'replace_file_content',
  'multi_replace_file_content',
  'apply_patch',
]);
const VERIFY_CMD_RE =
  /\b(?:pytest|vitest|npm\s+(?:run\s+)?(?:test|build|lint|type-check)|npx\s+vitest|tsc|cargo\s+test|go\s+test|jest|playwright|ruff|mypy|uv\s+run\s+pytest)\b/i;

function countTextLines(v: unknown): number {
  if (typeof v !== 'string' || !v) return 0;
  return v.split(/\r?\n/).length;
}

function isAbsFilePath(p: string): boolean {
  return p.startsWith('/') || /^[A-Za-z]:[\\/]/.test(p) || p.startsWith('\\\\');
}

function joinWithSessionCwd(rawPath: string, cwd: string | null): string {
  const clean = rawPath.trim();
  if (!clean || !cwd || isAbsFilePath(clean) || clean.startsWith('~')) return clean;
  const base = cwd.replace(/\/+$/, '');
  const rel = clean.replace(/^\.\//, '');
  return `${base}/${rel}`;
}

export function extractApplyPatchEdits(
  patchText: string,
  sessionCwd: string | null = null
): Array<{ path: string; add: number; del: number }> {
  const results: Array<{ path: string; add: number; del: number }> = [];
  let current: { path: string; add: number; del: number; mode: 'add' | 'update' | 'delete' } | null =
    null;

  const flush = () => {
    if (current && current.path) {
      results.push({ path: current.path, add: current.add, del: current.del });
    }
    current = null;
  };

  for (const rawLine of patchText.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    const headerMatch = /^\*\*\*\s+(Add|Update|Delete) File:\s*(.+?)\s*$/.exec(line);
    if (headerMatch) {
      flush();
      const action = headerMatch[1].toLowerCase() as 'add' | 'update' | 'delete';
      const target = joinWithSessionCwd(headerMatch[2], sessionCwd);
      current = { path: target, add: 0, del: 0, mode: action };
      continue;
    }
    const moveMatch = /^\*\*\*\s+Move to:\s*(.+?)\s*$/.exec(line);
    if (moveMatch && current) {
      current.path = joinWithSessionCwd(moveMatch[1], sessionCwd);
      continue;
    }
    if (line.startsWith('*** ')) {
      if (line.startsWith('*** End Patch')) flush();
      continue;
    }
    if (!current) continue;
    if (line.startsWith('+') && !line.startsWith('+++')) {
      current.add += 1;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      current.del += 1;
    } else if (current.mode === 'add' && line.length > 0 && !line.startsWith('@@')) {
      current.add += 1;
    }
  }
  flush();
  return results;
}

function extractFileEditStats(
  toolName: string,
  args: Record<string, unknown>,
  sessionCwd: string | null = null
): Array<{ path: string; add: number; del: number }> {
  const lower = toolName.toLowerCase();
  if (!FILE_EDIT_TOOLS.has(lower)) return [];
  if (lower === 'apply_patch') {
    const patchText =
      typeof args.input === 'string'
        ? args.input
        : typeof args.patch === 'string'
          ? args.patch
          : typeof args.raw === 'string'
            ? args.raw
            : '';
    return patchText ? extractApplyPatchEdits(patchText, sessionCwd) : [];
  }
  const path =
    typeof args.file_path === 'string'
      ? args.file_path
      : typeof args.filePath === 'string'
        ? args.filePath
        : typeof args.path === 'string'
          ? args.path
          : typeof args.TargetFile === 'string'
            ? args.TargetFile
            : typeof args.AbsolutePath === 'string'
              ? args.AbsolutePath
              : typeof args.notebook_path === 'string'
                ? args.notebook_path
                : typeof args.NotebookPath === 'string'
                  ? args.NotebookPath
                  : typeof args.target_file === 'string'
                    ? args.target_file
                    : '';
  const cleanedPath = path.trim().replace(/^"(.*)"$/, '$1').trim();
  if (!cleanedPath) return [];
  let add = 0;
  let del = 0;
  if (typeof args.new_string === 'string' || typeof args.old_string === 'string') {
    add = countTextLines(args.new_string);
    del = countTextLines(args.old_string);
  } else if (typeof args.content === 'string' || typeof args.CodeContent === 'string') {
    add = countTextLines(args.content ?? args.CodeContent);
  } else if (typeof args.ReplacementContent === 'string' || typeof args.TargetContent === 'string') {
    add = countTextLines(args.ReplacementContent);
    del = countTextLines(args.TargetContent);
  } else if (Array.isArray(args.edits)) {
    for (const ed of args.edits) {
      if (ed && typeof ed === 'object' && !Array.isArray(ed)) {
        const e = ed as Record<string, unknown>;
        add += countTextLines(e.new_string);
        del += countTextLines(e.old_string);
      }
    }
  }
  return [{ path: cleanedPath, add, del }];
}

function summarizeReplyConclusion(rawText: string): string {
  const withoutGrid = rawText.replace(/```[\s\S]*?```/g, '').trim();
  const firstLine = withoutGrid
    .split(/\r?\n/)
    .map((l) => l.replace(/^[#>*\-\s]+/, '').replace(/[*_`]/g, '').trim())
    .find(Boolean);
  if (!firstLine) return '';
  return firstLine.length > 180 ? `${firstLine.slice(0, 177)}...` : firstLine;
}

export function withTurnDecisionCards(records: WorkbenchRecord[]): WorkbenchRecord[] {
  const delegateToolIndices = new Set<number>();
  const markBrokenToolIndices = new Set<number>();
  const attachToAgentSay = new Map<number, string>();
  const attachImagesToAgentSay = new Map<number, string[]>();
  const attachContextToAgentSay = new Map<number, number>();
  const attachTriadToAgentSay = new Map<number, DeliveryTriadData>();

  let turnToolIndices: number[] = [];
  let turnToolBody = '';
  let turnBrokenToolIndices: number[] = [];
  let turnBrokenToolBody = '';
  let turnAskCallIds = new Set<string>();
  let turnImageIndices: number[] = [];
  let turnImageBodies: string[] = [];
  let turnInlineCardAgentIndices: number[] = [];
  let lastAgentSayIdx = -1;
  let turnContextTokens: number | null = null;
  let sessionCwd: string | null = null;
  let turnPendingFileCalls = new Map<string, Array<{ path: string; add: number; del: number }>>();
  let turnFileEdits = new Map<string, { add: number; del: number }>();
  let turnPendingVerifyCalls = new Map<string, string>();
  let turnLastVerifyCmd = '';

  const flushTurn = () => {
    if (turnToolIndices.length) {
      for (const idx of turnBrokenToolIndices) delegateToolIndices.add(idx);
      if (lastAgentSayIdx >= 0) {
        for (const idx of turnToolIndices) delegateToolIndices.add(idx);
        attachToAgentSay.set(lastAgentSayIdx, turnToolBody);
        for (const idx of turnInlineCardAgentIndices) {
          if (idx !== lastAgentSayIdx) delegateToolIndices.add(idx);
        }
      } else if (turnToolIndices.length > 1) {
        for (let k = 0; k < turnToolIndices.length - 1; k += 1) {
          delegateToolIndices.add(turnToolIndices[k]);
        }
      }
    } else if (turnBrokenToolIndices.length) {
      if (lastAgentSayIdx >= 0) {
        for (const idx of turnBrokenToolIndices) delegateToolIndices.add(idx);
        attachToAgentSay.set(lastAgentSayIdx, turnBrokenToolBody);
        for (const idx of turnInlineCardAgentIndices) {
          if (idx !== lastAgentSayIdx) delegateToolIndices.add(idx);
        }
      } else {
        for (let k = 0; k < turnBrokenToolIndices.length - 1; k += 1) {
          delegateToolIndices.add(turnBrokenToolIndices[k]);
        }
        markBrokenToolIndices.add(turnBrokenToolIndices[turnBrokenToolIndices.length - 1]);
      }
    } else if (turnInlineCardAgentIndices.length > 1) {
      for (let k = 0; k < turnInlineCardAgentIndices.length - 1; k += 1) {
        delegateToolIndices.add(turnInlineCardAgentIndices[k]);
      }
    }
    if (turnImageIndices.length && lastAgentSayIdx >= 0) {
      for (const idx of turnImageIndices) delegateToolIndices.add(idx);
      attachImagesToAgentSay.set(lastAgentSayIdx, [...turnImageBodies]);
    }
    if (lastAgentSayIdx >= 0 && turnContextTokens !== null) {
      attachContextToAgentSay.set(lastAgentSayIdx, turnContextTokens);
    }
    if (lastAgentSayIdx >= 0 && (turnFileEdits.size > 0 || turnLastVerifyCmd)) {
      const sayRecord = records[lastAgentSayIdx];
      const existingTriad = sayRecord.payload.delivery_triad;
      const sayText = typeof sayRecord.payload.text === 'string' ? sayRecord.payload.text : '';
      if (!existingTriad && sayText.trim()) {
        const files: DeliveryTriadFile[] = Array.from(turnFileEdits.entries()).map(
          ([path, counts]) => ({
            path,
            name: path.split('/').pop() || path,
            add: counts.add,
            del: counts.del,
          })
        );
        attachTriadToAgentSay.set(lastAgentSayIdx, {
          conclusion: summarizeReplyConclusion(sayText),
          files,
          verifyCommand: turnLastVerifyCmd,
          verifyPassed: true,
        });
      }
    }
    turnToolIndices = [];
    turnToolBody = '';
    turnBrokenToolIndices = [];
    turnBrokenToolBody = '';
    turnAskCallIds = new Set<string>();
    turnImageIndices = [];
    turnImageBodies = [];
    turnInlineCardAgentIndices = [];
    lastAgentSayIdx = -1;
    turnContextTokens = null;
    turnPendingFileCalls = new Map();
    turnFileEdits = new Map();
    turnPendingVerifyCalls = new Map();
    turnLastVerifyCmd = '';
  };

  for (let i = 0; i < records.length; i += 1) {
    const r = records[i];
    if (
      !sessionCwd &&
      r.kind === 'session.state' &&
      typeof r.payload.cwd === 'string' &&
      r.payload.cwd.trim()
    ) {
      sessionCwd = r.payload.cwd.trim();
    }
    if (!r.agent_path.length) {
      const isHumanTurnBoundary =
        r.kind === 'user.say' ||
        (r.kind === 'context.inject' && r.payload.channel === 'queued_command');
      if (isHumanTurnBoundary) {
        flushTurn();
        continue;
      }
      if (r.kind === 'usage.tick') {
        const ctx = typeof r.payload.context_tokens === 'number' ? r.payload.context_tokens : null;
        if (ctx !== null) {
          turnContextTokens = ctx;
          if (lastAgentSayIdx >= 0) {
            attachContextToAgentSay.set(lastAgentSayIdx, ctx);
          }
        }
        continue;
      }
      if (r.kind === 'agent.say') {
        lastAgentSayIdx = i;
        if (turnContextTokens !== null) {
          attachContextToAgentSay.set(i, turnContextTokens);
        }
        const text = typeof r.payload.text === 'string' ? r.payload.text : '';
        if (text && (splitTrailingBlock(text) || parseUiComponentOutput(text)?.ok)) {
          turnInlineCardAgentIndices.push(i);
        }
        continue;
      }
      if (r.kind === 'tool.call') {
        const callId = typeof r.payload.call_id === 'string' ? r.payload.call_id : '';
        if (isAskToolCall(r)) {
          if (callId) turnAskCallIds.add(callId);
        }
        const toolName = typeof r.payload.tool_name === 'string' ? r.payload.tool_name : '';
        const args =
          r.payload.args && typeof r.payload.args === 'object' && !Array.isArray(r.payload.args)
            ? (r.payload.args as Record<string, unknown>)
            : {};
        const fileEdits = extractFileEditStats(toolName, args, sessionCwd);
        if (fileEdits.length > 0) {
          if (callId) {
            const existing = turnPendingFileCalls.get(callId) ?? [];
            turnPendingFileCalls.set(callId, [...existing, ...fileEdits]);
          } else {
            for (const fileEdit of fileEdits) {
              const cur = turnFileEdits.get(fileEdit.path) ?? { add: 0, del: 0 };
              turnFileEdits.set(fileEdit.path, {
                add: cur.add + fileEdit.add,
                del: cur.del + fileEdit.del,
              });
            }
          }
        }
        const cmd =
          typeof args.command === 'string'
            ? args.command
            : typeof args.cmd === 'string'
              ? args.cmd
              : typeof args.CommandLine === 'string'
                ? args.CommandLine
                : '';
        if (cmd && VERIFY_CMD_RE.test(cmd)) {
          if (callId) turnPendingVerifyCalls.set(callId, cmd.trim());
          else turnLastVerifyCmd = cmd.trim();
        }
        continue;
      }
      if (r.kind === 'tool.result') {
        const body = typeof r.payload.body === 'string' ? r.payload.body : '';
        const callId = typeof r.payload.call_id === 'string' ? r.payload.call_id : '';
        const status = typeof r.payload.status === 'string' ? r.payload.status : '';
        if (callId && status !== 'error' && status !== 'denied') {
          const pendingEdits = turnPendingFileCalls.get(callId);
          if (pendingEdits && pendingEdits.length > 0) {
            for (const pendingEdit of pendingEdits) {
              const cur = turnFileEdits.get(pendingEdit.path) ?? { add: 0, del: 0 };
              turnFileEdits.set(pendingEdit.path, {
                add: cur.add + pendingEdit.add,
                del: cur.del + pendingEdit.del,
              });
            }
            turnPendingFileCalls.delete(callId);
          }
          const pendingVerify = turnPendingVerifyCalls.get(callId);
          if (pendingVerify) {
            turnLastVerifyCmd = pendingVerify;
            turnPendingVerifyCalls.delete(callId);
          }
        }
        if (body) {
          const isFailedAskCall = Boolean(
            callId && turnAskCallIds.has(callId) && status === 'error'
          );
          const uiCard = parseUiComponentOutput(body, isFailedAskCall);
          if (uiCard) {
            if (uiCard.ok && status !== 'error') {
              turnToolIndices.push(i);
              turnToolBody = body;
            } else {
              turnBrokenToolIndices.push(i);
              turnBrokenToolBody = body;
            }
          }
          if (status !== 'error') {
            const imageGrids = parseAllImageGridOutputs(body);
            if (imageGrids.length > 0) {
              turnImageIndices.push(i);
              turnImageBodies.push(body);
            }
          }
        }
      }
    }
  }
  flushTurn();

  if (
    !delegateToolIndices.size &&
    !markBrokenToolIndices.size &&
    !attachToAgentSay.size &&
    !attachImagesToAgentSay.size &&
    !attachContextToAgentSay.size &&
    !attachTriadToAgentSay.size
  ) {
    return records;
  }

  return records.map((r, idx) => {
    if (delegateToolIndices.has(idx)) {
      return r.payload.ui_component_delegated === true
        ? r
        : { ...r, payload: { ...r.payload, ui_component_delegated: true } };
    }
    if (markBrokenToolIndices.has(idx)) {
      return r.payload.ui_component_broken === true
        ? r
        : { ...r, payload: { ...r.payload, ui_component_broken: true } };
    }
    const attached = attachToAgentSay.get(idx);
    const attachedImages = attachImagesToAgentSay.get(idx);
    const attachedContext = attachContextToAgentSay.get(idx);
    const attachedTriad = attachTriadToAgentSay.get(idx);
    if (
      attached !== undefined ||
      attachedImages !== undefined ||
      attachedContext !== undefined ||
      attachedTriad !== undefined
    ) {
      const nextPayload: Record<string, unknown> = { ...r.payload };
      if (attached !== undefined) {
        nextPayload.ui_component = attached;
      }
      if (attachedImages !== undefined) {
        nextPayload.ui_image_grids = attachedImages;
      }
      if (attachedContext !== undefined) {
        nextPayload.context_tokens = attachedContext;
      }
      if (attachedTriad !== undefined) {
        nextPayload.delivery_triad = attachedTriad;
      }
      return { ...r, payload: nextPayload };
    }
    return r;
  });
}

function withAsyncCallbackMetadata(records: WorkbenchRecord[]): WorkbenchRecord[] {
  let hasPure = false;
  for (const r of records) {
    if (isPureAsyncCallbackRecord(r)) {
      hasPure = true;
      break;
    }
  }
  if (!hasPure) return records;

  const out: WorkbenchRecord[] = [];
  for (let i = 0; i < records.length; i += 1) {
    const r = records[i];
    if (!isPureAsyncCallbackRecord(r)) {
      out.push(r);
      continue;
    }
    const raw =
      r.kind === 'user.say'
        ? String(r.payload.text ?? '')
        : String(r.payload.body ?? '');
    const { callbacks } = splitAllLeadingBlocks(raw);
    const primaryKey = callbacks.length === 1 ? asyncCallbackGroupKey(callbacks[0]) : null;
    const isQueuedPending =
      r.kind === 'context.inject' &&
      r.payload.channel === 'queued_command' &&
      r.payload.queue_state === 'pending';

    let consumed = false;
    if (!isQueuedPending) {
      for (let j = i + 1; j < records.length; j += 1) {
        const next = records[j];
        if (!next.agent_path.length && (next.kind === 'agent.say' || next.kind === 'tool.call')) {
          consumed = true;
          break;
        }
      }
    }
    const stage = consumed ? 'consumed' : 'delivered';

    // 合并相邻同源的纯异步回传记录，保留最新那一条并累计去重计数
    const prev = out[out.length - 1];
    if (prev && primaryKey && isPureAsyncCallbackRecord(prev)) {
      const prevRaw =
        prev.kind === 'user.say'
          ? String(prev.payload.text ?? '')
          : String(prev.payload.body ?? '');
      const prevCbs = splitAllLeadingBlocks(prevRaw).callbacks;
      const prevKey = prevCbs.length === 1 ? asyncCallbackGroupKey(prevCbs[0]) : null;
      if (prevKey === primaryKey) {
        const prevCount =
          typeof prev.payload.async_callback_dedupe === 'number'
            ? prev.payload.async_callback_dedupe
            : 1;
        out[out.length - 1] = {
          ...r,
          payload: {
            ...r.payload,
            async_callback_dedupe: prevCount + 1,
            async_callback_stage: stage,
          },
        };
        continue;
      }
    }

    out.push({
      ...r,
      payload: {
        ...r.payload,
        async_callback_stage: stage,
      },
    });
  }
  return out;
}

/**
 * 给入队的那几行写上此刻的下场（见 `queueOutcomes`），并将当轮 `frago ask` 交互卡挂载到收尾回复末尾。
 * 其余记录原样返回，一条不复制。
 *
 * 镜头归属与卡上那枚下场标签都照这个值走，所以必须在分档之前做。
 */
export function withQueueOutcomes(records: WorkbenchRecord[]): WorkbenchRecord[] {
  const outcomes = queueOutcomes(records);
  const queued = !outcomes.size
    ? records
    : records.map((r) => {
        const state = outcomes.get(r.id);
        return state && r.payload.queue_state !== state
          ? { ...r, payload: { ...r.payload, queue_state: state } }
          : r;
      });
  return withAsyncCallbackMetadata(withTurnDecisionCards(queued));
}

/**
 * 「对话」那一档实际摆出来的记录：仅保留真实可见对话与兜底卡片，用量读数已内联挂载至回复头。
 *
 * 当轮 `frago ask` 产出的交互卡已由 `withTurnDecisionCards` 挂载到当轮最后一条 `agent.say`
 * （收尾消息）的正文下方；仅当某轮完全没有 `agent.say` 时，才捎带未移交的 `tool.result` 兜底显示。
 */
export function talkView(records: WorkbenchRecord[]): WorkbenchRecord[] {
  const normalized = withTurnDecisionCards(records);
  const out: WorkbenchRecord[] = [];
  for (let i = 0; i < normalized.length; i += 1) {
    const record = normalized[i];
    if (record.kind === 'usage.tick') {
      continue;
    }
    if (
      record.kind === 'tool.result' &&
      !record.agent_path.length &&
      record.payload.ui_component_delegated !== true
    ) {
      const body = typeof record.payload.body === 'string' ? record.payload.body : '';
      const uiCard = body
        ? parseUiComponentOutput(body, record.payload.ui_component_broken === true)
        : null;
      const imageGrids =
        record.payload.status !== 'error' && body ? parseAllImageGridOutputs(body) : [];
      if (uiCard !== null || imageGrids.length > 0) {
        out.push(record);
        continue;
      }
    }
    if (lensOf(record) !== 'talk') continue;
    out.push(record);
  }
  return out;
}

/** 一段连续的、属于同一次模型回复的记录。`groupId` 只用于分段，永不显示。 */
export interface RecordGroup {
  groupId: string | null;
  records: WorkbenchRecord[];
}

/**
 * 把记录流切成段。相邻且 `group_id` 相同的归一段；`group_id` 为空的各自独立成段。
 *
 * 只并相邻的，不跨段回收——记录的权威顺序是物理序，跨段并会把顺序搅乱。
 */
export function groupRecords(records: WorkbenchRecord[]): RecordGroup[] {
  const groups: RecordGroup[] = [];
  for (const record of records) {
    const last = groups[groups.length - 1];
    if (record.group_id && last && last.groupId === record.group_id) {
      last.records.push(record);
      continue;
    }
    groups.push({ groupId: record.group_id, records: [record] });
  }
  return groups;
}

/**
 * 记录流里的一段：一条原样的记录，或一串被并起来的同类记录。
 *
 * - `tools`：连续的工具调用与结果，按 `call_id` 配对成行。夹在中间的空正文 hook 注入、
 *   用量刻度、空思考不打断这一段，收进 `extras`，框底写明并进了几条。
 * - `system`：连续的系统记录（报错除外）压成一行。
 */
export type StreamSegment =
  | { kind: 'record'; record: WorkbenchRecord }
  | {
      kind: 'talk-agg';
      key: string;
      toolCalls: number;
      thinkingSteps: number;
      records: WorkbenchRecord[];
      groupId: string | null;
    }
  | { kind: 'tools'; key: string; rows: ToolRow[]; extras: WorkbenchRecord[]; records: WorkbenchRecord[] }
  | { kind: 'system'; key: string; records: WorkbenchRecord[] };

/**
 * 将「All 里显示但 Talk 里原本不显示」的响应前动作（工具调用与思考步骤）
 * 在每一条 `agent.say` 回复出现前自动叠加为单行 `{num}次工具调用 · {num}次thinking`，
 * 数字原位自增，不出现刷新式多行递增。
 */
export function buildTalkSegments(records: WorkbenchRecord[]): StreamSegment[] {
  const normalized = withTurnDecisionCards(records);
  const out: StreamSegment[] = [];
  let pendingTools = 0;
  let pendingThinking = 0;
  let pendingRecords: WorkbenchRecord[] = [];

  const flushPreResponse = (followingGroupId: string | null = null) => {
    if (pendingTools === 0 && pendingThinking === 0) return;
    const firstId = pendingRecords[0]?.id ?? `idx-${out.length}`;
    const sharedGroup =
      followingGroupId &&
      pendingRecords.length > 0 &&
      pendingRecords.every((r) => r.group_id === followingGroupId)
        ? followingGroupId
        : pendingRecords.length > 0 &&
            pendingRecords[0].group_id &&
            pendingRecords.every((r) => r.group_id === pendingRecords[0].group_id)
          ? pendingRecords[0].group_id
          : null;
    out.push({
      kind: 'talk-agg',
      key: `talk-agg:${firstId}`,
      toolCalls: pendingTools,
      thinkingSteps: pendingThinking,
      records: pendingRecords,
      groupId: sharedGroup,
    });
    pendingTools = 0;
    pendingThinking = 0;
    pendingRecords = [];
  };

  for (let i = 0; i < normalized.length; i += 1) {
    const record = normalized[i];
    if (record.kind === 'usage.tick') {
      continue;
    }
    if (record.kind === 'tool.call') {
      pendingTools += 1;
      pendingRecords.push(record);
      continue;
    }
    if (record.kind === 'agent.think') {
      pendingThinking += 1;
      pendingRecords.push(record);
      continue;
    }
    if (
      record.kind === 'tool.result' &&
      !record.agent_path.length &&
      record.payload.ui_component_delegated !== true
    ) {
      const body = typeof record.payload.body === 'string' ? record.payload.body : '';
      const uiCard = body
        ? parseUiComponentOutput(body, record.payload.ui_component_broken === true)
        : null;
      const imageGrids =
        record.payload.status !== 'error' && body ? parseAllImageGridOutputs(body) : [];
      if (uiCard !== null || imageGrids.length > 0) {
        flushPreResponse(record.group_id);
        out.push({ kind: 'record', record });
        continue;
      }
    }
    if (lensOf(record) !== 'talk') continue;
    flushPreResponse(record.kind === 'agent.say' ? record.group_id : null);
    out.push({ kind: 'record', record });
  }
  flushPreResponse(null);
  return out;
}

/** 提取某段记录切片中挂载了有效决策卡的条目，供 Watcher 在 Talk 折叠时原封不动展示并直接交互。 */
export function extractSliceDecisionCards(
  records: WorkbenchRecord[]
): { recordId: string; block: DecisionBlock }[] {
  const normalized = withTurnDecisionCards(records);
  const cards: { recordId: string; block: DecisionBlock }[] = [];
  for (const r of normalized) {
    if (r.agent_path.length > 0) continue;
    if (r.kind === 'agent.say') {
      const text = typeof r.payload.text === 'string' ? r.payload.text : '';
      const trailing = text ? trailingDecision(text) : null;
      if (trailing && trailing.result.ok) {
        cards.push({ recordId: r.id, block: trailing.result.block });
        continue;
      }
      const delegatedUi =
        typeof r.payload.ui_component === 'string' ? r.payload.ui_component : '';
      const uiCard = parseUiComponentOutput(delegatedUi || text);
      if (uiCard && uiCard.ok) {
        cards.push({ recordId: r.id, block: uiCard.block });
      }
    } else if (
      r.kind === 'tool.result' &&
      r.payload.status !== 'error' &&
      r.payload.ui_component_delegated !== true
    ) {
      const body = typeof r.payload.body === 'string' ? r.payload.body : '';
      const uiCard = body ? parseUiComponentOutput(body) : null;
      if (uiCard && uiCard.ok) {
        cards.push({ recordId: r.id, block: uiCard.block });
      }
    }
  }
  return cards;
}

function isToolRecord(r: WorkbenchRecord): boolean {
  return r.kind === 'tool.call' || r.kind === 'tool.result';
}

/** 跑过但一个字没说的 hook 注入：正文、各段、报错全空。 */
export function isSilentHook(r: WorkbenchRecord): boolean {
  if (r.kind !== 'context.inject' || r.payload.source !== 'hook') return false;
  const p = r.payload;
  const blocks = Array.isArray(p.blocks) ? p.blocks.filter((b) => typeof b === 'string' && b) : [];
  const body = typeof p.body === 'string' ? p.body : '';
  const exit = typeof p.exit_code === 'number' ? p.exit_code : null;
  return (
    !blocks.length &&
    !body &&
    !(typeof p.stderr === 'string' && p.stderr) &&
    p.prevented_continuation !== true &&
    (exit === null || exit === 0)
  );
}

/** 夹在工具调用之间也不算打断的那几种：空 hook、用量刻度、没落盘的空思考。 */
function isTransparent(r: WorkbenchRecord): boolean {
  if (r.kind === 'usage.tick') return true;
  if (r.kind === 'agent.think') {
    const text =
      typeof r.payload.text === 'string'
        ? r.payload.text
        : typeof r.payload.thinking === 'string'
          ? r.payload.thinking
          : '';
    return !text.trim();
  }
  return isSilentHook(r);
}

function isSystemRecord(r: WorkbenchRecord): boolean {
  return r.kind !== 'error' && lensOf(r) === 'system';
}

/**
 * 相邻且同属一类的记录并成一段；三类以外的原样独立成段。只并相邻的，不改顺序。
 *
 * `tools` / `system` 两个开关由镜头决定：「系统」那一档本来就是要逐条看系统记录的，
 * 在那里再压成一行等于什么都不给看。
 */
export function collapseRuns(
  records: WorkbenchRecord[],
  opts: { tools: boolean; system: boolean }
): StreamSegment[] {
  const out: StreamSegment[] = [];
  let i = 0;
  while (i < records.length) {
    const r = records[i];
    if (opts.tools && isToolRecord(r)) {
      const rows: ToolRow[] = [];
      const byCall = new Map<string, ToolRow>();
      const extras: WorkbenchRecord[] = [];
      const members: WorkbenchRecord[] = [];
      let pending: WorkbenchRecord[] = [];
      let j = i;
      while (j < records.length) {
        const x = records[j];
        if (isToolRecord(x)) {
          extras.push(...pending);
          members.push(...pending, x);
          pending = [];
          const cid = typeof x.payload.call_id === 'string' ? x.payload.call_id : '';
          if (x.kind === 'tool.call') {
            const row: ToolRow = { call: x, result: null };
            rows.push(row);
            if (cid) byCall.set(cid, row);
          } else {
            const row = cid ? byCall.get(cid) : undefined;
            if (row && !row.result) row.result = x;
            else rows.push({ call: null, result: x });
          }
          j += 1;
        } else if (isTransparent(x)) {
          pending.push(x);
          j += 1;
        } else {
          break;
        }
      }
      out.push({ kind: 'tools', key: `tools:${r.id}`, rows, extras, records: members });
      // 框尾那几条透明记录没被框收下，退回去照常分段
      i = j - pending.length;
      continue;
    }
    if (opts.system && isSystemRecord(r)) {
      let j = i;
      while (j < records.length && isSystemRecord(records[j])) j += 1;
      out.push({ kind: 'system', key: `system:${r.id}`, records: records.slice(i, j) });
      i = j;
      continue;
    }
    out.push({ kind: 'record', record: r });
    i += 1;
  }
  return out;
}

/** 一段连续的、属于同一次模型回复的分段。 */
export interface SegmentGroup {
  groupId: string | null;
  segments: StreamSegment[];
  /** 这一组底下一共几条原始记录。 */
  size: number;
}

function segmentRecords(seg: StreamSegment): WorkbenchRecord[] {
  return seg.kind === 'record' ? [seg.record] : seg.records;
}

/** 一段属于哪一次回复：组内记录同属一次回复才算，跨了回复的并段不归组。 */
function segmentGroupId(seg: StreamSegment): string | null {
  if (seg.kind === 'talk-agg') return seg.groupId;
  const recs = segmentRecords(seg).filter((r) => r.group_id);
  if (!recs.length) return null;
  const id = recs[0].group_id;
  return recs.every((r) => r.group_id === id) && recs.length === segmentRecords(seg).length
    ? id
    : null;
}

/** 与 `groupRecords` 同一个规矩（只并相邻），单位从记录换成分段。 */
export function groupSegments(segments: StreamSegment[]): SegmentGroup[] {
  const groups: SegmentGroup[] = [];
  for (const seg of segments) {
    const id = segmentGroupId(seg);
    const size = segmentRecords(seg).length;
    const last = groups[groups.length - 1];
    if (id && last && last.groupId === id) {
      last.segments.push(seg);
      last.size += size;
      continue;
    }
    groups.push({ groupId: id, segments: [seg], size });
  }
  return groups;
}

/**
 * 「Agent on it — 在做什么」里的「在做什么」：那句话之后最后一条 agent 动静的短描述。
 * 取记录流本身（确定、即时），不取观察者栏那句意译。
 */
export function describeActivity(
  records: WorkbenchRecord[],
  since: number,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  let last: WorkbenchRecord | null = null;
  for (const r of records) {
    if (r.ts >= since - 1_000 && AGENT_ACTIVITY.has(r.kind)) last = r;
  }
  if (!last) return t('workbench.progress.doingNothingYet');
  const p = last.payload;
  const tool = typeof p.tool_name === 'string' ? p.tool_name : '';
  switch (last.kind) {
    case 'agent.think':
      return t('workbench.progress.doingThinking');
    case 'agent.say':
      return t('workbench.progress.doingReplying');
    case 'tool.call': {
      const title = typeof p.title === 'string' && p.title ? p.title : previewArgs((p.args ?? {}) as Record<string, unknown>);
      return `${tool} ${title}`.trim().slice(0, 120);
    }
    case 'tool.result':
      return t('workbench.progress.doingToolResult', { tool });
    case 'subagent.dispatch':
      return t('workbench.progress.doingSubagent');
    case 'error':
      return p.code === 'informational'
        ? t('workbench.progress.doingNotice')
        : t('workbench.progress.doingError');
    default:
      return t('workbench.progress.doingNothingYet');
  }
}

/** 每秒一跳的钟。只在 `on` 时走，停下不占定时器。 */
function useTicking(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(id);
  }, [on]);
  return now;
}

/** 标注在浏览器里的高亮名字，与 `globals.css` 里 `::highlight()` 同名。 */
const MARK_STACK = 'workbench-mark-stack';
const MARK_BRANCH = 'workbench-mark-branch';
const MARK_QUOTE = 'workbench-mark-quote';
const MARK_FLASH = 'workbench-mark-flash';
/** 跳回原处之后那段文字亮多久。 */
const FLASH_MS = 1_400;

/** 一段标注在记录流里找到的位置。缩略滚动条按它画刻度。 */
export interface MarkTick {
  id: string;
  /**
   * stack＝没用过的暂存（橙）；branch＝没收口的分支（正文色虚线）；quote＝其余的中性底：
   * 引用、用过的暂存、收了口的分支。
   */
  tone: 'stack' | 'branch' | 'quote';
  recordId: string;
  range: Range;
}

/** 这条标注在记录流里画成哪一种。与 `MarkTick.tone` 同一套。 */
export function markTone(mark: WorkbenchMark): MarkTick['tone'] {
  if (mark.kind === 'stack' && !mark.used) return 'stack';
  if (mark.kind === 'branch' && !mark.closed) return 'branch';
  return 'quote';
}

/** 从 `[from, to)` 里挖掉 `cuts` 盖住的部分，剩下的几截。 */
function subtractSpans(span: [number, number], cuts: [number, number][]): [number, number][] {
  let pieces: [number, number][] = [span];
  for (const [c0, c1] of cuts) {
    pieces = pieces.flatMap(([a, b]): [number, number][] => {
      if (c1 <= a || c0 >= b) return [[a, b]];
      const out: [number, number][] = [];
      if (a < c0) out.push([a, c0]);
      if (c1 < b) out.push([c1, b]);
      return out;
    });
  }
  return pieces;
}

/**
 * 在记录流里找出每一条标注，按画法分成三组交给浏览器去涂，顺手交回刻度。
 *
 * 重叠处按「没用过的暂存 > 没收口的分支 > 中性底」取样子：底色是半透明的，只靠上下叠会
 * 混出第三种颜色；虚线下划线与底色又是两种属性，叠在一处两样都会画出来。所以低一档的
 * 那一组先把被高一档盖住的部分挖掉，重叠处只剩优先的那一种。同一组里的范围相接或重叠，
 * 浏览器自然画成一段，不会叠深。找不到的标注跳过，不报错。
 */
export function paintMarks(
  root: ParentNode,
  marks: WorkbenchMark[],
  owner?: object
): MarkTick[] {
  const byRecord = new Map<string, WorkbenchMark[]>();
  for (const mark of marks) {
    const list = byRecord.get(mark.record_id);
    if (list) list.push(mark);
    else byRecord.set(mark.record_id, [mark]);
  }
  const stackRanges: Range[] = [];
  const branchRanges: Range[] = [];
  const quoteRanges: Range[] = [];
  const ticks: MarkTick[] = [];
  for (const [recordId, list] of byRecord) {
    const el = root.querySelector(`[data-record-id="${CSS.escape(recordId)}"][${RECORD_BODY_ATTR}]`);
    if (!el) continue;
    const flat = flatten(el);
    const hot: [number, number][] = [];
    const open: [number, number][] = [];
    const cold: [number, number][] = [];
    for (const mark of list) {
      const span = markSpan(flat, mark.text, mark.occurrence);
      if (!span) continue;
      const tone = markTone(mark);
      (tone === 'stack' ? hot : tone === 'branch' ? open : cold).push(span);
      ticks.push({ id: mark.id, tone, recordId, range: rangeOf(flat, span[0], span[1]) });
    }
    for (const [a, b] of hot) stackRanges.push(rangeOf(flat, a, b));
    for (const span of open) {
      for (const [a, b] of subtractSpans(span, hot)) branchRanges.push(rangeOf(flat, a, b));
    }
    for (const span of cold) {
      for (const [a, b] of subtractSpans(span, [...hot, ...open])) {
        quoteRanges.push(rangeOf(flat, a, b));
      }
    }
  }
  paintHighlight(MARK_STACK, stackRanges, HIGHLIGHT_PRIORITY.stack, owner);
  paintHighlight(MARK_BRANCH, branchRanges, HIGHLIGHT_PRIORITY.branch, owner);
  paintHighlight(MARK_QUOTE, quoteRanges, HIGHLIGHT_PRIORITY.quote, owner);
  return ticks;
}

/** 这一点落没落在这段文字上。量不出位置（老浏览器、测试环境）一律算没落上。 */
function rangeHit(range: Range, x: number, y: number): boolean {
  if (typeof range.getClientRects !== 'function') return false;
  return Array.from(range.getClientRects()).some(
    (r) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom
  );
}

/** 离顶部多近算「在翻更早的」，触发前插。 */
const NEAR_TOP_PX = 240;
/**
 * 判定视口覆盖底部热区的阈值（像素）。
 * 当视口底边距内容底部的剩余距离 <= 此值时，视为覆盖「[底部上方 100px ～ 底部]」区域。
 */
export const SESSION_DETAIL_AUTO_SCROLL_THRESHOLD_PX = 100;

/**
 * 判断滚动容器的可视视口是否覆盖「[底部上方 100px ～ 底部]」区域。
 *
 * 视口覆盖底部上方 threshold 区域的几何条件：
 *   视口底边 (scrollTop + clientHeight) >= 内容底部上方 threshold (scrollHeight - threshold)
 * 即：
 *   scrollHeight - scrollTop - clientHeight <= threshold
 *
 * 当内容总高 scrollHeight <= clientHeight 时，视口容纳了全部内容，天然覆盖底部热区。
 * 为避免高分屏 (DPI) 缩放下浮点舍入误差，加入 0.5px 容差。
 */
export function isViewportCoveringBottom(
  el: { scrollTop: number; scrollHeight: number; clientHeight: number } | null | undefined,
  threshold: number = SESSION_DETAIL_AUTO_SCROLL_THRESHOLD_PX
): boolean {
  if (!el) return false;
  const { scrollTop, scrollHeight, clientHeight } = el;
  if (scrollHeight <= clientHeight) return true;
  const gap = scrollHeight - scrollTop - clientHeight;
  return gap <= threshold + 0.5;
}

/** 离底部超过这个距离，「跳到最新」按钮才冒出来。一屏之内随手一滚就回去，不打扰。 */
const JUMP_SHOW_PX = 240;
/** 手动输入事件后多久之内的滚动算是人滚的。程序滚动不在这个窗口里。 */
const MANUAL_INTENT_MS = 400;
/**
 * 跟到底时，离底部多远之内用动画滑过去。
 *
 * 一条新记录通常只把内容顶高几百像素，那一段用动画滑过去，人眼跟得住"又来了一条"；
 * 而一次前插或整流重取动辄上万像素，那种距离拿动画滑等于让人干等半秒还看不清落点，
 * 直接落位反而清楚。
 */
const SMOOTH_MAX_PX = 1_600;
/** 程序自己滚的时候，多久之内的滚动事件一律不当人滚的看。 */
const PROGRAMMATIC_MS = { auto: 150, smooth: 800 } as const;

/** 会滚动的键。别的键（打字、Tab）不该被当成滚动意图。 */
const SCROLL_KEYS = new Set([
  'PageUp',
  'PageDown',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
  ' ',
]);

export interface RecordStreamProps {
  sessionId: string | null;
  records: WorkbenchRecord[];
  /** 初次装载或整流重取中。 */
  loading: boolean;
  /** 顶部前插旧页中。 */
  loadingOlder: boolean;
  /** 当前窗口之上还有没有更早的记录。 */
  hasOlder: boolean;
  error: string | null;
  onLoadOlder: () => void;
  /** 刚投了一句话进去、还没见 agent 有任何动静。为真时跟到底，让那句话下面的「Agent on it」露出来。 */
  awaitingAgent?: boolean;
  /** 本页本次发出的每一句话的进度。按 `recordId` 挂到对应气泡下面。 */
  trails?: SendTrail[];
  /** 滚到这条记录（输入区「Show」）。`at` 让同一条连点两次也各算一次。 */
  scrollTarget?: { recordId: string; at: number } | null;
  /**
   * 人在流里圈了一段文字、按了「引用」。交出去的是去掉首尾空白的原文，
   * 接住它的是输入区——这一侧不碰输入框的内容。
   */
  onQuote?: (text: string, anchor?: MarkAnchor) => void;
  /** 人圈了一段正文、按了「暂存」并写完想法。不给就不出暂存按钮。 */
  onStack?: (anchor: MarkAnchor, note: string) => void;
  /** 人圈了一段正文、按了「分支」并写好那句话（或挑好 skill / 附件）。不给就不出分支按钮。 */
  onBranch?: (anchor: MarkAnchor, note: string, extras?: BranchExtras) => void;
  /**
   * 圈中的那段恰好是一条真文件的路径时，就地浮开看它（见 {@link SelectionQuote} 第四颗）。
   * 默认开着：这一颗不往外发消息、不改任何东西，只是把那份文件摆出来；某个界面不想要，
   * 传 `preview={false}` 关掉。
   */
  preview?: boolean;
  /** 没收口的分支标注上点出来的小菜单：「打开分支」。不给就不弹菜单。 */
  onOpenBranch?: (childSessionId: string) => void;
  /** 同一个小菜单：「标记已收口」。 */
  onCloseBranch?: (mark: WorkbenchMark) => void;
  /** 这场会话的全部标注。按它给正文着色、给缩略滚动条画刻度。 */
  marks?: WorkbenchMark[];
  /** 暂存列表「点原文」：滚回那段文字并闪一下。`at` 让同一条连点两次也各算一次。 */
  locateTarget?: { mark: WorkbenchMark; at: number } | null;
  /** 跳回原处的下场：找到了、正在往前翻页找、翻到开头也没找到。 */
  onLocateResult?: (id: string, result: LocateState | 'found') => void;
  /**
   * 挂不挂缩略滚动条。会话页挂；Teams 页也用这条记录流，但那一页守着「一屏只有一处实心
   * 绿」，人发言的绿条放过去就破了它，所以默认不挂。
   */
  minimap?: boolean;
  /** 点击异步回传卡「打开来源会话」时触发。 */
  onSelectSession?: (sessionId: string) => void;
  /** 点击交付三要素文件 Diff 胶囊时触发（默认打开 FileViewer 预览）。 */
  onOpenFileDiff?: (filePath: string) => void;
  /**
   * 「文件」那一档：这一场改过哪些文件的那块界面整个交过来。
   *
   * 它**不是镜头**（`StreamLens`）里的一档：镜头筛的是记录，一条记录归哪档是算得出来的；
   * 文件清单不是记录，条数也不是记录条数。所以它是那排里的**兄弟**——按下去记录流原地让位、
   * 清单铺满同一块地方，再按一下回来。不给就不出这一档（Teams 页那份记录流不带它）。
   */
  filesView?: ReactNode;
  /** 文件那一档此刻露着没有。 */
  filesOpen?: boolean;
  /**【Show】、点原文这些要去记录流里找一条的时候，先把文件那一档合上。 */
  onFilesOpenChange?: (open: boolean) => void;
  /**
   * 文件那一档的数字。还没数出来是 `null`。
   *
   * **不摆数字、也不按灰**：按灰的是「一条都没有」，而「还不知道」不是那个意思。数字是切
   * 到这一场就去数的（见页面那一侧），所以这里凡是 `null` 基本都是一眨眼；真取不回来时
   * `filesPending` 为假，这一档就不写个数——那时该说的是故障，不是正在数。
   */
  filesCount?: number | null;
  /** 个数还在路上：那一档后面写个省略号，别让它看着像「没有」。 */
  filesPending?: boolean;
  /**
   * 「终端」那一档：查看这场会话在 tmux 窗格里的实时屏幕或留底终端日志。
   * 与 `filesView` 一样作为 Executor 栏的兄弟档位，点开时覆盖在滚动区上方，不卸载记录流。
   * 支持函数形式按需注入实时的 `counts` 与 `switchToTalk` 回调。
   */
  terminalView?:
    | ReactNode
    | ((ctx: { counts: Record<StreamLens, number>; switchToTalk: () => void }) => ReactNode);
  /** 终端那一档此刻露着没有。 */
  terminalOpen?: boolean;
  /** 切回普通镜头或跳回原文时把终端那一档合上。 */
  onTerminalOpenChange?: (open: boolean) => void;
  /** 这场会话此刻是否活在 tmux 窗格里（为真时在 Terminal 按钮旁点一颗绿点）。 */
  terminalAlive?: boolean;
  /**
   * 档位条右侧常驻的三个数：当前模型、上下文水位、这场累计。
   *
   * 宽屏时与左侧六档同处一行、靠右对齐；窄屏同排装不下时自动折到第二行并左对齐，
   * 极窄时单行尾部省略，悬停保留完整说明。
   */
  usage?: ComposerUsage | null;
  /** 当前会话的文件清单，供对话内点击文件链接打开统一 FileViewer 时共享左栏导航。 */
  sessionFiles?: SessionFileRow[] | null;
  /** 在宿主机器打开文件所在目录的回调。 */
  onRevealFile?: (path: string) => void;
  /** 在 FileViewer 中打包批注填入对话框的回调。 */
  onPackPrompt?: (payload: PackedAnnotationsPayload) => void;
  /** 在 FileViewer 中保存文件修改后直接将修改通知发往对话区的回调。 */
  onSendFileEdit?: (payload: FileEditSendPayload) => void | Promise<void>;
  /** 旁路 AI 定期观察这场的解读结果（供 Watcher 档展示游标增量总结与包裹的 Talk）。 */
  observer?: SessionObserverView | null;
  /** 本会话的上游来历、8 层派生子会话树与 OS 后台进程探测结果。 */
  childrenData?: SessionChildrenResponse | null;
  /** `/children` 接口首取加载中标记。 */
  childrenLoading?: boolean;
}

interface WatcherSlice {
  id: string;
  runId: number;
  taskId: string;
  actor: string;
  at: number | null;
  cursorFrom: number;
  cursorTo: number;
  phaseGoal: string | null;
  doing: string | null;
  findings: string[];
  decision: string | null;
  summary: string;
  records: WorkbenchRecord[];
  decisionCards: { recordId: string; block: DecisionBlock }[];
}

function formatHm(ms: number | null | undefined): string {
  if (!ms) return '—';
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function WatcherInlineText({ text }: { text: string }) {
  if (!text) return null;
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, idx) => {
        if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
          return (
            <code
              key={idx}
              className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
            >
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
          return <strong key={idx}>{part.slice(2, -2)}</strong>;
        }
        return <Fragment key={idx}>{part}</Fragment>;
      })}
    </>
  );
}

function WatcherFindingItem({ text }: { text: string }) {
  const colonIdx = text.indexOf('：');
  if (
    colonIdx > 0 &&
    colonIdx <= 18 &&
    !text.slice(0, colonIdx).includes('`') &&
    !text.slice(0, colonIdx).includes('\n')
  ) {
    const prefix = text.slice(0, colonIdx + 1);
    const rest = text.slice(colonIdx + 1);
    return (
      <li>
        <b>{prefix}</b>
        <WatcherInlineText text={rest} />
      </li>
    );
  }
  return (
    <li>
      <WatcherInlineText text={text} />
    </li>
  );
}

function WatcherBoxBody({
  fullText,
  summaryText,
  expanded,
  onToggle,
  testIdPrefix,
  expandLabel,
  collapseLabel,
  lengthLabel,
}: {
  fullText: string;
  summaryText?: string | null;
  expanded: boolean;
  onToggle: () => void;
  testIdPrefix: string;
  expandLabel: string;
  collapseLabel: string;
  lengthLabel: string;
}) {
  const preview = summaryText && summaryText.trim() ? summaryText.trim() : fullText;
  const hasDiffSummary = preview !== fullText.trim();
  const collapsible = isLongLedgerText(fullText) || hasDiffSummary;
  const displayText = expanded || !collapsible ? fullText : preview;

  if (!collapsible) {
    return (
      <div className="w-box-txt" data-testid={`${testIdPrefix}-text`}>
        <WatcherInlineText text={displayText} />
      </div>
    );
  }

  return (
    <>
      <div className="w-box-txt-wrap">
        <div
          className={`w-box-txt ${expanded ? 'is-expanded' : 'is-clamped'}`}
          data-testid={`${testIdPrefix}-text`}
          data-clamped={expanded ? 'false' : 'true'}
        >
          <WatcherInlineText text={displayText} />
        </div>
        {!expanded ? <div className="w-box-fade" aria-hidden="true" /> : null}
      </div>
      <div className="w-box-foot">
        <span className="w-box-count">{lengthLabel}</span>
        <button
          type="button"
          className="w-box-toggle"
          data-testid={`${testIdPrefix}-toggle`}
          aria-expanded={expanded}
          onClick={onToggle}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          <span>{expanded ? collapseLabel : expandLabel}</span>
        </button>
      </div>
    </>
  );
}

function cleanTailText(raw?: string | null): string {
  if (typeof raw !== 'string') return '';
  return raw
    .replace(/^\[(?:此刻|产出)\]\s*/, '')
    .replace(/。\s*[；;]+/g, '。')
    .replace(/^[；;\s]+|[；;\s]+$/g, '')
    .trim();
}

function joinClauses(items: string[]): string {
  const cleaned = items.map((x) => cleanTailText(x)).filter(Boolean);
  if (cleaned.length === 0) return '';
  if (cleaned.length === 1) return cleaned[0];
  return cleaned.map((x) => x.replace(/[。；;]+$/, '')).join('；');
}

export function normalizeStreamLensParam(
  raw: string | null | undefined
): { lens: StreamLens; progressOpen: boolean } {
  const key = (raw || '').trim().toLowerCase();
  if (key === 'progress' || key === 'watcher') {
    return { lens: 'talk', progressOpen: true };
  }
  if (key === 'all' || key === 'talk' || key === 'hook' || key === 'tool' || key === 'system') {
    return { lens: key, progressOpen: false };
  }
  return { lens: 'talk', progressOpen: false };
}

function readInitialStreamLensFromLocation(): { lens: StreamLens; progressOpen: boolean } {
  if (typeof window === 'undefined') return { lens: 'talk', progressOpen: false };
  try {
    const searchParams = new URLSearchParams(window.location.search);
    const searchLens = searchParams.get('lens');
    if (searchLens) return normalizeStreamLensParam(searchLens);
    const hash = window.location.hash || '';
    const qIdx = hash.indexOf('?');
    if (qIdx >= 0) {
      const hashParams = new URLSearchParams(hash.slice(qIdx + 1));
      const hashLens = hashParams.get('lens');
      if (hashLens) return normalizeStreamLensParam(hashLens);
    }
  } catch {
    // 忽略异常 URL 查询串，退回默认对话视图
  }
  return { lens: 'talk', progressOpen: false };
}

export function splitWatcherLines(input: string | string[] | null | undefined): string[] {
  if (!input) return [];
  const rawItems = Array.isArray(input) ? input : [input];
  const out: string[] = [];
  for (const raw of rawItems) {
    if (typeof raw !== 'string') continue;
    const cleaned = cleanTailText(raw);
    if (!cleaned) continue;
    const pieces = cleaned
      .split(/\r?\n|[；;]+|(?<=[。？！])\s*(?![”’）\]】」』])/g)
      .map((part) => cleanTailText(part))
      .filter(Boolean);
    for (const piece of pieces) {
      if (!out.includes(piece)) {
        out.push(piece);
      }
    }
  }
  return out;
}

function deriveThreeParts(
  tail: ObserverTail | null | undefined,
  happenedList: string[] | undefined,
  decisionRaw: string | null | undefined
): { doing: string | null; findings: string[]; decision: string | null } {
  const tailKind = tail?.kind;
  const tailText = cleanTailText(tail?.text);
  const items: string[] = [];
  for (const raw of happenedList ?? []) {
    const cleaned = cleanTailText(raw);
    if (cleaned && !items.includes(cleaned)) items.push(cleaned);
  }
  const decisionCleaned = cleanTailText(decisionRaw);
  const decision = decisionCleaned || null;

  let doing: string | null = null;
  let findings: string[] = [];
  if (tailKind === 'now' && tailText) {
    doing = tailText;
    findings = items.filter((x) => x !== tailText);
  } else if ((tailKind === 'output' || tailKind === 'error') && tailText) {
    const withoutTail = items.filter((x) => x !== tailText);
    if (withoutTail.length > 0) {
      doing = joinClauses(withoutTail);
    }
    findings = [tailText];
  } else if (items.length > 0) {
    doing = items[0];
    findings = items.slice(1);
  }
  return { doing, findings, decision };
}

const NO_MARKS: WorkbenchMark[] = [];

export default function RecordStream({
  sessionId,
  records,
  loading,
  loadingOlder,
  hasOlder,
  error,
  onLoadOlder,
  awaitingAgent = false,
  trails = [],
  scrollTarget = null,
  onQuote,
  onStack,
  onBranch,
  preview = true,
  onOpenBranch,
  onCloseBranch,
  marks = NO_MARKS,
  locateTarget = null,
  onLocateResult,
  minimap = false,
  onSelectSession,
  onOpenFileDiff,
  filesView,
  filesOpen = false,
  onFilesOpenChange,
  filesCount = null,
  filesPending = false,
  terminalView,
  terminalOpen = false,
  onTerminalOpenChange,
  terminalAlive = false,
  usage = null,
  sessionFiles = null,
  onRevealFile,
  onPackPrompt,
  onSendFileEdit,
  observer = null,
  childrenData = null,
  childrenLoading = false,
}: RecordStreamProps) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');
  const decisionCardHost = useContext(DecisionCardContext);
  // 打开就落在**对话**上。整场记录里对话只占几十分之一，默认铺开全部等于让人自己
  // 在工具与记账里翻对话；要看全部，顶上那排镜头点一下就是。
  const initialLensState = useMemo(() => readInitialStreamLensFromLocation(), []);
  const [lens, setLens] = useState<StreamLens>(initialLensState.lens);
  const [watcherOpen, setWatcherOpen] = useState(initialLensState.progressOpen);
  const [inspectOpen, setInspectOpen] = useState(false);
  const [expandedWatcherIds, setExpandedWatcherIds] = useState<Record<string, boolean>>({});
  const [anchorExpanded, setAnchorExpanded] = useState(false);
  const [stateExpanded, setStateExpanded] = useState(false);
  // 按会话维度记忆用户是否手动展开过「已完结 Tx」行，避免后台轮询或流式更新强行重置。
  const [completedTasksExpandedBySession, setCompletedTasksExpandedBySession] = useState<
    Record<string, boolean>
  >({});
  const taskFoldKey = sessionId || '__default__';
  const isCompletedTasksExpanded = Boolean(completedTasksExpandedBySession[taskFoldKey]);
  const toggleCompletedTasksExpanded = useCallback(() => {
    setCompletedTasksExpandedBySession((prev) => ({
      ...prev,
      [taskFoldKey]: !prev[taskFoldKey],
    }));
  }, [taskFoldKey]);
  useEffect(() => {
    setExpandedWatcherIds({});
    setInspectOpen(false);
    setAnchorExpanded(false);
    setStateExpanded(false);
  }, [sessionId]);
  /** 圈中的那段是一条真文件、或点中回复里的本地文件链接时，就地浮开的那一份。 */
  const [peek, setPeek] = useState<{
    path: string;
    size: number | null;
    line?: string;
    mode?: 'preview' | 'file' | 'changes' | 'edit';
  } | null>(null);
  const handleFileLink = useCallback(
    (target: FileLinkTarget) => {
      if (preview) setPeek({ path: target.path, size: null, line: target.line });
    },
    [preview]
  );

  const streamActions = useMemo<RecordStreamActions>(
    () => ({
      onOpenFileDiff:
        onOpenFileDiff ??
        ((filePath: string) => {
          setPeek({ path: filePath, size: null, mode: 'changes' });
        }),
      onSelectSession,
    }),
    [onOpenFileDiff, onSelectSession]
  );

  /** 每一档各有几条。筛掉的也要报出真实条数，否则筛完像是那些事没发生过。 */
  const resolved = useMemo(() => withQueueOutcomes(records), [records]);

  const counts = useMemo(() => {
    const tally: Record<StreamLens, number> = {
      all: resolved.length,
      talk: 0,
      hook: 0,
      tool: 0,
      system: 0,
    };
    for (const record of resolved) {
      const bucket = lensOf(record);
      if (bucket !== 'talk') {
        tally[bucket] += 1;
      }
      if (isTalkBubbleRecord(record)) {
        tally.talk += 1;
      }
    }
    return tally;
  }, [resolved]);

  const visible = useMemo(
    () =>
      lens === 'all'
        ? resolved
        : lens === 'talk'
          ? talkView(resolved)
          : resolved.filter((r) => lensOf(r) === lens),
    [resolved, lens]
  );

  // 连续同类合并：「对话」档把响应前的工具调用与思考压成单行计数自增，其余对话原样摆；「系统」档不压系统记录。
  const segments = useMemo(
    () =>
      lens === 'talk'
        ? buildTalkSegments(resolved)
        : collapseRuns(visible, { tools: lens === 'all' || lens === 'tool', system: lens === 'all' }),
    [resolved, visible, lens]
  );
  const groups = useMemo(() => groupSegments(segments), [segments]);
  const lastSegment = segments[segments.length - 1];

  const scopedChildrenData = useMemo(
    () =>
      childrenData && (!sessionId || childrenData.session_id === sessionId)
        ? childrenData
        : null,
    [childrenData, sessionId]
  );

  const progressBadge = useMemo(
    () => computeProgressBadge(scopedChildrenData),
    [scopedChildrenData]
  );

  const hasAnyChildrenContext = Boolean(
    scopedChildrenData &&
      (scopedChildrenData.launched_by ||
        scopedChildrenData.child_sessions.length > 0 ||
        scopedChildrenData.child_processes.length > 0 ||
        scopedChildrenData.summary?.external_host_alive)
  );

  const { watcherSlices, unsummarizedTailRecords, firstHumanGoal } = useMemo<{
    watcherSlices: WatcherSlice[];
    unsummarizedTailRecords: WorkbenchRecord[];
    firstHumanGoal: string | null;
  }>(() => {
    if (!watcherOpen || !resolved.length) {
      return { watcherSlices: [], unsummarizedTailRecords: [], firstHumanGoal: null };
    }
    const state = observer?.state ?? null;
    const runs = state?.runs ?? [];
    let humanGoal: string | null = null;
    for (const r of resolved) {
      if (r.kind === 'user.say' && !r.payload.is_tool_result) {
        const g = cleanGoalText(typeof r.payload.text === 'string' ? r.payload.text : null);
        if (g) {
          humanGoal = g;
          break;
        }
      }
    }
    if (runs.length > 0) {
      let maxCursorTo = 0;
      const slices = runs.map((run, idx) => {
        const fromSeq = typeof run.cursor_from === 'number' ? run.cursor_from : 0;
        const toSeq =
          typeof run.cursor_to === 'number'
            ? run.cursor_to
            : resolved[resolved.length - 1].seq + 1;
        if (toSeq > maxCursorTo) maxCursorTo = toSeq;
        // 严格只包裹本次总结真实读过的已发生闭区间 [cursor_from, cursor_to)，
        // 绝不把 cursor_to 之后才发生的记录塞进旧总结槽位里。
        const sliceRecords = resolved.filter((r) => r.seq >= fromSeq && r.seq < toSeq);
        const sliceCards = extractSliceDecisionCards(sliceRecords);
        const lastSliceCard = sliceCards.length > 0 ? sliceCards[sliceCards.length - 1].block : null;
        const cardFallbackDecision = lastSliceCard
          ? lastSliceCard.why
            ? `${lastSliceCard.question}（${lastSliceCard.why}）`
            : lastSliceCard.question
          : null;
        const parts = deriveThreeParts(
          run.tail,
          run.happened_add,
          (run.decision && run.decision.trim()) || cardFallbackDecision
        );
        const summaryParts: string[] = [];
        if (run.summary && run.summary.trim()) {
          summaryParts.push(run.summary.trim());
        } else {
          if (run.happened_add?.length) summaryParts.push(...run.happened_add);
          if (run.tail?.text) summaryParts.push(run.tail.text);
          if (parts.decision) summaryParts.push(parts.decision);
        }
        const phaseGoal =
          cleanGoalText(run.phase_goal) ||
          cleanGoalText(state?.phase_goal) ||
          cleanGoalText(state?.anchor) ||
          humanGoal;
        const runId = typeof run.run_id === 'number' && run.run_id > 0 ? run.run_id : idx + 1;
        const taskId =
          typeof run.task_id === 'string' && run.task_id.trim()
            ? run.task_id.trim()
            : `T${idx + 1}`;
        const actor =
          typeof run.actor === 'string' && run.actor.trim()
            ? run.actor.trim()
            : '主会话';
        const doing =
          typeof run.doing === 'string' && run.doing.trim()
            ? cleanTailText(run.doing)
            : parts.doing;
        const findings =
          Array.isArray(run.findings) && run.findings.length > 0
            ? run.findings.map((f) => cleanTailText(f)).filter(Boolean)
            : parts.findings;
        return {
          id: run.id || `run-${idx + 1}`,
          runId,
          taskId,
          actor,
          at: run.at ?? state?.updated_at ?? sliceRecords[sliceRecords.length - 1]?.ts ?? null,
          cursorFrom: fromSeq,
          cursorTo: toSeq,
          phaseGoal,
          doing,
          findings,
          decision: parts.decision,
          summary: summaryParts.join('\n') || t('workbench.stream.watcherEmptySummary'),
          records: sliceRecords,
          decisionCards: sliceCards,
        };
      });
      const tailRecords = resolved.filter((r) => r.seq >= maxCursorTo);
      return { watcherSlices: slices, unsummarizedTailRecords: tailRecords, firstHumanGoal: humanGoal };
    }
    const fallbackChronological = state?.happened?.length ? [...state.happened].reverse() : [];
    const fallbackThree = deriveThreeParts(state?.tail, fallbackChronological, state?.decision);
    const fallbackParts: string[] = [];
    const safeAnchor = cleanGoalText(state?.anchor);
    if (safeAnchor) fallbackParts.push(safeAnchor);
    if (fallbackChronological.length) fallbackParts.push(...fallbackChronological);
    if (state?.tail?.text) fallbackParts.push(state.tail.text);
    if (state?.decision) fallbackParts.push(state.decision);
    if (fallbackParts.length > 0) {
      return {
        watcherSlices: [
          {
            id: 'run-1',
            runId: 1,
            taskId: 'T1',
            actor: '主会话',
            at: state?.updated_at ?? resolved[resolved.length - 1]?.ts ?? null,
            cursorFrom: 0,
            cursorTo: (resolved[resolved.length - 1]?.seq ?? 0) + 1,
            phaseGoal:
              cleanGoalText(state?.phase_goal) ||
              safeAnchor ||
              humanGoal,
            doing: fallbackThree.doing,
            findings: fallbackThree.findings,
            decision: fallbackThree.decision,
            summary: fallbackParts.join('\n'),
            records: resolved,
            decisionCards: extractSliceDecisionCards(resolved),
          },
        ],
        unsummarizedTailRecords: [],
        firstHumanGoal: humanGoal,
      };
    }
    return {
      watcherSlices: [],
      unsummarizedTailRecords: resolved,
      firstHumanGoal: humanGoal,
    };
  }, [watcherOpen, resolved, observer?.state, t]);

  /**
   * Progress 视图下自动向前补齐覆盖全部里程碑（`runs`）所需的早期历史记录。
   *
   * 长会话首屏默认只拉取尾部 200 条记录（及最多补足 40 条可见对话），导致早期里程碑
   * （`cursor_from < records[0].seq`）在前端内存里找不到对应的 `records`，按钮误显
   * `No conversation` 且点开后为空框。当打开 Progress 视图时，只要窗口首条 `seq` 仍大于
   * 最早里程碑的 `cursor_from` 且 `hasOlder` 为真，就按页向前加载，直至覆盖全部里程碑。
   */
  const earliestWatcherSeq = useMemo(() => {
    if (!watcherOpen) return null;
    const runs = observer?.state?.runs ?? [];
    if (!runs.length) return null;
    let minSeq = Number.POSITIVE_INFINITY;
    for (const run of runs) {
      const fromSeq = typeof run.cursor_from === 'number' ? run.cursor_from : 0;
      if (fromSeq < minSeq) minSeq = fromSeq;
    }
    return Number.isFinite(minSeq) ? minSeq : null;
  }, [watcherOpen, observer?.state?.runs]);

  const watcherBackfillPaged = useRef<{
    sessionId: string | null | undefined;
    firstId: string | undefined;
    firstSeq: number;
  } | null>(null);

  useEffect(() => {
    if (!watcherOpen) {
      watcherBackfillPaged.current = null;
      return;
    }
    if (
      earliestWatcherSeq === null ||
      !records.length ||
      records[0].seq <= earliestWatcherSeq ||
      !hasOlder ||
      loadingOlder
    ) {
      return;
    }
    const first = records[0];
    const paged = watcherBackfillPaged.current;
    if (
      paged &&
      paged.sessionId === sessionId &&
      paged.firstId === first.id &&
      paged.firstSeq === first.seq
    ) {
      return;
    }
    watcherBackfillPaged.current = {
      sessionId,
      firstId: first.id,
      firstSeq: first.seq,
    };
    onLoadOlder();
  }, [watcherOpen, earliestWatcherSeq, records, hasOlder, loadingOlder, sessionId, onLoadOlder]);

  const watcherTasks = useMemo<ObserverTaskItem[]>(() => {
    if (!watcherOpen) return [];
    const rawTasks = observer?.state?.tasks;
    if (Array.isArray(rawTasks) && rawTasks.length > 0) {
      return rawTasks;
    }
    if (!watcherSlices.length) return [];
    const byId = new Map<string, ObserverTaskItem>();
    for (let idx = 0; idx < watcherSlices.length; idx += 1) {
      const slice = watcherSlices[idx];
      const isLast = idx === watcherSlices.length - 1;
      const hasUnansweredCard = slice.decisionCards.some(
        (dc) => !decisionCardHost?.answerOf(dc.recordId)
      );
      const hasDecision = Boolean(
        hasUnansweredCard || (slice.decision && slice.decisionCards.length === 0)
      );
      const hasTailError =
        isLast &&
        (observer?.state?.tail?.kind === 'error' ||
          resolved.some(
            (r, rIdx) =>
              rIdx >= resolved.length - 3 &&
              r.kind === 'error'
          ));
      const status: ObserverTaskItem['status'] = isLast
        ? hasDecision
          ? 'waiting'
          : observer?.state?.tail?.kind === 'now'
            ? 'doing'
            : hasTailError
              ? 'error'
              : 'done'
        : 'done';
      const conclusion =
        slice.findings[0] ||
        slice.doing ||
        slice.summary.split('\n')[0] ||
        t('workbench.stream.watcherEmptySummary');
      const id = slice.taskId || `T${idx + 1}`;
      const existing = byId.get(id);
      if (!existing) {
        byId.set(id, {
          id,
          proposed_at: slice.at ?? resolved[resolved.length - 1]?.ts ?? Date.now(),
          title: slice.phaseGoal || slice.summary.split('\n')[0] || `阶段 #${idx + 1}`,
          status,
          actor: slice.actor || '主会话',
          conclusion,
        });
      } else {
        byId.set(id, {
          ...existing,
          status,
          actor: slice.actor || existing.actor,
          conclusion: conclusion || existing.conclusion,
        });
      }
    }
    return Array.from(byId.values());
  }, [watcherOpen, observer?.state?.tasks, observer?.state?.tail?.kind, watcherSlices, decisionCardHost, resolved, t]);

  /** 记录编号 → 挂在它下面的那份进度。 */
  const trailOf = useMemo(() => {
    const map = new Map<string, SendTrail>();
    for (const tr of trails) if (tr.recordId && !tr.expired) map.set(tr.recordId, tr);
    return map;
  }, [trails]);
  /** 眼下这一轮在跑的那一句：最后一份已落地、还没答完的进度。「Agent on it」只挂它下面。 */
  const activeTrail = useMemo(() => {
    for (let i = trails.length - 1; i >= 0; i -= 1) {
      const tr = trails[i];
      if (tr.expired || trailSettled(tr)) continue;
      if (!tr.recordId) continue;
      const since = (tr.steps.in_the_session ?? tr.steps.queued ?? tr.steps.on_its_way ?? 0) - 1_000;
      const stoppedAfter = records.some(
        (r) => r.ts >= since && (isLifecycleStopRecord(r) || r.kind === 'interrupt')
      );
      if (stoppedAfter) continue;
      return tr;
    }
    return null;
  }, [trails, records]);
  const now = useTicking(activeTrail !== null);
  const activeShown = activeTrail?.recordId
    ? visible.some((r) => r.id === activeTrail.recordId)
    : false;

  const agentOnIt = activeTrail ? (
    <p
      data-testid="agent-on-it"
      className="flex min-w-0 items-center gap-1.5 px-3 text-[11px] text-text-muted"
    >
      <span aria-hidden className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent-primary" />
      <span className="shrink-0 text-accent-primary">{t('workbench.progress.agentOnIt')}</span>
      <span className="min-w-0 truncate">
        — {describeActivity(records, activeTrail.steps.in_the_session ?? activeTrail.steps.queued ?? 0, t)}
      </span>
      <span className="shrink-0 font-mono tabular-nums text-text-dim">
        · {formatDuration(Math.max(0, now - (activeTrail.steps.on_its_way ?? now)))}
      </span>
    </p>
  ) : null;

  /** 一条记录连同挂在它下面的进度。只有对得上某份进度的记录才多包一层。 */
  const renderRecord = (record: WorkbenchRecord) => {
    const trail = trailOf.get(record.id);
    const bare = <RecordCard key={record.id} record={record} sessionId={sessionId ?? ''} />;
    // 正文类记录外面多一层只装这张卡的壳：标注的锚点、着色、跳回原处都认这一层，
    // 缩略滚动条也按它量高度、分颜色。挂着进度的那几条外层另有一个 data-record-id
    // （输入区「Show」认它），这一层套在里面，只包卡、不包进度。
    const card = isBodyRecord(record) ? (
      <div
        key={record.id}
        data-record-id={record.id}
        data-record-kind={isPureAsyncCallbackRecord(record) ? 'async.callback' : record.kind}
        {...{ [RECORD_BODY_ATTR]: '' }}
        className="wb-record"
      >
        {bare}
      </div>
    ) : (
      bare
    );
    if (!trail) return card;
    // 刚落地、agent 还没接手：气泡外多一圈淡描边，说「这是你刚发的那句」
    const fresh =
      !trail.midTurn && trail.steps.picked_up === undefined && !trailSettled(trail);
    return (
      <div key={record.id} data-record-id={record.id} className="flex min-w-0 flex-col gap-1">
        <div
          data-testid="trail-bubble"
          data-fresh={fresh ? 'true' : undefined}
          className={fresh ? 'rounded-[9px] outline outline-1 outline-offset-2 outline-[var(--sel-border)]' : ''}
        >
          {card}
        </div>
        <SendProgress trail={trail} className="px-3" />
        {activeTrail?.id === trail.id ? agentOnIt : null}
      </div>
    );
  };

  const renderSegment = (seg: StreamSegment) => {
    if (seg.kind === 'record') return renderRecord(seg.record);
    if (seg.kind === 'talk-agg') {
      const parts: ReactNode[] = [];
      if (seg.toolCalls > 0) {
        parts.push(
          <span key="tools" data-testid="talk-agg-tools">
            {t('workbench.stream.preResponseToolCalls', { count: seg.toolCalls })}
          </span>
        );
      }
      if (seg.thinkingSteps > 0) {
        parts.push(
          <span key="thinking" data-testid="talk-agg-thinking">
            {t('workbench.stream.preResponseThinking', { count: seg.thinkingSteps })}
          </span>
        );
      }
      return (
        <div
          key={seg.key}
          data-testid="talk-pre-response-agg"
          className="talk-agg"
        >
          <span className="tagg-ic" aria-hidden="true">
            ⚡
          </span>
          {parts.map((part, idx) => (
            <Fragment key={idx}>
              {idx > 0 ? <span aria-hidden="true">·</span> : null}
              {part}
            </Fragment>
          ))}
        </div>
      );
    }
    if (seg.kind === 'tools') {
      return (
        <ToolRun
          key={seg.key}
          rows={seg.rows}
          extras={seg.extras}
          sessionId={sessionId ?? ''}
          live={seg === lastSegment}
        />
      );
    }
    return <SystemRun key={seg.key} records={seg.records} sessionId={sessionId ?? ''} />;
  };

  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  /** 是否正在用鼠标按住原生滚动条滑块拖拽。 */
  const isDraggingScrollbar = useRef(false);
  /**
   * 自动滚动是否武装。
   * 仅当视口覆盖「[底部上方 100px ～ 底部]」热区时武装；离开该热区（距底 > 100px）时立即解除。
   * 初始默认武装（开一场新会话装载最新页时落在底部），用户上翻离开底部 100px 即刻解除。
   */
  const followArmed = useRef(true);
  /** 手动输入事件的有效期。窗口内的 onScroll 才算人滚的。 */
  const manualIntentUntil = useRef(0);
  /** 前插触发那一刻的滚动几何，插完用来把视口钉回原处。 */
  const anchor = useRef<{ height: number; top: number } | null>(null);
  /** 上一帧记录流的首尾编号，用来分辨追加、前插与整流替换。 */
  const prevEnds = useRef<{ first: string | null; last: string | null }>({
    first: null,
    last: null,
  });
  // 滚动事件触发得很密，到顶一次就够了；再触发由 hook 那一侧的闸挡住。
  const olderArmed = useRef(true);
  // Talk / Watcher 视图在可见对话不足或视口未填满时自动向前补取旧页的本轮计数，防极端空会话死循环。
  const autoBackfillCount = useRef(0);
  /**
   * 程序自己滚的有效期。
   *
   * 平滑滚动一次会连着吐几十个滚动事件，一路持续几百毫秒。不把这段时间标出来，那些
   * 事件会落进"人手滚动"的判定窗口里，人明明没碰过，自动跟随却自己解除了——症状是
   * 「滚着滚着就不跟了」，而且极难复现。
   */
  const programmaticUntil = useRef(0);

  const scrollToBottom = useCallback((behavior: 'auto' | 'smooth' = 'auto') => {
    const el = scrollRef.current;
    if (!el) return;
    // **页面被藏起来时一律直接落位。** 平滑滚动是逐帧动画，而浏览器在后台标签里根本
    // 不发帧——动画一步都不会走，视口就此被晾在半路。记录还在经 WebSocket 往里进
    // （那条路不看可见性），人切回来时看到的是停在中间的一屏，而且再也不会自己走完。
    // 实测：后台标签里 scrollTo({behavior:'smooth'}) 调用成功、scrollTop 一动不动。
    const effective = behavior === 'smooth' && document.hidden ? 'auto' : behavior;
    programmaticUntil.current = Date.now() + PROGRAMMATIC_MS[effective];
    // 没有 scrollTo 就直接落位。测试环境（jsdom）与老浏览器都属于这一档——沉底这件事
    // 一次都不能因为"滑不动"而不发生，那会让打开会话时停在整场的开头。
    if (typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight, behavior: effective });
    } else {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  /** 「跳到最新」按钮亮着吗。距底超过 {@link JUMP_SHOW_PX} 才亮——人翻上去看历史了，
   * 一键回去；就在底部附近时它没有可干的事，不占地方。 */
  const [showJump, setShowJump] = useState(false);
  const overlayViewOpenRef = useRef(false);
  overlayViewOpenRef.current = watcherOpen || filesOpen || terminalOpen;

  // 人点了「跳到最新」：这算程序滚动（scrollToBottom 自己会留 programmaticUntil，余波
  // 不会误伤跟随状态机），同时把手动滚动的痕迹清干净——上一秒人还在翻历史，这一秒起
  // 视图重新交还给自动跟随，下一条新记录照常跟到底。
  const jumpToLatest = useCallback(() => {
    followArmed.current = true;
    manualIntentUntil.current = 0;
    scrollToBottom('smooth');
    setShowJump(false);
  }, [scrollToBottom]);

  // 换会话：一切归零，默认重新武装——新打开的会话加载最新尾部一页就该落在最新内容上；
  // 若当前正处于 Progress / Files 等顶部定位视图，同步将滚动条重置回 0。
  useLayoutEffect(() => {
    followArmed.current = true;
    manualIntentUntil.current = 0;
    programmaticUntil.current = 0;
    anchor.current = null;
    prevEnds.current = { first: null, last: null };
    olderArmed.current = true;
    autoBackfillCount.current = 0;
    setShowJump(false);
    if (overlayViewOpenRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [sessionId]);

  // 记录流变化：前插钉住视口，初装沉底武装，尾部追加与流式单条变长跟底，整流替换按武装状态走。
  useLayoutEffect(() => {
    if (!records.length) {
      prevEnds.current = { first: null, last: null };
      return;
    }
    const first = records[0].id;
    const last = records[records.length - 1].id;
    const prev = prevEnds.current;
    const el = scrollRef.current;

    if (overlayViewOpenRef.current) {
      prevEnds.current = { first, last };
      anchor.current = null;
      return;
    }

    if (prev.first !== null && first !== prev.first && last === prev.last) {
      // 1. 前插旧页：把视口钉回原来那张卡，NEVER 让人觉得页面自己跳了。
      if (el && anchor.current) {
        el.scrollTop = el.scrollHeight - anchor.current.height + anchor.current.top;
      }
    } else if (prev.first === null) {
      // 2. 初次装载会话最新页（Tail Window 分页）：落位在最新内容底部并武装自动贴底
      scrollToBottom();
      followArmed.current = true;
    } else if (first === prev.first && last !== prev.last) {
      // 3. 尾部追加不同记录：依据内容增长前的武装状态决定是否自动滚底。
      //    若内容增长前视口正覆盖底部 100px 热区（followArmed 为真），则自动跟到底；
      //    若用户已手动上翻离开热区（距底 > 100px），绝对不滚，严禁打扰用户阅读历史！
      if (followArmed.current) {
        // 近处滑过去，远处直接落位——见 SMOOTH_MAX_PX。
        const gap = el ? el.scrollHeight - el.scrollTop - el.clientHeight : 0;
        scrollToBottom(gap <= SMOOTH_MAX_PX ? 'smooth' : 'auto');
        followArmed.current = true;
      }
    } else if (first === prev.first && last === prev.last) {
      // 4. 单条流式增量更新（最后一条内容变长）：
      //    只要内容变长前视口正处于底部 100px 热区（followArmed 为真），持续平滑跟到底；
      //    若用户正在上方看历史，视口纹丝不动，严禁抢滚！
      if (followArmed.current) {
        const gap = el ? el.scrollHeight - el.scrollTop - el.clientHeight : 0;
        scrollToBottom(gap <= SMOOTH_MAX_PX ? 'smooth' : 'auto');
        followArmed.current = true;
      }
    } else if (first !== prev.first && last !== prev.last) {
      // 5. 整流替换（重拉）：仅当替换前视口处于底部 100px 热区（或武装着）时才沉底并武装；
      //    若用户正在上方看历史，保持视口位置，绝不强行拉到底部。
      if (followArmed.current || isViewportCoveringBottom(el)) {
        scrollToBottom();
        followArmed.current = true;
      } else {
        followArmed.current = false;
      }
    }

    prevEnds.current = { first, last };
    anchor.current = null;
  }, [records, scrollToBottom]);

  // 换镜头后：
  // - 切进 Watcher（或 Files）时按原型契约停在顶部（scrollTop = 0）；
  // - 从 Watcher 切回对话 / 全部等流视图、或在不同流镜头间切换时立即沉底并武装跟随。
  const prevLensRef = useRef({ lens, watcherOpen, filesOpen });
  useLayoutEffect(() => {
    const prev = prevLensRef.current;
    const isFirstRun =
      prev.lens === lens &&
      prev.watcherOpen === watcherOpen &&
      prev.filesOpen === filesOpen;
    prevLensRef.current = { lens, watcherOpen, filesOpen };
    autoBackfillCount.current = 0;
    if (!isFirstRun) {
      const el = scrollRef.current;
      if (watcherOpen) {
        if (el) el.scrollTop = 0;
      } else if (prev.watcherOpen || prev.lens !== lens) {
        scrollToBottom();
        followArmed.current = true;
      } else if (!filesOpen && (followArmed.current || isViewportCoveringBottom(el))) {
        scrollToBottom();
        followArmed.current = true;
      }
      setShowJump(false);
    }
  }, [lens, watcherOpen, filesOpen, scrollToBottom]);

  // 全局鼠标/指针抬起与移动监听：维护拖拽原生滚动条滑块的意图状态
  useEffect(() => {
    const handleGlobalPointerUp = () => {
      if (isDraggingScrollbar.current) {
        isDraggingScrollbar.current = false;
        manualIntentUntil.current = Date.now() + MANUAL_INTENT_MS;
      }
    };
    const handleGlobalPointerMove = (e: MouseEvent) => {
      if (isDraggingScrollbar.current) {
        if (e.buttons === 0) {
          isDraggingScrollbar.current = false;
        } else {
          manualIntentUntil.current = Date.now() + MANUAL_INTENT_MS;
        }
      }
    };

    window.addEventListener('mouseup', handleGlobalPointerUp);
    window.addEventListener('pointerup', handleGlobalPointerUp);
    window.addEventListener('pointercancel', handleGlobalPointerUp);
    window.addEventListener('mousemove', handleGlobalPointerMove);
    window.addEventListener('pointermove', handleGlobalPointerMove);
    return () => {
      window.removeEventListener('mouseup', handleGlobalPointerUp);
      window.removeEventListener('pointerup', handleGlobalPointerUp);
      window.removeEventListener('pointercancel', handleGlobalPointerUp);
      window.removeEventListener('mousemove', handleGlobalPointerMove);
      window.removeEventListener('pointermove', handleGlobalPointerMove);
    };
  }, []);

  // 容器视口与内部内容尺寸变化时，实时驱动贴底跟随并维护武装状态。
  useEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el || !content || typeof ResizeObserver === 'undefined') return;

    const observer = new ResizeObserver(() => {
      if (overlayViewOpenRef.current) return;
      // 内部内容撑高时：若增长前处于贴底武装状态，持续自动向下滚动
      if (followArmed.current) {
        const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
        if (gap > 0) {
          scrollToBottom(gap <= SMOOTH_MAX_PX ? 'smooth' : 'auto');
        }
      } else if (Date.now() > programmaticUntil.current) {
        // 未武装状态下视口尺寸变大（如拉高浏览器窗体）使视口覆盖了底部 100px 热区，重新同步
        followArmed.current = isViewportCoveringBottom(el);
      }
    });

    observer.observe(content);
    observer.observe(el);
    return () => {
      observer.disconnect();
    };
  }, [scrollToBottom]);

  // Talk / Watcher 视图下，若当前已取窗口筛完后可见对话不足最小条数（满页却不足 MIN_TALK_RECORDS）
  // 或内容高度不足以撑出滚动条（导致无法通过上滚触发 NEAR_TOP_PX），且服务端还有更早记录，
  // 自动向前补取旧页，保证最新一页始终饱满可滚。
  useEffect(() => {
    if (!hasOlder || loading || loadingOlder) return;
    if (filesOpen || terminalOpen) return;
    if (lens !== 'talk' && !watcherOpen) return;
    if (autoBackfillCount.current >= MAX_BACKFILL_PAGES) return;

    const el = scrollRef.current;
    const underMinBubbles = counts.talk < MIN_TALK_RECORDS && records.length >= PAGE_SIZE;
    const underViewport =
      el !== null && el.clientHeight > 0 && el.scrollHeight <= el.clientHeight + NEAR_TOP_PX;

    if (!underMinBubbles && !underViewport) return;

    autoBackfillCount.current += 1;
    if (!watcherOpen && el && el.scrollHeight > 0) {
      anchor.current = { height: el.scrollHeight, top: el.scrollTop };
    }
    onLoadOlder();
  }, [
    hasOlder,
    loading,
    loadingOlder,
    filesOpen,
    terminalOpen,
    lens,
    watcherOpen,
    counts.talk,
    records.length,
    onLoadOlder,
  ]);

  // "在等 agent 开口"那一条也是内容，它一冒出来就要看得见——跟着的人正是为了看它。
  // 人自己滚上去看别的时不打扰。
  useLayoutEffect(() => {
    if (awaitingAgent && followArmed.current && !overlayViewOpenRef.current) scrollToBottom('smooth');
  }, [awaitingAgent, scrollToBottom]);

  // 输入区「Show」：滚到那句话。它可能在当前镜头里看不见，那就先回到「对话」档。
  const scrollAt = scrollTarget?.at ?? 0;
  const scrollId = scrollTarget?.recordId ?? '';
  useEffect(() => {
    if (!scrollAt || !scrollId) return;
    // 人正开着文件那一档：先把记录流露出来，下一拍再滚（这条效应盯着 filesOpen）。
    if (filesOpen) {
      onFilesOpenChange?.(false);
      return;
    }
    if (terminalOpen) {
      onTerminalOpenChange?.(false);
      return;
    }
    if (watcherOpen) {
      setWatcherOpen(false);
      return;
    }
    if (!visible.some((r) => r.id === scrollId) && lens !== 'talk') {
      setLens('talk');
      return;
    }
    const el = scrollRef.current?.querySelector<HTMLElement>(
      `[data-record-id="${CSS.escape(scrollId)}"]`
    );
    if (!el) return;
    programmaticUntil.current = Date.now() + PROGRAMMATIC_MS.smooth;
    followArmed.current = false;
    el.scrollIntoView?.({ block: 'center', behavior: scrollBehavior() });
    // 只在点下去那一刻滚一次；镜头换完再来一趟由 lens 变化带起
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollAt, scrollId, lens, filesOpen, terminalOpen, watcherOpen]);

  /**
   * 标注着色。记录、镜头、标注任何一样变了都重涂一遍：记录流是 React 画的，一换镜头
   * 那些文本节点就换了一批，上一轮交给浏览器的范围全都指着已经不在的节点。
   */
  const [ticks, setTicks] = useState<MarkTick[]>([]);
  // 这一块记录流在高亮登记里的身份。会话页、Teams 页各挂着记录流，高亮名字却是全网页
  // 共用的；每块只交、只撤自己那一份，藏着的那块重涂时不会把别处的底色撤掉。
  const painter = useRef({}).current;
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !marks.length) {
      paintHighlight(MARK_STACK, [], HIGHLIGHT_PRIORITY.stack, painter);
      paintHighlight(MARK_BRANCH, [], HIGHLIGHT_PRIORITY.branch, painter);
      paintHighlight(MARK_QUOTE, [], HIGHLIGHT_PRIORITY.quote, painter);
      setTicks([]);
      return;
    }
    setTicks(paintMarks(root, marks, painter));
  }, [marks, groups, sessionId, painter]);
  // 这块走了，底色一起走：高亮挂在浏览器上，不随 React 的树消失。
  useEffect(
    () => () => {
      paintHighlight(MARK_STACK, [], HIGHLIGHT_PRIORITY.stack, painter);
      paintHighlight(MARK_BRANCH, [], HIGHLIGHT_PRIORITY.branch, painter);
      paintHighlight(MARK_QUOTE, [], HIGHLIGHT_PRIORITY.quote, painter);
      paintHighlight(MARK_FLASH, [], HIGHLIGHT_PRIORITY.flash, painter);
    },
    [painter]
  );

  /**
   * 点在没收口的分支那道虚线上，就地弹一个小菜单：「打开分支」「标记已收口」。
   *
   * 虚线是浏览器按文本范围画的，DOM 里没有一个元素可挂点击，所以这里拿点下去的那一点
   * 去比每一道虚线的屏幕矩形。人正在圈字（选区不空）时不弹：那一下是在选，不是在点。
   */
  const [branchMenu, setBranchMenu] = useState<{ mark: WorkbenchMark; x: number; y: number } | null>(
    null
  );
  useEffect(() => setBranchMenu(null), [sessionId]);
  const handleStreamClick = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>) => {
      if (!onOpenBranch && !onCloseBranch) return;
      const picked = document.getSelection();
      if (picked && !picked.isCollapsed) return;
      const hit = ticks.find(
        (tick) => tick.tone === 'branch' && rangeHit(tick.range, e.clientX, e.clientY)
      );
      const mark = hit ? marks.find((m) => m.id === hit.id) : undefined;
      setBranchMenu(mark ? { mark, x: e.clientX, y: e.clientY } : null);
    },
    [ticks, marks, onOpenBranch, onCloseBranch]
  );
  // 菜单开着时，点别处、按 Esc、记录流一滚都收起——它贴着那道虚线，线一动它就指错了地方。
  const branchMenuEl = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!branchMenu) return undefined;
    const onDown = (e: PointerEvent) => {
      if (e.target instanceof Node && branchMenuEl.current?.contains(e.target)) return;
      setBranchMenu(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setBranchMenu(null);
    };
    const onScroll = () => setBranchMenu(null);
    const box = scrollRef.current;
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    box?.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
      box?.removeEventListener('scroll', onScroll);
    };
  }, [branchMenu]);

  /**
   * 暂存列表「点原文」：滚回那段文字，居中，闪一下。
   *
   * 原处那条记录还没加载，就往前翻一页再看，直到找到或翻到会话开头；那条在当前镜头里
   * 看不见，先切回「对话」（与输入区「Show」同一个做法）。翻完也找不到、或者那条在但
   * 文字对不上，就报「没找到原处」，NEVER 跳去别的地方。
   */
  const locateDone = useRef(0);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
  }, []);
  const locateAt = locateTarget?.at ?? 0;
  /** 这一次找原处最近一回往前翻页时，最早那条是谁。翻完它没变，就是这一页没取回来。 */
  const locatePaged = useRef<{ at: number; first: string | undefined } | null>(null);
  /**
   * 跳回原处那次平滑滚动的有效期。原处常在已加载内容的顶上，一路滑过去会碰到「到顶取更早
   * 那一页」的线；那一页前插时视口被钉回半路，动画就此断掉，落点离原处差出一截。这段时间里
   * 不自动取更早的页，人一伸手就作废。
   */
  const locateScrollUntil = useRef(0);
  useEffect(() => {
    if (!locateTarget || locateDone.current === locateAt) return;
    const { mark } = locateTarget;
    const finish = (result: LocateState | 'found') => {
      locateDone.current = locateAt;
      locatePaged.current = null;
      onLocateResult?.(mark.id, result);
    };
    // 人正开着文件那一档就先把记录流露出来，下一拍接着找（这一条也盯着 filesOpen；
    // `locateDone` 还没记，所以合上清单之后这一趟会重跑、照样找得到）。
    if (filesOpen) {
      onFilesOpenChange?.(false);
      return;
    }
    if (terminalOpen) {
      onTerminalOpenChange?.(false);
      return;
    }
    if (watcherOpen) {
      setWatcherOpen(false);
      return;
    }
    if (!records.some((r) => r.id === mark.record_id)) {
      if (hasOlder) {
        if (loadingOlder) {
          onLocateResult?.(mark.id, 'searching');
          return;
        }
        // 上一页翻完了、最早那条却没变：这一页没取回来（接口失败之类）。不原地连着重翻，
        // 报「没找到原处」，人再点一次原文就从头再找。
        const paged = locatePaged.current;
        if (paged && paged.at === locateAt && paged.first === records[0]?.id) {
          finish('notFound');
          return;
        }
        locatePaged.current = { at: locateAt, first: records[0]?.id };
        onLocateResult?.(mark.id, 'searching');
        onLoadOlder();
        return;
      }
      if (!loadingOlder) finish('notFound');
      return;
    }
    if (!visible.some((r) => r.id === mark.record_id)) {
      if (lens !== 'talk') setLens('talk');
      else finish('notFound');
      return;
    }
    const box = scrollRef.current;
    const el = box?.querySelector<HTMLElement>(
      `[data-record-id="${CSS.escape(mark.record_id)}"][${RECORD_BODY_ATTR}]`
    );
    const range = el ? findMarkRange(el, mark.text, mark.occurrence) : null;
    if (!box || !el || !range) {
      finish('notFound');
      return;
    }
    // 居中落位。Range 量不出位置（老浏览器、测试环境）就退到那条记录本身。
    const rect =
      typeof range.getBoundingClientRect === 'function'
        ? range.getBoundingClientRect()
        : el.getBoundingClientRect();
    const view = box.getBoundingClientRect();
    const top = box.scrollTop + rect.top - view.top - (box.clientHeight - rect.height) / 2;
    programmaticUntil.current = Date.now() + PROGRAMMATIC_MS.smooth;
    locateScrollUntil.current = programmaticUntil.current;
    followArmed.current = false;
    if (typeof box.scrollTo === 'function') box.scrollTo({ top, behavior: scrollBehavior() });
    else box.scrollTop = top;
    paintHighlight(MARK_FLASH, [range], HIGHLIGHT_PRIORITY.flash, painter);
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(
      () => paintHighlight(MARK_FLASH, [], HIGHLIGHT_PRIORITY.flash, painter),
      FLASH_MS
    );
    finish('found');
    // 只盯「点下去」这一刻与它等着的那几样：翻页回来、镜头换完、文件那一档合上
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locateAt, records, hasOlder, loadingOlder, visible, lens, filesOpen, terminalOpen, watcherOpen]);

  /** 人的滚动输入留下一张短期通行证：随后的 onScroll 按手动处理。 */
  const noteManualIntent = useCallback(() => {
    manualIntentUntil.current = Date.now() + MANUAL_INTENT_MS;
    // 人一伸手，程序那次滚动就作废——接下来的每一个事件都是人的，不许再被当成动画余波。
    programmaticUntil.current = 0;
    locateScrollUntil.current = 0;
  }, []);

  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLDivElement>) => {
      if (SCROLL_KEYS.has(e.key)) noteManualIntent();
    },
    [noteManualIntent]
  );

  const handleMouseDown = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>) => {
      // 只有按在滚动条那一窄条上才算滚动意图——按在正文上是在点选文字。
      const el = scrollRef.current;
      if (el && e.clientX > el.getBoundingClientRect().right - 20) {
        isDraggingScrollbar.current = true;
        noteManualIntent();
      }
    },
    [noteManualIntent]
  );

  const handleScroll = useCallback(
    (e: UIEvent<HTMLDivElement>) => {
      if (overlayViewOpenRef.current) {
        setShowJump(false);
        return;
      }
      const el = e.currentTarget;
      const now = Date.now();

      // 「跳到最新」按钮的显隐只看位置，不问是谁滚的。但有一个方向的例外：程序平滑
      // 滚向底部的一路经过的中间位置都离底很远，若照实亮按钮，人看到的是它闪一下又
      // 灭掉。所以**熄灭随时允许**（程序落底后事件还在余波里，按钮要能灭），**亮起**
      // 要等程序滚动窗口过去——那些中间位置不许点灯。
      const jumpGap = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowJump((prev) => {
        if (overlayViewOpenRef.current) return false;
        const next = jumpGap > JUMP_SHOW_PX;
        if (next === prev) return prev;
        if (next && now <= programmaticUntil.current) return prev;
        return next;
      });

      // 实时判定视口是否覆盖「[底部上方 100px ～ 底部]」热区
      const coveringBottom = isViewportCoveringBottom(el);

      // 非程序平滑滚动窗口期间的滚动：更新自动贴底跟随状态
      if (now > programmaticUntil.current) {
        if (coveringBottom) {
          // 视口处于或回到「[底部上方 100px ～ 底部]」热区时立即武装
          followArmed.current = true;
        } else {
          // 离开底部 100px 热区：必须是明确的用户手动输入（滚轮、触摸、按键、拖拽滚动条）才解除武装！
          // 彻底防止平滑滚动动画耗时超出预期时的中间帧把自动跟随误关掉（防止「滚着滚着自己不跟了」）！
          const isUserManual = now <= manualIntentUntil.current || isDraggingScrollbar.current;
          if (isUserManual) {
            followArmed.current = false;
          }
        }
      }

      // 翻到顶附近：钉住当前几何，取更早的一页前插。
      if (el.scrollTop < NEAR_TOP_PX) {
        // 跳回原处正滑着：不取（见 locateScrollUntil）。
        if (now > locateScrollUntil.current && olderArmed.current && hasOlder && !loadingOlder) {
          olderArmed.current = false;
          anchor.current = { height: el.scrollHeight, top: el.scrollTop };
          onLoadOlder();
        }
      } else {
        olderArmed.current = true;
      }
    },
    [hasOlder, loadingOlder, onLoadOlder]
  );

  // 缩略滚动条只在「全部」「对话」两档出现（spec 20260928-webui-session-stack 已定）。
  const showMinimap =
    minimap && !watcherOpen && (lens === 'all' || lens === 'talk') && visible.length > 0;

  if (!sessionId) {
    return (
      <div className="wb-empty-fill">
        <EmptyState
          Icon={Inbox}
          title={t('workbench.stream.pickSession')}
        />
      </div>
    );
  }

  const inspectActive =
    !watcherOpen &&
    !filesOpen &&
    !terminalOpen &&
    (lens === 'hook' || lens === 'tool' || lens === 'system');
  const inspectShown = inspectOpen || inspectActive;
  const inspectCount = counts.hook + counts.tool + counts.system;

  const lensModel = usage?.model ?? '';
  const lensContextStr =
    usage?.context !== null && usage?.context !== undefined
      ? `${t('workbench.record.usage.context')} ${formatTokensK(usage.context)}`
      : '';
  const hasLensUsage = Boolean(lensModel || lensContextStr);
  const lensUsageTitleParts = [
    usage?.model ?? '',
    usage?.context !== null && usage?.context !== undefined
      ? `${t('workbench.record.usage.context')} ${usage.context.toLocaleString()}`
      : '',
    usage?.total !== null && usage?.total !== undefined
      ? `${t('workbench.record.usage.total')} ${formatTokensM(usage.total)}`
      : '',
  ].filter(Boolean);
  const lensUsageTitle = lensUsageTitleParts.length
    ? `${lensUsageTitleParts.join(' · ')} — ${t('workbench.composer.usageHint')}`
    : undefined;

  // Progress 视图切换会话期间的统一就绪门禁：等待首取 records 与首取 observer state 均落定后再
  // 一次性同帧渲染镜头栏与 PROGRESS LEDGER，防止异步竞态导致的「半截抢跑闪现 → 后手顶开」抖动。
  const watcherWaitingForInitial =
    watcherOpen &&
    Boolean(sessionId) &&
    !error &&
    ((loading && !records.length) ||
      (Boolean(observer?.loading) && !observer?.state && !observer?.error) ||
      (Boolean(childrenLoading) && !scopedChildrenData));

  return (
    <div className="streamcol flex h-full min-h-0 min-w-0 flex-col">
      {(records.length > 0 || hasAnyChildrenContext) && !watcherWaitingForInitial ? (
        <div
          data-testid="stream-lens"
          data-inspect={inspectShown ? 'open' : 'closed'}
          className="wb-lens shrink-0 border-b border-border-color px-4 py-2"
        >
          {/* 主行仅保留 4 个核心视角（Watcher / Talk / All / Files，及按需挂载的 Terminal），
              Hooks / Tools / System 收进二级 Inspect 折叠组，右侧放紧凑模型与上下文读数。 */}
          <div className="wb-lens-group ui-seg-group">
            <button
              type="button"
              data-testid="lens-watcher"
              onClick={() => {
                setWatcherOpen(true);
                onFilesOpenChange?.(false);
                onTerminalOpenChange?.(false);
              }}
              aria-pressed={watcherOpen && !filesOpen && !terminalOpen}
              className={`wb-lens-pill ui-seg-pill ${
                watcherOpen && !filesOpen && !terminalOpen ? 'ui-seg-pill--active' : ''
              }`}
            >
              <span>{t('workbench.stream.watcher')}</span>
              {progressBadge.badgeText ? (
                <span
                  data-testid="lens-watcher-badge"
                  className={`wb-lens-badge ${
                    progressBadge.tone === 'delivering' ? 'is-delivering' : 'is-running'
                  }`}
                >
                  {progressBadge.badgeText}
                </span>
              ) : progressBadge.externalOnlyDot ? (
                <span data-testid="lens-watcher-external-dot" className="wb-lens-live" />
              ) : null}
            </button>
            {(['talk', 'all'] as const).map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => {
                  setWatcherOpen(false);
                  setLens(id);
                  onFilesOpenChange?.(false);
                  onTerminalOpenChange?.(false);
                }}
                aria-pressed={lens === id && !filesOpen && !terminalOpen && !watcherOpen}
                data-testid={`lens-${id}`}
                disabled={counts[id] === 0}
                className={`wb-lens-pill ui-seg-pill ${
                  lens === id && !filesOpen && !terminalOpen && !watcherOpen
                    ? 'ui-seg-pill--active'
                    : ''
                }`}
              >
                {t(LENS_LABEL_KEY[id])}
                <span className="ui-seg-count">{counts[id]}</span>
              </button>
            ))}
            {filesView ? (
              <button
                type="button"
                data-testid="lens-files"
                onClick={() => {
                  setWatcherOpen(false);
                  onTerminalOpenChange?.(false);
                  onFilesOpenChange?.(!filesOpen);
                }}
                aria-pressed={filesOpen}
                title={t('workbench.files.lensHint')}
                className={`wb-lens-pill ui-seg-pill ${filesOpen ? 'ui-seg-pill--active' : ''}`}
              >
                {t('workbench.files.lens')}
                {typeof filesCount === 'number' ? (
                  <span className="ui-seg-count">{filesCount}</span>
                ) : filesPending ? (
                  <span data-testid="lens-files-pending" className="ui-seg-count">
                    …
                  </span>
                ) : null}
              </button>
            ) : null}
            {terminalView ? (
              <button
                type="button"
                data-testid="lens-terminal"
                onClick={() => {
                  setWatcherOpen(false);
                  onFilesOpenChange?.(false);
                  onTerminalOpenChange?.(!terminalOpen);
                }}
                aria-pressed={terminalOpen}
                title={t('workbench.terminal.lensHint')}
                className={`wb-lens-pill ui-seg-pill ${terminalOpen ? 'ui-seg-pill--active' : ''}`}
              >
                {t('workbench.terminal.lens')}
                {terminalAlive ? (
                  <span data-testid="lens-terminal-alive" className="wb-lens-live" />
                ) : null}
              </button>
            ) : null}
          </div>

          {inspectShown ? (
            <div className="lens-inspect-grp" data-testid="lens-inspect-group">
              <div className="wb-lens-group ui-seg-group">
                {(['hook', 'tool', 'system'] as const).map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => {
                      setWatcherOpen(false);
                      setLens(id);
                      onFilesOpenChange?.(false);
                      onTerminalOpenChange?.(false);
                    }}
                    aria-pressed={lens === id && !filesOpen && !terminalOpen && !watcherOpen}
                    data-testid={`lens-${id}`}
                    title={id === 'hook' ? t('workbench.stream.lensHookFull') : undefined}
                    disabled={counts[id] === 0}
                    className={`wb-lens-pill ui-seg-pill ${
                      lens === id && !filesOpen && !terminalOpen && !watcherOpen
                        ? 'ui-seg-pill--active'
                        : ''
                    }`}
                  >
                    {t(LENS_LABEL_KEY[id])}
                    <span className="ui-seg-count">{counts[id]}</span>
                  </button>
                ))}
              </div>
              {!inspectActive ? (
                <button
                  type="button"
                  className="lens-inspect-close"
                  data-testid="lens-inspect-close"
                  title={t('workbench.stream.lensInspectCollapse')}
                  aria-label={t('workbench.stream.lensInspectCollapse')}
                  onClick={() => setInspectOpen(false)}
                >
                  <X size={12} />
                </button>
              ) : null}
            </div>
          ) : (
            <button
              type="button"
              className="lens-inspect-btn"
              data-testid="lens-inspect-toggle"
              aria-expanded={false}
              title={t('workbench.stream.lensInspectHint')}
              onClick={() => setInspectOpen(true)}
            >
              <span>{t('workbench.stream.lensInspect')}</span>
              <span aria-hidden="true">·</span>
              <span className="n">{inspectCount}</span>
              <ChevronDown size={12} />
            </button>
          )}

          {hasLensUsage ? (
            <span
              data-testid="lens-usage"
              className="lens-usage"
              title={lensUsageTitle}
            >
              {lensModel ? (
                <span
                  data-testid="lens-usage-model"
                  className="lens-usage-model"
                  title={lensModel}
                >
                  {lensModel}
                </span>
              ) : null}
              {lensModel && lensContextStr ? (
                <span aria-hidden="true" className="lens-usage-sep">
                  {' · '}
                </span>
              ) : null}
              {lensContextStr ? (
                <span data-testid="lens-usage-context" className="lens-usage-context">
                  {lensContextStr}
                </span>
              ) : null}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* 缩略滚动条压在滚动区右侧那条空白里，所以两者包在同一个定位框里；它只在「全部」
          「对话」两档出现，其余几档本来就没有人发言和代理回复可画。 */}
      <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        id="record-stream-scroll"
        onScroll={handleScroll}
        onWheel={noteManualIntent}
        onTouchMove={noteManualIntent}
        onKeyDown={handleKeyDown}
        onMouseDown={handleMouseDown}
        onClick={handleStreamClick}
        /* 滚动容器的内距契约：左右各 20（上 16 下 40）。底下比上面厚，是因为滚到底那一刻
           最后一条不该被硬切在容器边框上，而输入框就压在下面。挂着缩略滚动条时右边
           多让出到 40px（12px 宽的滚动条压在离右边 12px 处，占右侧 24px 以内），保留
           16px 安全间距，防止用户消息卡外圆角及 ring-1 描边与滚动条区域重叠。 */
        className={`min-h-0 flex-1 overflow-y-auto ${
          watcherOpen
            ? ''
            : `pb-10 pl-5 pt-4 ${showMinimap ? 'record-stream-no-bar pr-10' : 'pr-5'}`
        }`}
        data-testid="record-stream-scroll"
      >
        <FileLinkContext.Provider value={preview ? handleFileLink : null}>
        <RecordStreamActionsContext.Provider value={streamActions}>
        <div
          ref={contentRef}
          data-testid="record-stream-content"
          className={`wb-stream-body flex min-h-full w-full min-w-0 flex-col gap-4 ${
            watcherOpen ? 'justify-start' : 'justify-end'
          }`}
        >
          {!watcherOpen && loadingOlder ? (
            <p className="flex items-center justify-center gap-2 py-2 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              {t('workbench.stream.loadingOlder')}
            </p>
          ) : null}

          {!hasOlder && records.length && !watcherOpen ? (
            <p className="py-2 text-center text-[11px] text-text-muted">
              {t('workbench.stream.streamStart', { n: records.length })}
            </p>
          ) : null}

          {error ? (
            <p className="rounded-[6px] bg-bg-subtle px-3 py-2 text-[12px] text-text-secondary">
              {error}
            </p>
          ) : null}

          {!watcherOpen && records.length && !visible.length && !segments.length ? (
            <p className="my-auto py-10 text-center text-[12px] text-text-muted">
              {t('workbench.stream.lensEmpty')}
            </p>
          ) : null}

          {!records.length &&
          !loading &&
          !watcherWaitingForInitial &&
          !error &&
          !(watcherOpen && (Boolean(observer?.state) || hasAnyChildrenContext)) ? (
            <div className="my-auto flex flex-col items-center gap-4 py-16">
              <EmptyState
                Icon={Inbox}
                title={t('workbench.stream.emptySession')}
                description={t('workbench.stream.emptySessionHint')}
              />
              {hasAnyChildrenContext && scopedChildrenData ? (
                <div
                  data-testid="empty-stream-children-hint"
                  className="w-empty-children-card"
                >
                  <ProgressOriginStrip
                    launchedBy={scopedChildrenData.launched_by}
                    onSelectSession={onSelectSession}
                  />
                  <div className="w-empty-children-foot">
                    <span className="w-empty-children-summary">
                      {progressBadge.activeCount > 0
                        ? t('workbench.children.emptyActiveSummary', {
                            count: progressBadge.activeCount,
                          })
                        : scopedChildrenData.summary.external_host_alive
                          ? t('workbench.children.externalHostTitle')
                          : t('workbench.children.emptyHistorySummary', {
                              count:
                                scopedChildrenData.child_sessions.length +
                                scopedChildrenData.child_processes.length,
                            })}
                    </span>
                    <button
                      type="button"
                      data-testid="empty-stream-open-progress"
                      onClick={() => {
                        setWatcherOpen(true);
                        onFilesOpenChange?.(false);
                        onTerminalOpenChange?.(false);
                      }}
                      className="w-empty-children-btn"
                    >
                      <span>{t('workbench.children.emptyViewProgress')}</span>
                      <ArrowUpRight size={12} strokeWidth={1.5} />
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}

          {watcherOpen &&
          !watcherWaitingForInitial &&
          (records.length > 0 || Boolean(observer?.state) || hasAnyChildrenContext) ? (() => {
            const hasObserverOrRecords = records.length > 0 || Boolean(observer?.state);
            const isDelegationActive = Boolean(
              scopedChildrenData?.summary?.has_running ||
                scopedChildrenData?.summary?.external_host_alive
            );
            const state = observer?.state ?? null;
            const rawAnchorHasBridge =
              parseWebBridgeContext(state?.anchor ?? '').hasBridgeContext ||
              parseTextQuoteBlocks(state?.anchor ?? '').hasQuotes;
            const firstUserHasBridge = resolved.some(
              (r) =>
                r.kind === 'user.say' &&
                typeof r.payload.text === 'string' &&
                (parseWebBridgeContext(r.payload.text).hasBridgeContext ||
                  parseTextQuoteBlocks(r.payload.text).hasQuotes)
            );
            const cleanedStateAnchor = cleanGoalText(state?.anchor);
            const anchorText =
              cleanedStateAnchor ||
              firstHumanGoal ||
              t('workbench.report.none');
            const anchorSummaryText =
              cleanedStateAnchor || firstHumanGoal
                ? (!(rawAnchorHasBridge || firstUserHasBridge) && cleanGoalText(state?.anchor_summary)) ||
                  extractGoalSummary(anchorText)
                : null;
            const modelLabel = state?.model || 'observer';
            const latestSlice =
              watcherSlices.length > 0 ? watcherSlices[watcherSlices.length - 1] : null;
            const updatedAtMs = state?.updated_at ?? latestSlice?.at ?? null;
            const updatedHm = formatHm(updatedAtMs);
            const doingCount = watcherTasks.filter((task) => task.status === 'doing').length;
            const waitingCount = watcherTasks.filter((task) => task.status === 'waiting').length;
            const doneCount = watcherTasks.filter((task) => isCompletedWatcherTask(task)).length;
            const taskPartition = partitionTasksForOverview(watcherTasks);

            let pendingCard: {
              taskId: string;
              question: string;
              hasInteractiveCard: boolean;
            } | null = null;
            for (const sl of watcherSlices) {
              for (const dc of sl.decisionCards) {
                if (!decisionCardHost?.answerOf(dc.recordId)) {
                  pendingCard = {
                    taskId: sl.taskId,
                    question: dc.block.question,
                    hasInteractiveCard: true,
                  };
                  break;
                }
              }
              if (pendingCard) break;
            }
            if (!pendingCard && unsummarizedTailRecords.length > 0) {
              const tailCards = extractSliceDecisionCards(unsummarizedTailRecords);
              for (const dc of tailCards) {
                if (!decisionCardHost?.answerOf(dc.recordId)) {
                  pendingCard = {
                    taskId: latestSlice?.taskId || 'T1',
                    question: dc.block.question,
                    hasInteractiveCard: true,
                  };
                  break;
                }
              }
            }
            const cleanedStateDecision = cleanTailText(state?.decision);
            const tasksAllowDecision = watcherTasks.length === 0 || waitingCount > 0;
            if (!pendingCard && cleanedStateDecision && tasksAllowDecision) {
              const waitingTask = watcherTasks.find((task) => task.status === 'waiting');
              pendingCard = {
                taskId: waitingTask?.id || latestSlice?.taskId || 'T1',
                question: cleanedStateDecision,
                hasInteractiveCard: false,
              };
            }

            const curStateStatus: 'running' | 'waiting' | 'done' =
              pendingCard || waitingCount > 0
                ? 'waiting'
                : state?.tail?.kind === 'now' || doingCount > 0
                  ? 'running'
                  : 'done';
            const curStateText =
              cleanTailText(state?.tail?.text) ||
              latestSlice?.doing ||
              (state?.happened?.length ? cleanTailText(state.happened[0]) : '') ||
              t('workbench.report.none');

            const taskStatusLabel: Record<ObserverTaskItem['status'], string> = {
              done: '已办结',
              doing: '在办',
              waiting: '待拍板',
              blocked: '阻塞',
              error: '异常',
              failed: '失败',
            };
            const hiddenCount = taskPartition.hiddenCompletedTasks.length;
            const foldRangeSuffix = taskPartition.hiddenIdSummary
              ? ` (${taskPartition.hiddenIdSummary})`
              : '';
            const renderTaskActor = (actor: string) => {
              const matched = matchActorToChildSession(
                actor,
                scopedChildrenData?.child_sessions ?? []
              );
              if (!matched || !onSelectSession) {
                return actor;
              }
              const dotCls =
                matched.status === 'running'
                  ? 'd-run'
                  : matched.status === 'delivering' || matched.status === 'awaiting_input'
                    ? 'd-warn'
                    : matched.status === 'error'
                      ? 'd-err'
                      : 'd-muted';
              return (
                <button
                  type="button"
                  data-testid={`task-actor-link-${matched.session_id}`}
                  onClick={() => onSelectSession(matched.session_id)}
                  title={matched.title}
                  className="w-actor-link"
                >
                  <span aria-hidden="true" className={`w-dot ${dotCls}`} />
                  <span className="truncate">{actor}</span>
                  <ArrowUpRight size={11} strokeWidth={1.5} className="shrink-0" />
                </button>
              );
            };
            const renderTaskRow = (task: ObserverTaskItem, keySuffix = '') => {
              const completed = isCompletedWatcherTask(task);
              const badgeCls = completed ? 'done' : task.status;
              const badgeLabel =
                taskStatusLabel[task.status] || (completed ? '已办结' : task.status);
              return (
                <tr
                  key={`${task.id}${keySuffix}`}
                  data-testid={`watcher-task-row-${task.id}`}
                  data-task-completed={completed ? 'true' : 'false'}
                  className={`w-task-row ${completed ? 'is-completed' : ''}`}
                >
                  <td>
                    <span className="w-tid">{task.id}</span>
                  </td>
                  <td>
                    <span className="w-tm">{formatHm(task.proposed_at)}</span>
                  </td>
                  <td>
                    <span className="w-task-title">
                      <WatcherInlineText text={task.title} />
                    </span>
                  </td>
                  <td>
                    <span className={`w-st-badge ${badgeCls}`}>
                      {task.status === 'doing' ? <i className="w-dot d-run" /> : null}
                      {badgeLabel}
                    </span>
                  </td>
                  <td>{renderTaskActor(task.actor)}</td>
                  <td>
                    <WatcherInlineText text={task.conclusion} />
                  </td>
                </tr>
              );
            };

            return (
              <div className="wwrap" data-testid="watcher-view">
                {/* L0. 上游来历微条（仅当由其他会话或定时任务启动时展示） */}
                <ProgressOriginStrip
                  launchedBy={scopedChildrenData?.launched_by ?? null}
                  onSelectSession={onSelectSession}
                />

                {/* L1. 顶部态势锚点卡 */}
                {hasObserverOrRecords ? (
                <section className="w-anchor-card" data-testid="watcher-anchor-card">
                  <div className="w-anchor-top">
                    <div className="w-anchor-title">
                      <span className="w-kicker">PROGRESS LEDGER</span>
                      <span className="w-meta">
                        {modelLabel} · updated {updatedHm}
                      </span>
                    </div>
                    <div className="w-stat-pills" data-testid="watcher-stat-pills">
                      <span className="w-stat doing">
                        {doingCount > 0 ? <i className="w-dot d-run w-pulse" /> : null}
                        在办 {doingCount}
                      </span>
                      <span className={`w-stat waiting ${waitingCount > 0 ? 'has' : ''}`}>
                        待拍板 {waitingCount}
                      </span>
                      <span className="w-stat done">已办结 {doneCount}</span>
                    </div>
                  </div>
                  <div
                    className={`w-anchor-grid ${anchorExpanded || stateExpanded ? 'has-expanded' : ''}`}
                  >
                    <div className="w-box" data-testid="watcher-goal-anchor">
                      <div className="w-box-lbl">
                        <span>① Goal Anchor · 总目标锚点</span>
                      </div>
                      <WatcherBoxBody
                        fullText={anchorText}
                        summaryText={anchorSummaryText}
                        expanded={anchorExpanded}
                        onToggle={() => setAnchorExpanded((v) => !v)}
                        testIdPrefix="watcher-goal-anchor"
                        expandLabel={t('workbench.stream.watcherExpandFull')}
                        collapseLabel={t('workbench.stream.watcherCollapseFull')}
                        lengthLabel={t('workbench.stream.watcherFullLength', {
                          count: anchorText.length,
                        })}
                      />
                    </div>
                    <div className="w-box is-now" data-testid="watcher-current-state">
                      <div className="w-box-lbl">
                        <span>③ Current State · 此刻状态</span>
                        {curStateStatus === 'running' ? (
                          <span className="w-box-state running">
                            <i className="w-dot d-run w-pulse" />
                            Running
                          </span>
                        ) : curStateStatus === 'waiting' ? (
                          <span className="w-box-state waiting">
                            <i className="w-dot d-warn" />
                            Waiting decision
                          </span>
                        ) : (
                          <span className="w-box-state done">Completed</span>
                        )}
                      </div>
                      <WatcherBoxBody
                        fullText={curStateText}
                        expanded={stateExpanded}
                        onToggle={() => setStateExpanded((v) => !v)}
                        testIdPrefix="watcher-current-state"
                        expandLabel={t('workbench.stream.watcherExpandFull')}
                        collapseLabel={t('workbench.stream.watcherCollapseFull')}
                        lengthLabel={t('workbench.stream.watcherFullLength', {
                          count: curStateText.length,
                        })}
                      />
                    </div>
                  </div>
                  {pendingCard ? (
                    <div className="w-decision-bar" data-testid="watcher-decision-banner">
                      <span className="w-dec-q" title={pendingCard.question}>
                        待主人拍板 · [{pendingCard.taskId}] {pendingCard.question}
                      </span>
                      {pendingCard.hasInteractiveCard ? (
                        <button
                          type="button"
                          className="w-decision-btn"
                          onClick={() => jumpToPendingCard()}
                        >
                          定位决策卡 ↓
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </section>
                ) : null}

                {/* L2（活跃置顶）：委派与后台执行区 */}
                {isDelegationActive ? (
                  <ProgressDelegationSection
                    data={scopedChildrenData}
                    onSelectSession={onSelectSession}
                  />
                ) : null}

                {/* L3. 最新发出 / 尚未纳入下批里程碑汇总的实时对话区：置顶在锚点卡下方，保证与「最新在上」读序一致 */}
                {hasObserverOrRecords ? (() => {
                  const tailSegments = unsummarizedTailRecords.length
                    ? buildTalkSegments(unsummarizedTailRecords)
                    : [];
                  const tailGroups = tailSegments.length ? groupSegments(tailSegments) : [];
                  const showTailAgentOnIt = Boolean(
                    activeTrail &&
                      !unsummarizedTailRecords.some((r) => r.id === activeTrail.recordId)
                  );
                  if (!tailGroups.length && !showTailAgentOnIt) return null;
                  const orderedTailGroups = [...tailGroups].reverse();
                  return (
                    <section
                      data-testid="watcher-unsummarized-tail"
                      className="w-sec"
                    >
                      <div className="w-sec-hd">
                        <span className="w-sec-title">
                          {isZh ? '最新消息与实时动态' : 'Latest Messages & Live Activity'}
                        </span>
                        <span className="w-sec-sub">
                          {isZh ? '待纳入下批里程碑 · 最新在上' : 'Pending next milestone · newest first'}
                        </span>
                      </div>
                      <div className="flex max-h-[360px] min-w-0 flex-col gap-3 overflow-y-auto rounded-[10px] border border-[var(--border-color)] bg-[var(--bg-primary)] p-3.5">
                        {orderedTailGroups.map((group, gIdx) =>
                          group.segments.length === 1 ? (
                            renderSegment(group.segments[0])
                          ) : (
                            <section
                              key={`${group.groupId ?? 'loose'}-tail-${gIdx}`}
                              data-testid="record-group"
                              className="flex min-w-0 flex-col gap-1"
                            >
                              {group.segments.map((seg) => renderSegment(seg))}
                            </section>
                          )
                        )}
                        {showTailAgentOnIt ? agentOnIt : null}
                      </div>
                    </section>
                  );
                })() : null}

                {/* L4. 第一张表：事项总控表 */}
                {hasObserverOrRecords ? (
                <section className="w-sec" data-testid="watcher-tasks-table">
                  <div className="w-sec-hd">
                    <span className="w-sec-title">事项总控表 · Tasks Overview</span>
                    <span className="w-sec-sub">
                      {taskPartition.canCollapse && !isCompletedTasksExpanded
                        ? `${watcherTasks.length} 项事项 · 已折叠 ${hiddenCount} 项完结 · JSON 实时汇总`
                        : `${watcherTasks.length} 项事项 · JSON 实时汇总`}
                    </span>
                  </div>
                  <div
                    className={`w-tbl-wrap ${
                      taskPartition.canCollapse && !isCompletedTasksExpanded
                        ? 'has-folded-tasks'
                        : ''
                    }`}
                  >
                    <table className="w-tbl w-tasks-tbl">
                      <colgroup>
                        <col style={{ width: '54px' }} />
                        <col style={{ width: '62px' }} />
                        <col style={{ width: '22%' }} />
                        <col style={{ width: '82px' }} />
                        <col style={{ width: '124px' }} />
                        <col />
                      </colgroup>
                      <thead>
                        <tr>
                          <th>编号</th>
                          <th>提出</th>
                          <th>事项简述</th>
                          <th>当前状态</th>
                          <th>承接执行体</th>
                          <th>最新结论与产物</th>
                        </tr>
                      </thead>
                      <tbody>
                        {watcherTasks.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="text-center text-text-muted">
                              {t('workbench.stream.watcherEmptySummary')}
                            </td>
                          </tr>
                        ) : taskPartition.canCollapse ? (
                          !isCompletedTasksExpanded ? (
                            <>
                              {taskPartition.peekTask ? (
                                <tr
                                  key={`peek-${taskPartition.peekTask.id}`}
                                  className="w-tasks-peek-row"
                                  data-testid="watcher-tasks-peek-row"
                                  aria-hidden="true"
                                  onClick={toggleCompletedTasksExpanded}
                                  title={
                                    isZh
                                      ? `点击展开全部 ${hiddenCount} 项已完结旧事项`
                                      : `Expand ${hiddenCount} completed tasks`
                                  }
                                >
                                  <td>
                                    <div className="w-tasks-peek-cell">
                                      <span className="w-tid">{taskPartition.peekTask.id}</span>
                                    </div>
                                  </td>
                                  <td>
                                    <div className="w-tasks-peek-cell">
                                      <span className="w-tm">
                                        {formatHm(taskPartition.peekTask.proposed_at)}
                                      </span>
                                    </div>
                                  </td>
                                  <td>
                                    <div className="w-tasks-peek-cell">
                                      <span className="w-task-title">
                                        <WatcherInlineText text={taskPartition.peekTask.title} />
                                      </span>
                                    </div>
                                  </td>
                                  <td>
                                    <div className="w-tasks-peek-cell">
                                      <span className="w-st-badge done">
                                        {taskStatusLabel[taskPartition.peekTask.status] || '已办结'}
                                      </span>
                                    </div>
                                  </td>
                                  <td>
                                    <div className="w-tasks-peek-cell">
                                      {renderTaskActor(taskPartition.peekTask.actor)}
                                    </div>
                                  </td>
                                  <td>
                                    <div className="w-tasks-peek-cell">
                                      <WatcherInlineText
                                        text={taskPartition.peekTask.conclusion}
                                      />
                                    </div>
                                  </td>
                                </tr>
                              ) : null}
                              <tr
                                className="w-tasks-fold-row is-collapsed"
                                data-testid="watcher-tasks-fold-row"
                              >
                                <td colSpan={6}>
                                  <div className="w-tasks-fold-bar">
                                    <span className="w-tasks-fold-info">
                                      <span className="w-tasks-fold-dots" aria-hidden="true">
                                        <i />
                                        <i />
                                        <i />
                                      </span>
                                      <span>
                                        {isZh
                                          ? `已自动折叠 ${hiddenCount} 项已完结旧事项${foldRangeSuffix}`
                                          : `Collapsed ${hiddenCount} completed task(s)${foldRangeSuffix}`}
                                      </span>
                                    </span>
                                    <button
                                      type="button"
                                      className="w-tasks-fold-btn"
                                      data-testid="watcher-tasks-fold-toggle"
                                      aria-expanded={false}
                                      onClick={toggleCompletedTasksExpanded}
                                    >
                                      <span>
                                        {isZh
                                          ? `展开已完结 (${hiddenCount})`
                                          : `Show completed (${hiddenCount})`}
                                      </span>
                                      <ChevronDown size={12} />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                              {taskPartition.visibleTasks.map((task) => renderTaskRow(task))}
                            </>
                          ) : (
                            <>
                              <tr
                                className="w-tasks-fold-row is-expanded"
                                data-testid="watcher-tasks-fold-row"
                              >
                                <td colSpan={6}>
                                  <div className="w-tasks-fold-bar">
                                    <span className="w-tasks-fold-info">
                                      <span>
                                        {isZh
                                          ? `已展开全部 ${hiddenCount} 项已完结事项${foldRangeSuffix}`
                                          : `Showing all ${hiddenCount} completed task(s)${foldRangeSuffix}`}
                                      </span>
                                    </span>
                                    <button
                                      type="button"
                                      className="w-tasks-fold-btn"
                                      data-testid="watcher-tasks-fold-toggle"
                                      aria-expanded={true}
                                      onClick={toggleCompletedTasksExpanded}
                                    >
                                      <span>
                                        {isZh
                                          ? `收起已完结 (${hiddenCount})`
                                          : `Collapse completed (${hiddenCount})`}
                                      </span>
                                      <ChevronUp size={12} />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                              {watcherTasks.map((task) => renderTaskRow(task))}
                            </>
                          )
                        ) : (
                          watcherTasks.map((task) => renderTaskRow(task))
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
                ) : null}

                {/* L2（纯历史态降位折叠）：委派与后台执行区 */}
                {!isDelegationActive ? (
                  <ProgressDelegationSection
                    data={scopedChildrenData}
                    onSelectSession={onSelectSession}
                  />
                ) : null}

                {/* L5. 第二张表：② 阶段里程碑追加记录表 */}
                {hasObserverOrRecords ? (
                <section className="w-sec" data-testid="watcher-milestones-table">
                  <div className="w-sec-hd">
                    <span className="w-sec-title">
                      ② 阶段里程碑追加记录 · Milestones Log (Append-only JSON)
                    </span>
                    <span className="w-sec-sub">
                      {t('workbench.stream.watcherRunsAppended', { count: watcherSlices.length })}
                    </span>
                  </div>
                  <div className="w-tbl-wrap">
                    <table className="w-tbl w-runs-tbl">
                      <colgroup>
                        <col className="col-run" style={{ width: '82px' }} />
                        <col className="col-actor" style={{ width: '128px' }} />
                        <col className="col-main" />
                        <col className="col-talk" style={{ width: '158px' }} />
                      </colgroup>
                      <thead>
                        <tr>
                          <th>批次 / 时刻</th>
                          <th>关联事项 / 主体</th>
                          <th>阶段进展与关键发现</th>
                          <th style={{ textAlign: 'right' }}>对话切片</th>
                        </tr>
                      </thead>
                      <tbody>
                        {watcherSlices.length === 0 ? (
                          <tr>
                            <td colSpan={4} className="text-center text-text-muted">
                              {t('workbench.stream.watcherEmptySummary')}
                            </td>
                          </tr>
                        ) : (
                          watcherSlices
                            .map((slice, origIdx) => ({
                              slice,
                              origNum: slice.runId || origIdx + 1,
                            }))
                            .reverse()
                            .map(({ slice, origNum }) => {
                            const isExpanded = Boolean(expandedWatcherIds[slice.id]);
                            const rawTalkSegments = buildTalkSegments(slice.records);
                            const sliceSegments =
                              rawTalkSegments.length > 0
                                ? rawTalkSegments
                                : slice.records.length > 0
                                  ? collapseRuns(
                                      slice.records.filter(
                                        (r) => r.kind !== 'usage.tick' && !isSilentHook(r)
                                      ),
                                      { tools: true, system: true }
                                    )
                                  : [];
                            const hasTalkContent = sliceSegments.length > 0;
                            const isSliceHistoryPending =
                              resolved.length > 0 &&
                              slice.cursorFrom < resolved[0].seq &&
                              (hasOlder || loadingOlder);
                            const canToggleTalk = hasTalkContent || isSliceHistoryPending;
                            const showTalkBody = isExpanded && canToggleTalk;
                            const sliceGroups =
                              showTalkBody && hasTalkContent ? groupSegments(sliceSegments) : [];
                            const sliceDecisionCards = slice.decisionCards;
                            let promptCount = 0;
                            let toolCallsCount = 0;
                            let thinkingCount = 0;
                            let replyCount = 0;
                            for (const r of slice.records) {
                              if (
                                (r.kind === 'user.say' ||
                                  (r.kind === 'context.inject' &&
                                    r.payload.channel === 'queued_command')) &&
                                !isPureAsyncCallbackRecord(r)
                              ) {
                                promptCount += 1;
                              } else if (r.kind === 'tool.call') {
                                toolCallsCount += 1;
                              } else if (r.kind === 'agent.think') {
                                thinkingCount += 1;
                              } else if (r.kind === 'agent.say') {
                                replyCount += 1;
                              }
                            }
                            if (
                              hasTalkContent &&
                              promptCount === 0 &&
                              toolCallsCount === 0 &&
                              thinkingCount === 0 &&
                              replyCount === 0
                            ) {
                              if (rawTalkSegments.length > 0) {
                                replyCount = rawTalkSegments.length;
                              } else {
                                toolCallsCount = sliceSegments.length;
                              }
                            }
                            const metaCounts: string[] = [];
                            if (promptCount > 0) {
                              metaCounts.push(
                                t('workbench.stream.watcherTalkPromptCount', { count: promptCount })
                              );
                            }
                            if (toolCallsCount > 0) {
                              metaCounts.push(
                                t('workbench.stream.preResponseToolCalls', {
                                  count: toolCallsCount,
                                })
                              );
                            }
                            if (thinkingCount > 0) {
                              metaCounts.push(
                                t('workbench.stream.preResponseThinking', { count: thinkingCount })
                              );
                            }
                            if (replyCount > 0) {
                              metaCounts.push(
                                t('workbench.stream.watcherTalkReplyCount', { count: replyCount })
                              );
                            }
                            const metaSummary = metaCounts.length
                              ? metaCounts.join(' · ')
                              : isSliceHistoryPending
                                ? t('workbench.stream.watcherTalkLoading')
                                : t('workbench.stream.watcherTalkEmpty');
                            const clock = slice.at ? formatClock(slice.at) : '';
                            const hasDetail = showTalkBody || sliceDecisionCards.length > 0;

                            return (
                              <Fragment key={slice.id}>
                                <tr
                                  className="w-run-row"
                                  data-testid={`watcher-run-${origNum}`}
                                >
                                  <td>
                                    <span className="wno">#{origNum}</span>
                                    {clock ? <span className="wtm">{clock}</span> : null}
                                  </td>
                                  <td>
                                    <span className="w-tid">{slice.taskId}</span>
                                    <div className="w-actor">{slice.actor}</div>
                                  </td>
                                  <td>
                                    {slice.phaseGoal ? (
                                      <span className="w-phase-tag">{slice.phaseGoal}</span>
                                    ) : null}
                                    {slice.doing ? (
                                      <div className="w-doing">
                                        <WatcherInlineText text={slice.doing} />
                                      </div>
                                    ) : slice.summary ? (
                                      <div className="w-doing">
                                        <WatcherInlineText text={slice.summary} />
                                      </div>
                                    ) : null}
                                    {slice.findings.length > 0 ? (
                                      <ul className="w-findings">
                                        {slice.findings.map((fi, fIdx) => (
                                          <WatcherFindingItem key={fIdx} text={fi} />
                                        ))}
                                      </ul>
                                    ) : null}
                                  </td>
                                  <td style={{ textAlign: 'right' }}>
                                    <button
                                      type="button"
                                      className="wtalk-btn"
                                      title={`Talk · ${metaSummary}`}
                                      disabled={!canToggleTalk}
                                      aria-expanded={showTalkBody}
                                      data-testid={`watcher-talk-toggle-${origNum}`}
                                      onClick={() => {
                                        if (!canToggleTalk) return;
                                        if (isSliceHistoryPending && hasOlder && !loadingOlder) {
                                          watcherBackfillPaged.current = null;
                                          onLoadOlder();
                                        }
                                        setExpandedWatcherIds((prev) => ({
                                          ...prev,
                                          [slice.id]: !prev[slice.id],
                                        }));
                                      }}
                                    >
                                      {canToggleTalk ? (
                                        showTalkBody ? (
                                          <ChevronDown
                                            size={12}
                                            className="shrink-0 text-text-muted"
                                          />
                                        ) : (
                                          <ChevronRight
                                            size={12}
                                            className="shrink-0 text-text-muted"
                                          />
                                        )
                                      ) : null}
                                      <span className="truncate">Talk · {metaSummary}</span>
                                    </button>
                                  </td>
                                </tr>
                                {hasDetail ? (
                                  <tr className="w-run-detail-row">
                                    <td colSpan={4}>
                                      <div className="w-run-detail-stack">
                                        {showTalkBody ? (
                                          <div
                                            className="wtalk-body"
                                            data-testid={`watcher-talk-body-${origNum}`}
                                          >
                                            {sliceGroups.length > 0 ? (
                                              sliceGroups.map((group, gIdx) =>
                                                group.segments.length === 1 ? (
                                                  renderSegment(group.segments[0])
                                                ) : (
                                                  <section
                                                    key={`${group.groupId ?? 'loose'}-${gIdx}`}
                                                    data-testid="record-group"
                                                    className="flex min-w-0 flex-col gap-1"
                                                  >
                                                    {group.segments.map((seg) => renderSegment(seg))}
                                                  </section>
                                                )
                                              )
                                            ) : (
                                              <div
                                                className="flex items-center gap-2 py-1 text-[12px] text-text-muted"
                                                data-testid={`watcher-talk-loading-${origNum}`}
                                              >
                                                <Loader2 size={13} className="animate-spin" />
                                                <span>{t('workbench.stream.watcherTalkLoading')}</span>
                                              </div>
                                            )}
                                          </div>
                                        ) : null}
                                        {sliceDecisionCards.length > 0 ? (
                                          <div
                                            data-testid="watcher-card-slot"
                                            className="flex min-w-0 flex-col gap-2"
                                          >
                                            {sliceDecisionCards.map((dc) => (
                                              <DecisionCard
                                                key={dc.recordId}
                                                block={dc.block}
                                                recordId={dc.recordId}
                                              />
                                            ))}
                                          </div>
                                        ) : null}
                                      </div>
                                    </td>
                                  </tr>
                                ) : null}
                              </Fragment>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
                ) : null}
              </div>
            );
          })() : watcherOpen ? null : (
            groups.map((group, index) => {
              /* **归组只剩间距，头上不再有字。**
                 同一次回复里的几条收在 4px 里，两次回复之间隔 16px——人不读一个字也看得出
                 哪几条是一伙的。从前这里还有一行「同一次回复 · 模型名 · 本组 N 条」：它要
                 说的只是下面几条同属一轮，而这件事间距已经说完了；模型名每一轮都要重写一遍，
                 一场会话几百轮就是几百遍同一个牌子。模型名现在常驻在输入框右下那边，一次
                 性说清"现在是谁在答"。 */
              if (group.segments.length === 1) return renderSegment(group.segments[0]);
              return (
                <section
                  key={`${group.groupId ?? 'loose'}-${index}`}
                  data-testid="record-group"
                  className="flex min-w-0 flex-col gap-1"
                >
                  {group.segments.map((seg) => renderSegment(seg))}
                </section>
              );
            })
          )}

          {/* 换到一场会话、首取还没落定：占住空态的位置说「正在加载」。大会话首取要好几秒，
              这段时间里摆空白或空态，人会以为这场会话没有内容。 */}
          {((loading && !records.length && !error) || watcherWaitingForInitial) ? (
            <div
              data-testid="record-stream-loading"
              className="my-auto flex flex-col items-center gap-3 py-16 text-text-muted"
            >
              <Loader2 size={28} className="animate-spin" />
              <p className="text-[13px]">{t('workbench.stream.loading')}</p>
            </div>
          ) : null}

          {!watcherOpen && loading && records.length ? (
            <p className="flex items-center justify-center gap-2 py-4 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              {t('workbench.stream.loading')}
            </p>
          ) : null}

          {/* 「Agent on it」紧贴在那句话下面。那句话在当前镜头里看不见时（切到了工具档），
              退到流的末尾，安静期照样有东西撑着；Progress 视图下统一渲染在顶部动态区内。 */}
          {!watcherOpen && activeTrail && !activeShown ? agentOnIt : null}
        </div>
        </RecordStreamActionsContext.Provider>
        </FileLinkContext.Provider>
      </div>
      {showMinimap ? (
        <StreamMinimap
          scrollRef={scrollRef}
          ticks={ticks}
          version={groups}
          onUserScroll={noteManualIntent}
        />
      ) : null}

      {/* 人翻上去看历史了：右下角亮一颗「跳到最新」，一键沉底。只看位置（距底超过
          JUMP_SHOW_PX），不问是谁滚的；就在底部附近时不出现，不打扰。挂着缩略滚动条
          时右边让出它那一条（那条压在离右 12px 处，占右侧 24px 以内）。 */}
      {showJump && !watcherOpen && !filesOpen && !terminalOpen ? (
        <button
          type="button"
          data-testid="jump-to-latest"
          onClick={jumpToLatest}
          title={t('workbench.stream.jumpToLatest')}
          aria-label={t('workbench.stream.jumpToLatest')}
          className={`absolute bottom-12 z-10 flex h-8 w-8 items-center justify-center rounded-full border border-border-color bg-bg-elevated text-text-secondary shadow-md backdrop-blur-sm transition-colors hover:text-text-primary ${
            showMinimap ? 'right-10' : 'right-4'
          }`}
        >
          <ArrowDown size={15} strokeWidth={2} />
        </button>
      ) : null}

      {/* 文件那一档铺在这块滚动区上面，**记录流不卸载**：它一卸，滚动位置、标注高亮、
          翻过的页全都得重建，回来时人又落在别处。盖住而不是换掉，回来还是原来那一眼。 */}
      {filesOpen && filesView ? (
        <div
          data-testid="files-panel"
          className="absolute inset-0 z-20 flex min-h-0 flex-col bg-bg-primary"
        >
          {filesView}
        </div>
      ) : null}

      {/* 终端那一档同样铺在这块滚动区上面，不卸载记录流。 */}
      {terminalOpen && terminalView ? (
        <div
          data-testid="terminal-panel"
          className="absolute inset-0 z-20 flex min-h-0 flex-col bg-bg-primary"
        >
          {typeof terminalView === 'function'
            ? terminalView({
                counts,
                switchToTalk: () => {
                  setWatcherOpen(false);
                  setLens(counts.talk > 0 ? 'talk' : 'all');
                  onFilesOpenChange?.(false);
                  onTerminalOpenChange?.(false);
                },
              })
            : terminalView}
        </div>
      ) : null}
      </div>

      {/* 圈中一段文字之后冒出来的「引用」按钮，以及短选区的同字标绿。
          它挂在滚动容器外面：摆在里面会被 `overflow-y-auto` 裁掉一半。 */}
      {onQuote ? (
        <SelectionQuote
          containerRef={scrollRef}
          sessionId={sessionId}
          onQuote={onQuote}
          onStack={onStack}
          onBranch={onBranch}
          onPreview={preview ? (path, size) => setPeek({ path, size }) : undefined}
        />
      ) : null}

      {/* 浮开的那一份统一走 FileViewer（固定比例大视野、预览/内容/改动切换、行级批注与打包回填）。 */}
      {peek ? (
        (() => {
          const baseList = sessionFiles ?? [];
          const foundIdx = baseList.findIndex((f) => f.path === peek.path);
          const viewerFiles: SessionFileRow[] =
            foundIdx >= 0
              ? baseList
              : [{ path: peek.path, action: 'modified', count: 1, first_seq: 0 }, ...baseList];
          const viewerIdx = foundIdx >= 0 ? foundIdx : 0;
          return (
            <FileViewer
              sessionId={sessionId ?? ''}
              files={viewerFiles}
              index={viewerIdx}
              line={peek.line}
              initialMode={peek.mode}
              onClose={() => setPeek(null)}
              onStep={(delta) => {
                const total = viewerFiles.length;
                if (!total) return;
                const nextIdx = (viewerIdx + delta + total) % total;
                const nextFile = viewerFiles[nextIdx];
                if (nextFile) setPeek({ path: nextFile.path, size: null });
              }}
              onReveal={(p) => {
                if (onRevealFile) onRevealFile(p);
                else void revealPath(p).catch(() => {});
              }}
              onPackPrompt={onPackPrompt}
              onSendFileEdit={onSendFileEdit}
            />
          );
        })()
      ) : null}

      {branchMenu ? (
        <div
          ref={branchMenuEl}
          role="menu"
          data-testid="branch-mark-menu"
          style={{ left: branchMenu.x, top: branchMenu.y + 6 }}
          className="fixed z-30 flex min-w-[132px] flex-col rounded-[8px] border border-border-color bg-bg-card py-1 shadow-lg"
        >
          {onOpenBranch && branchMenu.mark.child_session_id ? (
            <button
              type="button"
              role="menuitem"
              data-testid="branch-mark-open"
              onClick={() => {
                const child = branchMenu.mark.child_session_id as string;
                setBranchMenu(null);
                onOpenBranch(child);
              }}
              className="flex items-center gap-2 px-3 py-1 text-left text-[12px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
            >
              <ExternalLink size={12} />
              {t('workbench.branch.menuOpen')}
            </button>
          ) : null}
          {onCloseBranch ? (
            <button
              type="button"
              role="menuitem"
              data-testid="branch-mark-close"
              onClick={() => {
                const mark = branchMenu.mark;
                setBranchMenu(null);
                onCloseBranch(mark);
              }}
              className="flex items-center gap-2 px-3 py-1 text-left text-[12px] text-text-secondary hover:bg-bg-hover hover:text-text-primary"
            >
              <CheckCheck size={12} />
              {t('workbench.branch.menuClose')}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
