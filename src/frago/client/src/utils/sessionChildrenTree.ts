import type {
  SessionChildProcess,
  SessionChildSession,
  SessionChildrenResponse,
} from '@/types/api';

export interface ProgressBadgeInfo {
  activeCount: number;
  runningCount: number;
  deliveringCount: number;
  badgeText: string | null;
  tone: 'running' | 'delivering' | 'none';
  externalOnlyDot: boolean;
}

export interface ChildSessionTreeNode {
  session: SessionChildSession;
  treeDepth: number;
  /** 视觉缩进深度在第 4 层封顶（5~8 层与第 4 层对齐并展示 L5..L8 标签）。 */
  visualDepth: number;
  isPriority: boolean;
  subtreeHasActiveOrError: boolean;
  defaultExpanded: boolean;
  totalDescendants: number;
  children: ChildSessionTreeNode[];
}

export interface SiblingPartition {
  visibleNodes: ChildSessionTreeNode[];
  hiddenFinishedNodes: ChildSessionTreeNode[];
  hiddenCount: number;
}

const STATUS_PRIORITY: Record<SessionChildSession['status'], number> = {
  running: 0,
  delivering: 1,
  awaiting_input: 2,
  error: 3,
  idle: 4,
  done: 5,
};

export function clipTitle(title: string, limit = 36): string {
  const collapsed = (title || '').replace(/\s+/g, ' ').trim();
  if (collapsed.length <= limit) return collapsed;
  return `${collapsed.slice(0, Math.max(1, limit - 1)).trimEnd()}…`;
}

export function cleanCommandPreview(raw: string): string {
  return (raw || '').replace(/\\012/g, ' ').replace(/\s+/g, ' ').trim();
}

export function dedupChildSessions(items: SessionChildSession[]): SessionChildSession[] {
  const map = new Map<string, SessionChildSession>();
  for (const item of items) {
    const sid = (item.session_id || '').trim();
    if (!sid) continue;
    const prev = map.get(sid);
    if (!prev) {
      map.set(sid, item);
      continue;
    }
    const prevRank = STATUS_PRIORITY[prev.status] ?? 9;
    const nextRank = STATUS_PRIORITY[item.status] ?? 9;
    if (nextRank < prevRank) {
      map.set(sid, item);
    }
  }
  return Array.from(map.values());
}

/**
 * C-4 去重活跃角标口径：
 * activeBadgeCount = 活跃子会话数 (running / delivering) + 未归入活跃子会话的独立运行中子进程数。
 */
export function computeProgressBadge(
  data: SessionChildrenResponse | null | undefined
): ProgressBadgeInfo {
  if (!data || !data.summary) {
    return {
      activeCount: 0,
      runningCount: 0,
      deliveringCount: 0,
      badgeText: null,
      tone: 'none',
      externalOnlyDot: false,
    };
  }

  const dedupedChildren = dedupChildSessions(data.child_sessions ?? []);
  const activeChildIds = new Set<string>();
  let runningChildCount = 0;
  let deliveringChildCount = 0;

  for (const child of dedupedChildren) {
    if (child.status === 'running') {
      activeChildIds.add(child.session_id);
      runningChildCount += 1;
    } else if (child.status === 'delivering') {
      activeChildIds.add(child.session_id);
      deliveringChildCount += 1;
    }
  }

  const seenPids = new Set<number>();
  let independentRunningProcCount = 0;
  for (const proc of data.child_processes ?? []) {
    if (!proc.is_running) continue;
    if (seenPids.has(proc.pid)) continue;
    seenPids.add(proc.pid);

    const coveredByActiveChild =
      (proc.host_session_id && activeChildIds.has(proc.host_session_id)) ||
      (proc.launched_by_session_id && activeChildIds.has(proc.launched_by_session_id)) ||
      (proc.linked_session_id ? activeChildIds.has(proc.linked_session_id) : false);
    if (!coveredByActiveChild) {
      independentRunningProcCount += 1;
    }
  }

  const runningCount = runningChildCount + independentRunningProcCount;
  const activeCount = activeChildIds.size + independentRunningProcCount;
  const badgeText = activeCount <= 0 ? null : activeCount > 9 ? '9+' : String(activeCount);
  const tone: ProgressBadgeInfo['tone'] =
    runningCount > 0 ? 'running' : deliveringChildCount > 0 ? 'delivering' : 'none';
  const externalOnlyDot = activeCount === 0 && Boolean(data.summary.external_host_alive);

  return {
    activeCount,
    runningCount,
    deliveringCount: deliveringChildCount,
    badgeText,
    tone,
    externalOnlyDot,
  };
}

function isPriorityStatus(status: SessionChildSession['status']): boolean {
  return (
    status === 'running' ||
    status === 'delivering' ||
    status === 'error' ||
    status === 'awaiting_input'
  );
}

function sortSiblingNodes(nodes: ChildSessionTreeNode[]): ChildSessionTreeNode[] {
  return [...nodes].sort((a, b) => {
    const aPri = a.isPriority || a.subtreeHasActiveOrError ? 0 : 1;
    const bPri = b.isPriority || b.subtreeHasActiveOrError ? 0 : 1;
    if (aPri !== bPri) return aPri - bPri;
    const rankDiff =
      (STATUS_PRIORITY[a.session.status] ?? 9) - (STATUS_PRIORITY[b.session.status] ?? 9);
    if (rankDiff !== 0) return rankDiff;
    const aTs = a.session.last_active_at ?? a.session.started_at ?? 0;
    const bTs = b.session.last_active_at ?? b.session.started_at ?? 0;
    return bTs - aTs;
  });
}

/**
 * C-3：按 `launched_by_session_id` 重组最多 8 层派生树（含环路保护）。
 */
export function buildChildSessionTree(
  rootSessionId: string,
  rawChildren: SessionChildSession[]
): ChildSessionTreeNode[] {
  const deduped = dedupChildSessions(rawChildren);
  if (deduped.length === 0) return [];

  const knownIds = new Set(deduped.map((c) => c.session_id));
  const byParent = new Map<string, SessionChildSession[]>();

  for (const child of deduped) {
    const rawParent = (child.launched_by_session_id || '').trim();
    const effectiveParent =
      rawParent === rootSessionId || knownIds.has(rawParent) ? rawParent : rootSessionId;
    const list = byParent.get(effectiveParent);
    if (list) {
      list.push(child);
    } else {
      byParent.set(effectiveParent, [child]);
    }
  }

  const visited = new Set<string>([rootSessionId]);

  const buildNode = (item: SessionChildSession, treeDepth: number): ChildSessionTreeNode => {
    visited.add(item.session_id);
    const rawKids = treeDepth < 8 ? byParent.get(item.session_id) ?? [] : [];
    const childNodes: ChildSessionTreeNode[] = [];
    for (const kid of rawKids) {
      if (visited.has(kid.session_id)) continue;
      childNodes.push(buildNode(kid, treeDepth + 1));
    }

    const sortedKids = sortSiblingNodes(childNodes);
    const isPriority = isPriorityStatus(item.status);
    const subtreeHasActiveOrError =
      isPriority || sortedKids.some((k) => k.subtreeHasActiveOrError);
    const totalDescendants = sortedKids.reduce(
      (sum, k) => sum + 1 + k.totalDescendants,
      0
    );

    return {
      session: item,
      treeDepth,
      visualDepth: Math.min(treeDepth, 4),
      isPriority,
      subtreeHasActiveOrError,
      defaultExpanded: sortedKids.length > 0 && subtreeHasActiveOrError,
      totalDescendants,
      children: sortedKids,
    };
  };

  const rootKids: ChildSessionTreeNode[] = [];
  for (const direct of byParent.get(rootSessionId) ?? []) {
    if (visited.has(direct.session_id)) continue;
    rootKids.push(buildNode(direct, 1));
  }

  // 若出现断链/孤立循环子集，兜底挂在根下防止遗漏
  for (const item of deduped) {
    if (!visited.has(item.session_id)) {
      rootKids.push(buildNode(item, 1));
    }
  }

  return sortSiblingNodes(rootKids);
}

/**
 * 同级已完结超过 5 条时，默认保留全部活跃/异常项与最近 3 条已完结项。
 */
export function partitionTreeSiblings(nodes: ChildSessionTreeNode[]): SiblingPartition {
  const priorityNodes: ChildSessionTreeNode[] = [];
  const finishedNodes: ChildSessionTreeNode[] = [];

  for (const node of nodes) {
    if (node.isPriority || node.subtreeHasActiveOrError) {
      priorityNodes.push(node);
    } else {
      finishedNodes.push(node);
    }
  }

  if (finishedNodes.length <= 5) {
    return {
      visibleNodes: [...priorityNodes, ...finishedNodes],
      hiddenFinishedNodes: [],
      hiddenCount: 0,
    };
  }

  const keptFinished = finishedNodes.slice(0, 3);
  const hiddenFinished = finishedNodes.slice(3);
  return {
    visibleNodes: [...priorityNodes, ...keptFinished],
    hiddenFinishedNodes: hiddenFinished,
    hiddenCount: hiddenFinished.length,
  };
}

function unwrapShellCommand(cmd: string): string {
  const trimmed = cleanCommandPreview(cmd);
  const m = trimmed.match(/^(?:\/(?:usr\/)?bin\/)?(?:bash|zsh|sh)\s+(?:-[lci]+\s+)?['"]?(.+?)['"]?$/i);
  if (m && m[1]) return m[1].trim();
  return trimmed;
}

/**
 * C-5：把底层 OS 进程命令翻成普通人一眼看懂的任务摘要（技术参数收进次级折叠）。
 */
export function summarizeChildProcess(proc: SessionChildProcess, isZh: boolean): string {
  const raw = cleanCommandPreview(proc.command || proc.comm);
  const unwrapped = unwrapShellCommand(raw);
  const low = unwrapped.toLowerCase();

  if (/\bpytest\b|\bpy\.test\b/.test(low)) {
    return isZh ? '执行测试（pytest）' : 'Running tests (pytest)';
  }
  if (/\bvitest\b|\bjest\b|\bnpm\s+test\b|\bpnpm\s+test\b/.test(low)) {
    return isZh ? '执行前端测试' : 'Running frontend tests';
  }
  if (/\bvite\s+build\b|\bnpm\s+run\s+build\b|\btsc\b|\btype-check\b/.test(low)) {
    return isZh ? '前端构建与类型检查' : 'Frontend build & type check';
  }
  if (/\bruff\b|\beslint\b|\bmypy\b/.test(low)) {
    return isZh ? '代码规范与静态检查' : 'Lint & static checks';
  }
  if (/\bfrago\s+(?:agent|employee)\b/.test(low)) {
    return isZh ? '运行派生代理任务' : 'Running derived agent task';
  }
  if (proc.kind === 'agent_cli' || /\b(?:claude|codex|opencode|agy|frago-core)\b/.test(low)) {
    const tool = low.includes('codex')
      ? 'codex'
      : low.includes('opencode')
        ? 'opencode'
        : low.includes('agy')
          ? 'agy'
          : low.includes('frago-core')
            ? 'CoreAgent'
            : 'Claude';
    return isZh ? `运行代理会话（${tool}）` : `Running agent CLI (${tool})`;
  }
  const gitMatch = unwrapped.match(/\bgit\s+([a-z-]+)/i);
  if (gitMatch) {
    return isZh ? `Git 操作（${gitMatch[1]}）` : `Git operation (${gitMatch[1]})`;
  }
  const pyScript = unwrapped.match(/(?:python3?|uv\s+run(?:\s+python3?)?)\s+(?:-m\s+)?([^\s]+\.(?:py)|[a-zA-Z0-9_.-]+)/i);
  if (pyScript && pyScript[1] && !pyScript[1].startsWith('-')) {
    const target = pyScript[1].split('/').pop() || pyScript[1];
    return isZh ? `运行后台脚本（${target}）` : `Running script (${target})`;
  }
  if (/\bnode\b|\btsx\b/.test(low)) {
    return isZh ? '运行 Node 脚本' : 'Running Node script';
  }
  if (/\bcurl\b|\bwget\b/.test(low)) {
    return isZh ? '执行网络请求' : 'Running network request';
  }
  if (proc.kind === 'subshell') {
    return isZh ? '后台终端命令' : 'Background shell command';
  }
  const name = proc.comm || unwrapped.split(' ')[0] || 'process';
  return isZh ? `后台命令（${name}）` : `Background command (${name})`;
}

/**
 * 将 `ps` 的 `etime`（`MM:SS` / `HH:MM:SS` / `D-HH:MM:SS`）格式化为人话时长。
 */
export function formatElapsedHuman(etime: string, isZh: boolean): string {
  const cleaned = (etime || '').trim();
  if (!cleaned) return '';

  let days = 0;
  let rest = cleaned;
  const dashIdx = cleaned.indexOf('-');
  if (dashIdx >= 0) {
    days = Number.parseInt(cleaned.slice(0, dashIdx), 10) || 0;
    rest = cleaned.slice(dashIdx + 1);
  }
  const parts = rest.split(':').map((p) => Number.parseInt(p, 10));
  if (parts.some((n) => Number.isNaN(n))) return cleaned;

  let hours = 0;
  let mins = 0;
  let secs = 0;
  if (parts.length === 3) {
    [hours, mins, secs] = parts;
  } else if (parts.length === 2) {
    [mins, secs] = parts;
  } else if (parts.length === 1) {
    [secs] = parts;
  }

  if (days > 0) {
    return isZh
      ? `已运行 ${days} 天 ${hours} 小时`
      : `Running ${days}d ${hours}h`;
  }
  if (hours > 0) {
    return isZh
      ? `已运行 ${hours} 小时 ${mins} 分`
      : `Running ${hours}h ${mins}m`;
  }
  if (mins > 0) {
    return isZh
      ? `已运行 ${mins} 分 ${secs} 秒`
      : `Running ${mins}m ${secs}s`;
  }
  return isZh ? `已运行 ${secs} 秒` : `Running ${secs}s`;
}

export function describeProcessSource(
  proc: SessionChildProcess,
  currentSessionId: string,
  childSessionById: Map<string, SessionChildSession>,
  isZh: boolean
): string {
  if (proc.host_session_id === currentSessionId) {
    return isZh ? '当前会话拉起' : 'Started by current session';
  }
  const hostChild = childSessionById.get(proc.host_session_id);
  if (hostChild) {
    const t = clipTitle(hostChild.title || hostChild.session_id, 24);
    return isZh ? `由子会话「${t}」拉起` : `Started by child "${t}"`;
  }
  return isZh ? '由子会话拉起' : 'Started by child session';
}

const GENERIC_ACTORS = new Set(['', '主会话', 'main', 'main session', '当前会话']);

/**
 * AC-09：仅当 Tasks Overview 的 `actor` 能够唯一确定匹配某派生子会话时返回该子会话（不猜不强绑）。
 */
export function matchActorToChildSession(
  actor: string | null | undefined,
  childSessions: SessionChildSession[]
): SessionChildSession | null {
  const norm = (actor || '').trim().toLowerCase();
  if (!norm || GENERIC_ACTORS.has(norm) || childSessions.length === 0) {
    return null;
  }

  const deduped = dedupChildSessions(childSessions);
  const matches = deduped.filter((child) => {
    const emp = (child.employee_id || '').trim().toLowerCase();
    const title = (child.title || '').trim().toLowerCase();
    const sid = child.session_id.toLowerCase();
    return (
      (emp && emp === norm) ||
      (title && title === norm) ||
      sid === norm ||
      (norm.length >= 8 && sid.startsWith(norm))
    );
  });

  return matches.length === 1 ? matches[0] : null;
}
