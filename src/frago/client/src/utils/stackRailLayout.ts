/**
 * stackRailLayout — 方案 4A 滚动条暂存轨的几何排版与过程旁白过滤算法。
 *
 * 1. `layoutStackLabels`：将轨道内的活跃暂存标注按 rawY 排序分组、近邻散开或归并成
 *    聚合胶囊（×N），并对前驱/后继碰撞做向上/向下消除，输出不重叠的标签实体列表。
 * 2. `isResponseAt` / `computeFinalAgentSayIds`：在 `resolved` 全量记录流上区分
 *    「触发 tool.call 之前的过程旁白」与「轮次最终回复」，使缩略导航条只画真实发言与
 *    最终回复，避免中间旁白碎片刷屏。
 */

import type { WorkbenchMark } from '@/types/api';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

export const STACK_LABEL_H = 22;
export const STACK_CLUSTER_H = 24;
export const STACK_MIN_STEP = 26;
export const STACK_MAX_OFFSET = 36;

export type StackStatus = 'pending' | 'draft' | 'used';

export interface StackRailItem {
  mark: WorkbenchMark;
  status: 'pending' | 'draft';
  rawY: number;
}

export type StackRailEntity =
  | {
      kind: 'single';
      id: string;
      item: StackRailItem;
      dispY: number;
      h: number;
    }
  | {
      kind: 'cluster';
      id: string;
      items: StackRailItem[];
      rawY: number;
      dispY: number;
      h: number;
      prefItem: StackRailItem;
      allDraft: boolean;
    };

export function stackStatusOf(
  mark: WorkbenchMark,
  inDraftMarkIds: ReadonlySet<string>
): StackStatus {
  if (mark.used) return 'used';
  if (inDraftMarkIds.has(mark.id)) return 'draft';
  return 'pending';
}

export function cleanQuoteText(raw: string): string {
  return String(raw || '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function stackLabelText(mark: Pick<WorkbenchMark, 'note' | 'text'>): string {
  const note = (mark.note ?? '').trim();
  return note || cleanQuoteText(mark.text);
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function makeClusterEntity(
  items: StackRailItem[],
  topReserve: number,
  railH: number
): Extract<StackRailEntity, { kind: 'cluster' }> {
  const cy = items.reduce((sum, it) => sum + it.rawY, 0) / items.length;
  const maxC = Math.max(topReserve, railH - 8 - STACK_CLUSTER_H);
  const prefItem = items.find((it) => it.status === 'pending') ?? items[0];
  const allDraft = items.every((it) => it.status === 'draft');
  return {
    kind: 'cluster',
    id: items.map((it) => it.mark.id).join('+'),
    items,
    rawY: cy,
    dispY: clamp(cy - STACK_CLUSTER_H / 2, topReserve, maxC),
    h: STACK_CLUSTER_H,
    prefItem,
    allDraft,
  };
}

/**
 * 将已按轨道垂直像素定位的暂存项编排成不重叠的标签/聚合实体集合。
 */
export function layoutStackLabels(
  items: StackRailItem[],
  railH: number,
  topReserve = 4
): StackRailEntity[] {
  if (!items.length || railH <= 0) return [];
  const sorted = [...items].sort((a, b) => a.rawY - b.rawY);
  const maxY = Math.max(topReserve, railH - 8 - STACK_LABEL_H);

  // 1) 按垂直间距 < 26px 聚合近邻组
  const groups: StackRailItem[][] = [[sorted[0]]];
  for (let i = 1; i < sorted.length; i += 1) {
    const prevGrp = groups[groups.length - 1];
    const prev = prevGrp[prevGrp.length - 1];
    if (sorted[i].rawY - prev.rawY < STACK_MIN_STEP) {
      prevGrp.push(sorted[i]);
    } else {
      groups.push([sorted[i]]);
    }
  }

  // 2) 组内散开（<= 3 且最大偏移 <= 36px）或归并成聚合胶囊
  const entities: StackRailEntity[] = [];
  for (const grp of groups) {
    if (grp.length === 1) {
      const it = grp[0];
      entities.push({
        kind: 'single',
        id: it.mark.id,
        item: it,
        dispY: clamp(it.rawY - STACK_LABEL_H / 2, topReserve, maxY),
        h: STACK_LABEL_H,
      });
      continue;
    }

    if (grp.length <= 3) {
      const cy = grp.reduce((sum, it) => sum + it.rawY, 0) / grp.length;
      const startTop = cy - ((grp.length - 1) * STACK_MIN_STEP) / 2 - STACK_LABEL_H / 2;
      let maxOffset = 0;
      const spread: StackRailEntity[] = grp.map((it, idx) => {
        const dy = clamp(startTop + idx * STACK_MIN_STEP, topReserve, maxY);
        const offset = Math.abs(dy + STACK_LABEL_H / 2 - it.rawY);
        if (offset > maxOffset) maxOffset = offset;
        return {
          kind: 'single',
          id: it.mark.id,
          item: it,
          dispY: dy,
          h: STACK_LABEL_H,
        };
      });
      // 确保散开后各自不重叠
      let spreadDistinct = true;
      for (let k = 1; k < spread.length; k += 1) {
        if (spread[k].dispY < spread[k - 1].dispY + spread[k - 1].h + 2) {
          spreadDistinct = false;
          break;
        }
      }
      if (maxOffset <= STACK_MAX_OFFSET && spreadDistinct) {
        entities.push(...spread);
      } else {
        entities.push(makeClusterEntity(grp, topReserve, railH));
      }
    } else {
      entities.push(makeClusterEntity(grp, topReserve, railH));
    }
  }

  // 3) 跨组前向防碰撞：向下微调或合并为相邻 cluster
  for (let i = 1; i < entities.length; i += 1) {
    const prev = entities[i - 1];
    const cur = entities[i];
    const needTop = prev.dispY + prev.h + 4;
    if (cur.dispY < needTop) {
      const maxCur = Math.max(topReserve, railH - 8 - cur.h);
      if (needTop <= maxCur) {
        cur.dispY = needTop;
      } else {
        const mergedItems = [
          ...(prev.kind === 'cluster' ? prev.items : [prev.item]),
          ...(cur.kind === 'cluster' ? cur.items : [cur.item]),
        ];
        entities.splice(i - 1, 2, makeClusterEntity(mergedItems, topReserve, railH));
        i -= 1;
      }
    }
  }

  return entities;
}

/**
 * 判断 `records[idx]` 这条 `agent.say` 是否是向人类汇报的正式答复（而非紧邻下一次 tool.call 前的过程旁白）。
 * 必须在尚未过滤 tool.call 的 `resolved` 全量记录序列上判定！
 */
export function isResponseAt(records: readonly WorkbenchRecord[], idx: number): boolean {
  const rec = records[idx];
  if (!rec || rec.kind !== 'agent.say') return false;
  for (let j = idx + 1; j < records.length; j += 1) {
    const next = records[j];
    if (
      next.kind === 'user.say' ||
      next.kind === 'call.envelope' ||
      (next.kind === 'context.inject' &&
        (next.payload.channel === 'queued_command' ||
          next.payload.source === 'task-notification'))
    ) {
      return true;
    }
    if (next.kind === 'tool.call') return false;
  }
  return true;
}

/**
 * 在完整 `resolved` 流上计算应纳入缩略导航条的正式 `agent.say` 记录编号集合。
 */
export function computeFinalAgentSayIds(records: readonly WorkbenchRecord[]): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < records.length; i += 1) {
    if (isResponseAt(records, i)) out.add(records[i].id);
  }
  return out;
}
