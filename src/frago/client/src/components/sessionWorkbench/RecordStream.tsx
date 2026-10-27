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
import { CheckCheck, ChevronDown, ChevronRight, ExternalLink, Inbox, Loader2 } from 'lucide-react';
import { DecisionCard } from './DecisionCard';
import RecordCard, {
  KIND_GROUP,
  SystemRun,
  ToolRun,
  formatClock,
  formatDuration,
  previewArgs,
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
import type { SessionFileRow } from '@/types/api';
import { FileLinkContext, type FileLinkTarget } from '@/components/ui/MarkdownContent';
import type { LocateState } from './StackPanel';
import type { ComposerUsage } from './Composer';
import type { WorkbenchMark } from '@/hooks/useSessionMarks';
import SendProgress from './SendProgress';
import StreamMinimap from './StreamMinimap';
import { SEG_GROUP, SEG_ITEM, SEG_OFF, SEG_ON, SEG_TIGHT } from './seg';
import {
  AGENT_ACTIVITY,
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
import type { SessionObserverView } from '@/hooks/useSessionObserver';

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
 */
export function withTurnDecisionCards(records: WorkbenchRecord[]): WorkbenchRecord[] {
  const delegateToolIndices = new Set<number>();
  const attachToAgentSay = new Map<number, string>();
  const attachImagesToAgentSay = new Map<number, string[]>();

  let turnToolIndices: number[] = [];
  let turnToolBody = '';
  let turnImageIndices: number[] = [];
  let turnImageBodies: string[] = [];
  let turnInlineCardAgentIndices: number[] = [];
  let lastAgentSayIdx = -1;

  const flushTurn = () => {
    if (turnToolIndices.length) {
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
    } else if (turnInlineCardAgentIndices.length > 1) {
      for (let k = 0; k < turnInlineCardAgentIndices.length - 1; k += 1) {
        delegateToolIndices.add(turnInlineCardAgentIndices[k]);
      }
    }
    if (turnImageIndices.length && lastAgentSayIdx >= 0) {
      for (const idx of turnImageIndices) delegateToolIndices.add(idx);
      attachImagesToAgentSay.set(lastAgentSayIdx, [...turnImageBodies]);
    }
    turnToolIndices = [];
    turnToolBody = '';
    turnImageIndices = [];
    turnImageBodies = [];
    turnInlineCardAgentIndices = [];
    lastAgentSayIdx = -1;
  };

  for (let i = 0; i < records.length; i += 1) {
    const r = records[i];
    if (!r.agent_path.length) {
      const isHumanTurnBoundary =
        r.kind === 'user.say' ||
        (r.kind === 'context.inject' && r.payload.channel === 'queued_command');
      if (isHumanTurnBoundary) {
        flushTurn();
        continue;
      }
      if (r.kind === 'agent.say') {
        lastAgentSayIdx = i;
        const text = typeof r.payload.text === 'string' ? r.payload.text : '';
        if (text && (splitTrailingBlock(text) || parseUiComponentOutput(text)?.ok)) {
          turnInlineCardAgentIndices.push(i);
        }
        continue;
      }
      if (r.kind === 'tool.result' && r.payload.status !== 'error') {
        const body = typeof r.payload.body === 'string' ? r.payload.body : '';
        if (body) {
          const uiCard = parseUiComponentOutput(body);
          if (uiCard && uiCard.ok) {
            turnToolIndices.push(i);
            turnToolBody = body;
          }
          const imageGrids = parseAllImageGridOutputs(body);
          if (imageGrids.length > 0) {
            turnImageIndices.push(i);
            turnImageBodies.push(body);
          }
        }
      }
    }
  }
  flushTurn();

  if (!delegateToolIndices.size && !attachToAgentSay.size && !attachImagesToAgentSay.size) {
    return records;
  }

  return records.map((r, idx) => {
    if (delegateToolIndices.has(idx)) {
      return r.payload.ui_component_delegated === true
        ? r
        : { ...r, payload: { ...r.payload, ui_component_delegated: true } };
    }
    const attached = attachToAgentSay.get(idx);
    const attachedImages = attachImagesToAgentSay.get(idx);
    if (attached !== undefined || attachedImages !== undefined) {
      const nextPayload: Record<string, unknown> = { ...r.payload };
      if (attached !== undefined) {
        nextPayload.ui_component = attached;
      }
      if (attachedImages !== undefined) {
        nextPayload.ui_image_grids = attachedImages;
      }
      return { ...r, payload: nextPayload };
    }
    return r;
  });
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
  return withTurnDecisionCards(queued);
}

/**
 * 「对话」那一档实际摆出来的记录：对话本身，外加捎带的用量刻度。
 *
 * 当轮 `frago ask` 产出的交互卡已由 `withTurnDecisionCards` 挂载到当轮最后一条 `agent.say`
 * （收尾消息）的正文下方；仅当某轮完全没有 `agent.say` 时，才捎带未移交的 `tool.result` 兜底显示。
 */
export function talkView(records: WorkbenchRecord[]): WorkbenchRecord[] {
  const normalized = withTurnDecisionCards(records);
  const out: WorkbenchRecord[] = [];
  let tick: WorkbenchRecord | null = null;
  for (let i = 0; i < normalized.length; i += 1) {
    const record = normalized[i];
    if (record.kind === 'usage.tick') {
      tick = record;
      continue;
    }
    if (
      record.kind === 'tool.result' &&
      !record.agent_path.length &&
      record.payload.status !== 'error' &&
      record.payload.ui_component_delegated !== true
    ) {
      const body = typeof record.payload.body === 'string' ? record.payload.body : '';
      const uiCard = body ? parseUiComponentOutput(body) : null;
      const imageGrids = body ? parseAllImageGridOutputs(body) : [];
      if ((uiCard && uiCard.ok) || imageGrids.length > 0) {
        if (tick) out.push(tick);
        tick = null;
        out.push(record);
        continue;
      }
    }
    if (lensOf(record) !== 'talk') continue;
    if (tick) out.push(tick);
    tick = null;
    out.push(record);
  }
  if (tick) out.push(tick);
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
  let tick: WorkbenchRecord | null = null;
  let pendingTools = 0;
  let pendingThinking = 0;
  let pendingRecords: WorkbenchRecord[] = [];

  const flushTick = () => {
    if (tick) {
      out.push({ kind: 'record', record: tick });
      tick = null;
    }
  };

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
      tick = record;
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
      record.payload.status !== 'error' &&
      record.payload.ui_component_delegated !== true
    ) {
      const body = typeof record.payload.body === 'string' ? record.payload.body : '';
      const uiCard = body ? parseUiComponentOutput(body) : null;
      const imageGrids = body ? parseAllImageGridOutputs(body) : [];
      if ((uiCard && uiCard.ok) || imageGrids.length > 0) {
        flushTick();
        flushPreResponse(record.group_id);
        out.push({ kind: 'record', record });
        continue;
      }
    }
    if (lensOf(record) !== 'talk') continue;
    flushTick();
    flushPreResponse(record.kind === 'agent.say' ? record.group_id : null);
    out.push({ kind: 'record', record });
  }
  flushPreResponse(null);
  flushTick();
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
    const text = typeof r.payload.thinking === 'string' ? r.payload.thinking : '';
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
      return t('workbench.progress.doingError');
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
/** 离底部多近算「人就在底部」，手动滚到这里立即重新武装自动滚动。 */
const AT_BOTTOM_PX = 60;
/** 手动输入事件后多久之内的滚动算是人滚的。程序滚动不在这个窗口里。 */
const MANUAL_INTENT_MS = 400;
/** 解除后多久没再手动滚动，新条目进来时自动滚动复活。 */
const REARM_AFTER_MS = 10_000;
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
}

interface WatcherSlice {
  id: string;
  at: number | null;
  phaseGoal: string | null;
  doing: string | null;
  findings: string[];
  decision: string | null;
  summary: string;
  records: WorkbenchRecord[];
  decisionCards: { recordId: string; block: DecisionBlock }[];
}

function cleanGoalText(raw?: string | null): string | null {
  if (typeof raw !== 'string') return null;
  const trimmed = raw.trim();
  if (!trimmed || trimmed.startsWith('【answer】')) return null;
  return trimmed;
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
  tail: { kind: 'now' | 'output'; text: string } | null | undefined,
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
  } else if (tailKind === 'output' && tailText) {
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

/** 悬停说明与水位读数里 k 为单位的写法：312k。 */
function formatK(n: number): string {
  return `${Math.round(n / 1000)}k`;
}

/**
 * 本场累计到七位数，用 k 写成一串谁读不出量级，收一档到 M：30.1M。
 * 百万以下还是 k，跟上下文用同一把尺子。
 */
function formatM(n: number): string {
  if (n < 1_000_000) return formatK(n);
  return `${(n / 1_000_000).toFixed(1)}M`;
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
  filesView,
  filesOpen = false,
  onFilesOpenChange,
  filesCount = null,
  filesPending = false,
  usage = null,
  sessionFiles = null,
  onRevealFile,
  onPackPrompt,
  onSendFileEdit,
  observer = null,
}: RecordStreamProps) {
  const { t } = useTranslation();
  /** 档位条右侧那几个数拼成一行。取不到的不进串，中间不留孤零零的分隔点。 */
  const usageReadout = useMemo(() => {
    if (!usage) return '';
    const parts: string[] = [];
    if (usage.model) parts.push(usage.model);
    if (usage.context !== null) {
      parts.push(`${t('workbench.record.usage.context')} ${formatK(usage.context)}`);
    }
    if (usage.total !== null) {
      parts.push(`${t('workbench.record.usage.total')} ${formatM(usage.total)}`);
    }
    return parts.join(' · ');
  }, [usage, t]);
  // 打开就落在**对话**上。整场记录里对话只占几十分之一，默认铺开全部等于让人自己
  // 在工具与记账里翻对话；要看全部，顶上那排镜头点一下就是。
  const [lens, setLens] = useState<StreamLens>('talk');
  const [watcherOpen, setWatcherOpen] = useState(false);
  const [expandedWatcherIds, setExpandedWatcherIds] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setExpandedWatcherIds({});
  }, [sessionId]);
  /** 圈中的那段是一条真文件、或点中回复里的本地文件链接时，就地浮开的那一份。 */
  const [peek, setPeek] = useState<{ path: string; size: number | null; line?: string } | null>(
    null
  );
  const handleFileLink = useCallback(
    (target: FileLinkTarget) => {
      if (preview) setPeek({ path: target.path, size: null, line: target.line });
    },
    [preview]
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
    for (const record of resolved) tally[lensOf(record)] += 1;
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

  const watcherCount = useMemo(() => {
    if (!resolved.length) return 0;
    const state = observer?.state ?? null;
    const runs = state?.runs ?? [];
    if (runs.length > 0) return runs.length;
    const hasFallback = Boolean(
      cleanGoalText(state?.anchor) ||
        state?.happened?.length ||
        state?.tail?.text ||
        state?.decision
    );
    return hasFallback ? 1 : 0;
  }, [resolved.length, observer?.state]);

  const { watcherSlices, unsummarizedTailRecords } = useMemo<{
    watcherSlices: WatcherSlice[];
    unsummarizedTailRecords: WorkbenchRecord[];
  }>(() => {
    if (!watcherOpen || !resolved.length) return { watcherSlices: [], unsummarizedTailRecords: [] };
    const state = observer?.state ?? null;
    const runs = state?.runs ?? [];
    let firstHumanGoal: string | null = null;
    for (const r of resolved) {
      if (r.kind === 'user.say' && !r.payload.is_tool_result) {
        const g = cleanGoalText(typeof r.payload.text === 'string' ? r.payload.text : null);
        if (g) {
          firstHumanGoal = g;
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
          firstHumanGoal;
        return {
          id: run.id || `run-${idx + 1}`,
          at: run.at ?? state?.updated_at ?? sliceRecords[sliceRecords.length - 1]?.ts ?? null,
          phaseGoal,
          doing: parts.doing,
          findings: parts.findings,
          decision: parts.decision,
          summary: summaryParts.join('\n') || t('workbench.stream.watcherEmptySummary'),
          records: sliceRecords,
          decisionCards: sliceCards,
        };
      });
      const tailRecords = resolved.filter((r) => r.seq >= maxCursorTo);
      return { watcherSlices: slices, unsummarizedTailRecords: tailRecords };
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
            at: state?.updated_at ?? resolved[resolved.length - 1]?.ts ?? null,
            phaseGoal:
              cleanGoalText(state?.phase_goal) ||
              safeAnchor ||
              firstHumanGoal,
            doing: fallbackThree.doing,
            findings: fallbackThree.findings,
            decision: fallbackThree.decision,
            summary: fallbackParts.join('\n'),
            records: resolved,
            decisionCards: extractSliceDecisionCards(resolved),
          },
        ],
        unsummarizedTailRecords: [],
      };
    }
    return {
      watcherSlices: [],
      unsummarizedTailRecords: resolved,
    };
  }, [watcherOpen, resolved, observer?.state, t]);

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
      if (tr.recordId) return tr;
    }
    return null;
  }, [trails]);
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
      <span className="shrink-0 font-mono text-text-dim">
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
        data-record-kind={record.kind}
        {...{ [RECORD_BODY_ATTR]: '' }}
        className="min-w-0"
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
          className="flex min-w-0 flex-wrap items-center gap-2 px-3 py-1 font-mono text-[13px] text-text-muted"
        >
          {parts.map((part, idx) => (
            <Fragment key={idx}>
              {idx > 0 ? <span aria-hidden className="text-text-dim">·</span> : null}
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
  /** 自动滚动是否武装。开一场新会话时武装，人手动离开底部解除。 */
  const followArmed = useRef(true);
  /** 最后一次人手动滚动的时刻。十秒复活的计时起点。 */
  const lastManualScrollAt = useRef(0);
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

  // 换会话：一切归零，默认重新武装——新打开的会话就该落在最新内容上。
  // 必须是布局效应且声明在记录流效应之前：挂载时普通效应跑在布局效应之后，会把记录流
  // 效应刚记下的首尾编号抹掉，下一帧追加就被误判成初装，视口不由分说沉到底。
  useLayoutEffect(() => {
    followArmed.current = true;
    lastManualScrollAt.current = 0;
    manualIntentUntil.current = 0;
    programmaticUntil.current = 0;
    anchor.current = null;
    prevEnds.current = { first: null, last: null };
    olderArmed.current = true;
  }, [sessionId]);

  // 记录流变化的三种形态：前插钉住视口，追加按状态机走，整流替换与初装沉底。
  useLayoutEffect(() => {
    if (!records.length) {
      prevEnds.current = { first: null, last: null };
      return;
    }
    const first = records[0].id;
    const last = records[records.length - 1].id;
    const prev = prevEnds.current;

    if (prev.first !== null && first !== prev.first && last === prev.last) {
      // 前插旧页：把视口钉回原来那张卡，NEVER 让人觉得页面自己跳了。
      const el = scrollRef.current;
      if (el && anchor.current) {
        el.scrollTop = el.scrollHeight - anchor.current.height + anchor.current.top;
      }
    } else if (prev.first === null) {
      // 初次装载：沉底并武装。
      scrollToBottom();
      followArmed.current = true;
    } else if (first === prev.first && last !== prev.last) {
      // 尾部追加：武装着就跟到底；解除满十秒也复活。
      if (
        followArmed.current ||
        Date.now() - lastManualScrollAt.current > REARM_AFTER_MS
      ) {
        // 近处滑过去，远处直接落位——见 SMOOTH_MAX_PX。
        const el = scrollRef.current;
        const gap = el ? el.scrollHeight - el.scrollTop - el.clientHeight : 0;
        scrollToBottom(gap <= SMOOTH_MAX_PX ? 'smooth' : 'auto');
        followArmed.current = true;
      }
    } else if (first !== prev.first && last !== prev.last) {
      // 整流替换（重拉）：落在最新内容上并武装。
      scrollToBottom();
      followArmed.current = true;
    }

    prevEnds.current = { first, last };
    anchor.current = null;
  }, [records, scrollToBottom]);

  // 换镜头后落在这一档的最新一条上。不这么做，视口会停在按旧内容算出来的高度上，
  // 换完看到的是半空的一屏。
  useLayoutEffect(() => {
    scrollToBottom();
    followArmed.current = true;
  }, [lens, watcherOpen, scrollToBottom]);

  // "在等 agent 开口"那一条也是内容，它一冒出来就要看得见——跟着的人正是为了看它。
  // 人自己滚上去看别的时不打扰。
  useLayoutEffect(() => {
    if (awaitingAgent && followArmed.current) scrollToBottom('smooth');
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
    el.scrollIntoView?.({ block: 'center', behavior: 'smooth' });
    // 只在点下去那一刻滚一次；镜头换完再来一趟由 lens 变化带起
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollAt, scrollId, lens, filesOpen, watcherOpen]);

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
    if (typeof box.scrollTo === 'function') box.scrollTo({ top, behavior: 'smooth' });
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
  }, [locateAt, records, hasOlder, loadingOlder, visible, lens, filesOpen, watcherOpen]);

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
        noteManualIntent();
      }
    },
    [noteManualIntent]
  );

  const handleScroll = useCallback(
    (e: UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget;
      const now = Date.now();

      // 手动滚动：离开底部就解除自动滚动，回到底部立即重新武装。
      //
      // 程序自己滚出来的那一串**不参与这个判定**：平滑滚动一路经过的中间位置全都不在
      // 底部，落进判定里就会把自动跟随解除掉——人明明没碰过，症状却是「滚着滚着就不跟
      // 了」。到顶取更早那一页的判定不受这条影响：那件事只看位置，不问是谁滚的。
      if (now > programmaticUntil.current && now <= manualIntentUntil.current) {
        lastManualScrollAt.current = now;
        followArmed.current =
          el.scrollHeight - el.scrollTop - el.clientHeight < AT_BOTTOM_PX;
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
      <div className="flex h-full flex-col items-center justify-center gap-3 text-text-muted">
        <Inbox size={44} strokeWidth={1.4} />
        <p className="text-[13px]">{t('workbench.stream.pickSession')}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      {records.length ? (
        <div
          data-testid="stream-lens"
          className="flex shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border-color px-4 py-2"
        >
          {/* 整个左侧区域分为紧贴的 Watcher + 隔离纯文本 Executor + 现有的 All | Talk | ... 菜单 */}
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
            <div className={SEG_GROUP}>
              <button
                type="button"
                data-testid="lens-watcher"
                onClick={() => {
                  setWatcherOpen(true);
                  onFilesOpenChange?.(false);
                }}
                aria-pressed={watcherOpen && !filesOpen}
                className={`${SEG_ITEM} ${SEG_TIGHT} ${watcherOpen && !filesOpen ? SEG_ON : SEG_OFF}`}
              >
                {t('workbench.stream.watcher')}
                <span className="font-mono opacity-60">{watcherCount}</span>
              </button>
            </div>
            <span
              data-testid="lens-executor-label"
              className="shrink-0 select-none whitespace-nowrap px-0.5 text-[12px] font-medium text-text-muted"
            >
              {t('workbench.stream.executor')}
            </span>
            <div className={SEG_GROUP}>
              {LENS_ORDER.map((id) => (
                <Fragment key={id}>
                  {/* 文件那一档排在 System 之前，与原型同一顺序：它与镜头同一排、同一套长相，
                      但它不是镜头——见 `filesView` 那段说明。它**不按条数变灰**：数字还不知道时
                      按灰，人就以为这一场没改过文件。 */}
                  {id === 'system' && filesView ? (
                    <button
                      type="button"
                      data-testid="lens-files"
                      onClick={() => {
                        setWatcherOpen(false);
                        onFilesOpenChange?.(!filesOpen);
                      }}
                      aria-pressed={filesOpen}
                      title={t('workbench.files.lensHint')}
                      className={`${SEG_ITEM} ${SEG_TIGHT} ${filesOpen ? SEG_ON : SEG_OFF}`}
                    >
                      {t('workbench.files.lens')}
                      {typeof filesCount === 'number' ? (
                        <span className="font-mono opacity-60">{filesCount}</span>
                      ) : filesPending ? (
                        /* 还在数：写个省略号占住那个位置。空着一眼看去就是「这个会话没动过文件」，
                           而那正是这颗按钮**不该**说的事。 */
                        <span data-testid="lens-files-pending" className="font-mono opacity-60">
                          …
                        </span>
                      ) : null}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    /* 点某一档镜头就是回记录流：人手上还开着文件清单或 Watcher 时，他这一下是在说「我要看记录」。
                       不跟着切回来，点了没反应，像坏了。 */
                    onClick={() => {
                      setWatcherOpen(false);
                      setLens(id);
                      onFilesOpenChange?.(false);
                    }}
                    aria-pressed={lens === id && !filesOpen && !watcherOpen}
                    data-testid={`lens-${id}`}
                    /* 「Hooks」是缩写（半宽的 Teams 栏里全称挤成两行），悬停给全称 */
                    title={id === 'hook' ? t('workbench.stream.lensHookFull') : undefined}
                    disabled={counts[id] === 0}
                    className={`${SEG_ITEM} ${SEG_TIGHT} ${lens === id && !filesOpen && !watcherOpen ? SEG_ON : SEG_OFF}`}
                  >
                    {t(LENS_LABEL_KEY[id])}
                    <span className="font-mono opacity-60">{counts[id]}</span>
                  </button>
                </Fragment>
              ))}
            </div>
          </div>
          {usageReadout ? (
            <span
              data-testid="stream-lens-usage"
              title={t('workbench.composer.usageHint')}
              className="min-w-0 max-w-full truncate whitespace-nowrap font-mono text-[11px] text-text-dim"
            >
              {usageReadout}
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
        /* 滚动容器的内距契约：左右各 16（照原型），上 16 下 40。底下比上面厚，是因为滚到
           底那一刻最后一条不该被硬切在容器边框上，而输入框就压在下面。挂着缩略滚动条时
           右边多让出它那一条（那条 12px 宽的滚动条压在离右边 12px 处，占掉右边 24 以内的
           地方），窄窗下正文不会钻到它底下。 */
        className={`min-h-0 flex-1 overflow-y-auto pb-10 pl-4 pt-4 ${showMinimap ? 'record-stream-no-bar pr-6' : 'pr-4'}`}
        data-testid="record-stream-scroll"
      >
        <FileLinkContext.Provider value={preview ? handleFileLink : null}>
        <div className="flex w-full min-w-0 flex-col gap-4">
          {loadingOlder ? (
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
            <p className="py-10 text-center text-[12px] text-text-muted">
              {t('workbench.stream.lensEmpty')}
            </p>
          ) : null}

          {!records.length && !loading && !error ? (
            <div className="flex flex-col items-center gap-3 py-16 text-text-muted">
              <Inbox size={44} strokeWidth={1.4} />
              <p className="text-[13px]">{t('workbench.stream.emptySession')}</p>
              <p className="text-[12px]">{t('workbench.stream.emptySessionHint')}</p>
            </div>
          ) : null}

          {watcherOpen ? (
            <div
              data-testid="watcher-view"
              className="flex min-w-0 flex-col divide-y divide-border-color"
            >
              {watcherSlices.map((slice, idx) => {
                const isExpanded = Boolean(expandedWatcherIds[slice.id]);
                const sliceGroups = isExpanded ? groupSegments(buildTalkSegments(slice.records)) : [];
                const sliceDecisionCards = slice.decisionCards;
                let promptCount = 0;
                let toolCallsCount = 0;
                let thinkingCount = 0;
                let replyCount = 0;
                for (const r of slice.records) {
                  if (
                    r.kind === 'user.say' ||
                    (r.kind === 'context.inject' && r.payload.channel === 'queued_command')
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
                const metaCounts: string[] = [];
                if (promptCount > 0) {
                  metaCounts.push(
                    t('workbench.stream.watcherTalkPromptCount', { count: promptCount })
                  );
                }
                if (toolCallsCount > 0) {
                  metaCounts.push(
                    t('workbench.stream.preResponseToolCalls', { count: toolCallsCount })
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
                const clock = slice.at ? formatClock(slice.at) : '';
                const goalLines = splitWatcherLines(slice.phaseGoal);
                const doingLines = splitWatcherLines(slice.doing);
                const findingLines = splitWatcherLines(slice.findings);
                const decisionLines = splitWatcherLines(slice.decision);
                return (
                  <section
                    key={slice.id}
                    data-testid="watcher-item"
                    className="flex min-w-0 flex-col gap-4 py-5 first:pt-1 last:pb-1"
                  >
                    <header className="flex flex-wrap items-center gap-x-2.5 gap-y-1 font-mono text-[12px] text-text-muted">
                      <span className="font-semibold text-text-secondary">#{idx + 1}</span>
                      {clock ? <span>{clock}</span> : null}
                    </header>
                    <div
                      data-testid="watcher-summary"
                      className="flex max-w-[78ch] min-w-0 flex-col gap-4 break-words text-[16px] leading-[1.72] text-text-primary"
                    >
                      {goalLines.length > 0 ? (
                        <div
                          data-testid="watcher-phase-goal"
                          className="flex min-w-0 flex-col gap-1.5"
                        >
                          <div
                            data-testid="watcher-phase-goal-label"
                            className="text-[13px] font-semibold tracking-wide text-text-secondary"
                          >
                            {t('workbench.stream.watcherPhaseGoalLabel')}
                          </div>
                          <div className="flex min-w-0 flex-col gap-1.5 font-medium text-text-primary">
                            {goalLines.map((line, lIdx) => (
                              <div
                                key={lIdx}
                                data-testid="watcher-phase-goal-line"
                                className="flex min-w-0 items-start gap-2.5 leading-[1.68]"
                              >
                                {goalLines.length > 1 ? (
                                  <span
                                    aria-hidden
                                    className="mt-[10px] h-1.5 w-1.5 shrink-0 rounded-full bg-text-muted/60"
                                  />
                                ) : null}
                                <span className="min-w-0 flex-1">{line}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {doingLines.length > 0 || findingLines.length > 0 || decisionLines.length > 0 ? (
                        <>
                          {doingLines.length > 0 ? (
                            <div
                              data-testid="watcher-part-doing"
                              className="flex min-w-0 flex-col gap-1.5"
                            >
                              <div
                                data-testid="watcher-part-doing-label"
                                className="text-[13px] font-semibold tracking-wide text-text-secondary"
                              >
                                {t('workbench.stream.watcherPartDoing')}
                              </div>
                              <div className="flex min-w-0 flex-col gap-1.5">
                                {doingLines.map((line, lIdx) => (
                                  <div
                                    key={lIdx}
                                    data-testid="watcher-part-doing-line"
                                    className="flex min-w-0 items-start gap-2.5 leading-[1.72]"
                                  >
                                    {doingLines.length > 1 ? (
                                      <span
                                        aria-hidden
                                        className="mt-[10px] h-1.5 w-1.5 shrink-0 rounded-full bg-text-muted/60"
                                      />
                                    ) : null}
                                    <span className="min-w-0 flex-1">{line}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          {findingLines.length > 0 ? (
                            <div
                              data-testid="watcher-part-findings"
                              className="flex min-w-0 flex-col gap-1.5"
                            >
                              <div
                                data-testid="watcher-part-findings-label"
                                className="text-[13px] font-semibold tracking-wide text-text-secondary"
                              >
                                {t('workbench.stream.watcherPartFindings')}
                              </div>
                              <div className="flex min-w-0 flex-col gap-1.5">
                                {findingLines.map((line, lIdx) => (
                                  <div
                                    key={lIdx}
                                    data-testid="watcher-part-findings-line"
                                    className="flex min-w-0 items-start gap-2.5 leading-[1.72]"
                                  >
                                    {findingLines.length > 1 ? (
                                      <span
                                        aria-hidden
                                        className="mt-[10px] h-1.5 w-1.5 shrink-0 rounded-full bg-text-muted/60"
                                      />
                                    ) : null}
                                    <span className="min-w-0 flex-1">{line}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          {decisionLines.length > 0 ? (
                            <div
                              data-testid="watcher-part-decision"
                              className="flex min-w-0 flex-col gap-1.5"
                            >
                              <div
                                data-testid="watcher-part-decision-label"
                                className="text-[13px] font-semibold tracking-wide text-accent-primary"
                              >
                                {t('workbench.stream.watcherPartDecision')}
                              </div>
                              <div className="flex min-w-0 flex-col gap-1.5">
                                {decisionLines.map((line, lIdx) => (
                                  <div
                                    key={lIdx}
                                    data-testid="watcher-part-decision-line"
                                    className="flex min-w-0 items-start gap-2.5 leading-[1.72]"
                                  >
                                    {decisionLines.length > 1 ? (
                                      <span
                                        aria-hidden
                                        className="mt-[10px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent-primary/70"
                                      />
                                    ) : null}
                                    <span className="min-w-0 flex-1">{line}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <span className="whitespace-pre-wrap">{slice.summary}</span>
                      )}
                    </div>
                    <div className="min-w-0 rounded-[8px] bg-bg-subtle px-3 py-2">
                      <button
                        type="button"
                        data-testid={`watcher-talk-toggle-${idx}`}
                        aria-expanded={isExpanded}
                        onClick={() =>
                          setExpandedWatcherIds((prev) => ({
                            ...prev,
                            [slice.id]: !prev[slice.id],
                          }))
                        }
                        className="flex w-full min-w-0 flex-wrap items-center gap-2 text-left text-[13px] text-text-secondary hover:text-text-primary"
                      >
                        {isExpanded ? (
                          <ChevronDown size={14} className="shrink-0 text-text-muted" />
                        ) : (
                          <ChevronRight size={14} className="shrink-0 text-text-muted" />
                        )}
                        <span className="font-semibold text-text-primary">
                          {t('workbench.stream.lens.talk')}
                        </span>
                        <span className="font-mono text-[12px] text-text-muted">
                          {metaCounts.length
                            ? metaCounts.join(' · ')
                            : t('workbench.stream.watcherTalkEmpty')}
                        </span>
                      </button>
                      {isExpanded ? (
                        <div
                          data-testid={`watcher-talk-body-${idx}`}
                          className="mt-3 flex min-w-0 flex-col gap-3 pt-1"
                        >
                          {sliceGroups.map((group, gIdx) =>
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
                          )}
                        </div>
                      ) : null}
                    </div>
                    {!isExpanded && sliceDecisionCards.length > 0 ? (
                      <div data-testid="watcher-decision-cards" className="flex min-w-0 flex-col gap-2">
                        {sliceDecisionCards.map((dc) => (
                          <DecisionCard key={dc.recordId} block={dc.block} recordId={dc.recordId} />
                        ))}
                      </div>
                    ) : null}
                  </section>
                );
              })}
              {(() => {
                if (!unsummarizedTailRecords.length) return null;
                const tailSegments = buildTalkSegments(unsummarizedTailRecords);
                const tailGroups = groupSegments(tailSegments);
                if (!tailGroups.length) return null;
                return (
                  <section
                    data-testid="watcher-unsummarized-tail"
                    className="flex min-w-0 flex-col gap-3 py-4 first:pt-1 last:pb-1"
                  >
                    {tailGroups.map((group, gIdx) =>
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
                  </section>
                );
              })()}
            </div>
          ) : (
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
          {loading && !records.length && !error ? (
            <div
              data-testid="record-stream-loading"
              className="flex flex-col items-center gap-3 py-16 text-text-muted"
            >
              <Loader2 size={28} className="animate-spin" />
              <p className="text-[13px]">{t('workbench.stream.loading')}</p>
            </div>
          ) : null}

          {loading && records.length ? (
            <p className="flex items-center justify-center gap-2 py-4 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              {t('workbench.stream.loading')}
            </p>
          ) : null}

          {/* 「Agent on it」紧贴在那句话下面。那句话在当前镜头里看不见时（切到了工具档），
              退到流的末尾，安静期照样有东西撑着。 */}
          {activeTrail && !activeShown ? agentOnIt : null}
        </div>
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
