/**
 * useAgentClients — 新建会话时能挑哪几家 CLI，以及新建这件事本身。
 *
 * **名单一律来自服务端。** 这里一个字都不写死："本机装了哪几家"是本机的事实，只有
 * 服务端问得到；而"frago 支持哪几家"出自 driver 注册表，前端再抄一份的话，接新家的人
 * 改完 driver 会发现界面上它根本不出现，而 driver 那侧一点异样都没有。
 *
 * **挑不了的那几家照样收下。** 服务端把它们连同理由一起给，界面摆出来但不可点——整个
 * 藏掉，人只会觉得"frago 不支持 codex"，而真相往往只是没装。
 *
 * **新建有两条路，因为编号的来路是两种。** claude 接受由调用方指定编号，点完创建当场
 * 就知道这一场叫什么；codex / opencode 的编号由它们自己分配，frago 要等会话起来后认领，
 * 所以中间有一段空窗。空窗期由 `waitForSession` 轮询把手，NEVER 假装编号已经有了——
 * 那会让界面跳进一场并不存在的会话，人看到一片空记录流，以为刚开的会话丢了。
 */

import { useEffect, useState } from 'react';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 上次挑的那一家记在本地。这是"我这台机器习惯用哪个"，不是跨设备的数据。 */
const LAST_AGENT_KEY = 'frago-workbench-last-agent';

export interface AgentClient {
  agent_type: string;
  display_name: string;
  /** 本机装没装；null = 这一家没提供探测方式，判不出。 */
  installed: boolean | null;
  path: string | null;
  /** 工作台里的家族名；null = 记录读不回工作台。 */
  family: string | null;
  selectable: boolean;
  /** 摆在名字底下那一句：挑不了的理由，或"判不出装没装"的提醒。 */
  reason: string | null;
  /** 'caller' = 编号页面这边定；'claimed' = 起来之后认领，新建时要等一会儿。 */
  id_origin: 'caller' | 'claimed';
}

export interface PendingLaunch {
  handle: string;
  agent: string;
  display_name: string;
  cwd: string;
  /** 认到编号没有。null = 还在等。 */
  session_id: string | null;
  /** 起会话这条路上出的错。有值就别再等了。 */
  error: string | null;
  finished: boolean;
}

export interface AgentClientsState {
  agents: AgentClient[];
  /** 服务端建议默认挑哪一家；一家都挑不了时为 null。 */
  fallbackDefault: string | null;
  loading: boolean;
  error: string | null;
}

export async function fetchAgents(): Promise<{ agents: AgentClient[]; default: string | null }> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/agents`);
  if (!res.ok) throw new Error(`取不到本机的客户端清单（HTTP ${res.status}）`);
  return (await res.json()) as { agents: AgentClient[]; default: string | null };
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

export async function createSession(input: {
  agent: string;
  cwd: string;
  text: string;
}): Promise<PendingLaunch> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readError(res, `没建起来（HTTP ${res.status}）`));
  return (await res.json()) as PendingLaunch;
}

export async function fetchPending(handle: string): Promise<PendingLaunch> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/sessions/pending/${encodeURIComponent(handle)}`
  );
  if (!res.ok) throw new Error(await readError(res, `问不到这次新建（HTTP ${res.status}）`));
  return (await res.json()) as PendingLaunch;
}

/**
 * 等这次新建报出会话编号。
 *
 * 起手快、越等越慢：codex 的记录文件在 TUI 起来那一刻就建好（几秒），opencode 要等首轮
 * 提交落库（久一些）。一律按最慢的节奏问，前者要白等好几拍。
 *
 * **等不到不返回一个编造的编号。** 服务端说这次起失败了（`error`），或者首轮都跑完了还
 * 没认到（`finished` 且没编号），就抛出来让调用方去报——让界面跳进一场并不存在的会话，
 * 比直说"没起来"坏得多。
 */
export async function waitForSession(
  handle: string,
  options: { signal?: AbortSignal } = {}
): Promise<string> {
  const delays = [700, 700, 1000, 1000, 1500, 1500, 2000, 2000, 3000, 3000, 5000, 5000, 5000];
  for (const delay of delays) {
    await new Promise((r) => setTimeout(r, delay));
    if (options.signal?.aborted) throw new Error('已取消');
    const launch = await fetchPending(handle);
    if (launch.session_id) return launch.session_id;
    if (launch.error) throw new Error(launch.error);
    if (launch.finished) {
      throw new Error(`${launch.display_name} 这一轮跑完了也没报出会话编号，去 tmux 里看看它`);
    }
  }
  throw new Error('等太久了，还是没等到会话编号');
}

export function readLastAgent(): string | null {
  try {
    return localStorage.getItem(LAST_AGENT_KEY);
  } catch {
    return null;
  }
}

export function rememberLastAgent(agentType: string): void {
  try {
    localStorage.setItem(LAST_AGENT_KEY, agentType);
  } catch {
    // 记不住只是下次回到默认那一家，不值得打断任何事。
  }
}

/**
 * 清单只在对话框打开时取一次。
 *
 * 装没装是台面下的事实，不会在对话框开着的这十几秒里变；定时重取只会让一个静止的
 * 列表反复闪。`enabled` 关掉时不发请求——对话框没开就去问一遍，纯属白花。
 */
export function useAgentClients(enabled: boolean): AgentClientsState {
  const [agents, setAgents] = useState<AgentClient[]>([]);
  const [fallbackDefault, setFallbackDefault] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setLoading(true);
    setError(null);
    fetchAgents()
      .then((body) => {
        if (!alive) return;
        setAgents(body.agents ?? []);
        setFallbackDefault(body.default ?? null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        // 取不到就明说取不到。悄悄退回"只有 claude"会让人以为本机只装了这一家。
        setError(e instanceof Error ? e.message : '取不到本机的客户端清单');
        setAgents([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [enabled]);

  return { agents, fallbackDefault, loading, error };
}

/**
 * 这次该默认选中哪一家：上次挑的那个优先，它现在挑不了就退到服务端建议的那个。
 *
 * 上次挑的优先，是因为人换机位是有惯性的——昨天用 codex 的人今天多半还用 codex。
 * 它现在挑不了（卸了 / 坏了）时**不声张地**退回默认：为一个上次的选择弹一句报错，
 * 除了打断没有用处，界面上选中的是谁本来就看得见。
 */
export function pickDefaultAgent(
  agents: AgentClient[],
  fallbackDefault: string | null
): string | null {
  const selectable = agents.filter((a) => a.selectable);
  if (!selectable.length) return null;
  const remembered = readLastAgent();
  if (remembered && selectable.some((a) => a.agent_type === remembered)) return remembered;
  if (fallbackDefault && selectable.some((a) => a.agent_type === fallbackDefault)) {
    return fallbackDefault;
  }
  return selectable[0].agent_type;
}
