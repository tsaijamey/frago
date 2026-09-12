/**
 * useSessionGroups — 左栏会话分组的数据源。
 *
 * 分组存在服务端（`/api/workbench/groups`），与置顶一样不存浏览器本地：换一个浏览器、换一台
 * 设备，本地存储天生不通，人在一处搬好的分组换个地方打开就不见了。
 *
 * **一场会话只在一个组里。** 放进另一个组就是从原来那组搬走，界面照这个规矩先改、服务端
 * 回来的那份为准。
 *
 * **点下去那一刻界面就改，不等服务端。** 服务端拒绝时把界面改回去并把错抛出来，NEVER 让
 * 界面停在一个盘上并不存在的状态。
 *
 * **AI 分组在后台跑。** 点下去立刻回来，之后每隔几秒取一次分组，直到那一趟跑完——分好的
 * 会话一批一批落进各自的组里，人看得见它在动。
 *
 * 各分区折没折起来记在本地：那是"我这块屏幕上现在想不想看见"，不是跨设备的数据。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import i18n from '@/i18n';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

const COLLAPSED_KEY = 'frago-workbench-groups-collapsed';

/** 「未分组」那一区在折叠记录里的键。标签的键就是标签编号。 */
export const UNGROUPED = '__ungrouped';

/** AI 在跑时隔多久取一次分组。一批要几十秒，三秒一趟足够看得出在动。 */
export const AI_POLL_MS = 3_000;

export interface GroupTag {
  id: string;
  name: string;
  /** AI 建的还是人建的。 */
  source: 'ai' | 'human';
}

/** 后台那一趟 AI 分组走到哪了。字段与服务端 `workbench_groups.AiJob` 逐字对齐。 */
export interface AiJobState {
  running: boolean;
  /** `tags` 在拟标签 / `assign` 在归组。 */
  phase: 'tags' | 'assign' | null;
  done: number;
  total: number;
  assigned: number;
  created_tags: number;
  error: string | null;
  /** 秒级时间戳。一趟都没跑过时为 null。 */
  finished_at: number | null;
}

interface GroupsPayload {
  tags: GroupTag[];
  sessions: Record<string, string[]>;
  ai_tags_created: boolean;
  ai_job: AiJobState;
}

const IDLE_JOB: AiJobState = {
  running: false,
  phase: null,
  done: 0,
  total: 0,
  assigned: 0,
  created_tags: 0,
  error: null,
  finished_at: null,
};

const EMPTY: GroupsPayload = { tags: [], sessions: {}, ai_tags_created: false, ai_job: IDLE_JOB };

export interface SessionGroupsState {
  tags: GroupTag[];
  /** 这场会话在哪个组里。没分组是 null。 */
  groupOf: (sessionId: string) => string | null;
  /**
   * 这个标签下一共挂着几场。按分组里记着的编号数，不是左栏眼下摆出来的数——原文件被
   * Claude Code 清掉、清单里暂时没有的那几场也算在里面。
   */
  sizeOf: (tagId: string) => number;
  /** 放进某个组；`tagId` 为 null 就是移出分组。失败时界面已经改回去了，错照样抛出来。 */
  assign: (sessionId: string, tagId: string | null) => Promise<void>;
  /** 建一个标签，回建好的那个。 */
  createTag: (name: string) => Promise<GroupTag>;
  deleteTag: (tagId: string) => Promise<void>;
  aiJob: AiJobState;
  runAi: () => Promise<void>;
  /** 这一区折没折起来。键是标签编号，或 `UNGROUPED`。 */
  isCollapsed: (key: string) => boolean;
  toggleCollapsed: (key: string) => void;
}

async function readPayload(res: Response, errorKey: string): Promise<GroupsPayload> {
  if (!res.ok) {
    let detail = '';
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // 没有可读的错误正文就只报状态码。
    }
    throw new Error(detail || i18n.t(errorKey, { status: res.status }));
  }
  const body = (await res.json()) as Partial<GroupsPayload>;
  return {
    tags: body.tags ?? [],
    sessions: body.sessions ?? {},
    ai_tags_created: Boolean(body.ai_tags_created),
    ai_job: body.ai_job ?? IDLE_JOB,
  };
}

export async function fetchGroups(): Promise<GroupsPayload> {
  return readPayload(await fetch(`${API_BASE_URL}/api/workbench/groups`), 'workbench.errors.groupsFetchFailed');
}

async function putAssign(sessionId: string, tagId: string | null): Promise<GroupsPayload> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/groups/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tag_id: tagId }),
    }
  );
  return readPayload(res, 'workbench.errors.groupSaveFailed');
}

async function postTag(name: string): Promise<GroupsPayload> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/groups/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  return readPayload(res, 'workbench.errors.tagCreateFailed');
}

async function removeTag(tagId: string): Promise<GroupsPayload> {
  const res = await fetch(
    `${API_BASE_URL}/api/workbench/groups/tags/${encodeURIComponent(tagId)}`,
    { method: 'DELETE' }
  );
  return readPayload(res, 'workbench.errors.tagDeleteFailed');
}

async function postAi(): Promise<GroupsPayload> {
  const res = await fetch(`${API_BASE_URL}/api/workbench/groups/ai`, { method: 'POST' });
  return readPayload(res, 'workbench.errors.groupAiStartFailed');
}

function readCollapsed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

/** 把 `标签 → 会话编号` 翻成 `会话编号 → 标签`，左栏逐行都要问一次。 */
function indexOf(sessions: Record<string, string[]>): Map<string, string> {
  const map = new Map<string, string>();
  for (const [tagId, members] of Object.entries(sessions)) {
    for (const sid of members) {
      if (!map.has(sid)) map.set(sid, tagId);
    }
  }
  return map;
}

export function useSessionGroups(): SessionGroupsState {
  const [payload, setPayload] = useState<GroupsPayload>(EMPTY);
  const [collapsed, setCollapsedState] = useState<Record<string, boolean>>(readCollapsed);

  useEffect(() => {
    let alive = true;
    fetchGroups()
      .then((p) => {
        if (alive) setPayload(p);
      })
      .catch(() => {
        // 取不到就当没分过组：左栏照常摆得出会话清单，只是没有分区。开局弹一句人还没做
        // 任何事的报错，除了吓人没有用处。
      });
    return () => {
      alive = false;
    };
  }, []);

  /** AI 在跑就一直取，跑完那一趟取回来的就是最终结果，定时器随之停下。 */
  const running = payload.ai_job.running;
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      fetchGroups()
        .then(setPayload)
        .catch(() => {
          // 某一趟没取到不要紧，下一趟再取。
        });
    }, AI_POLL_MS);
    return () => clearInterval(timer);
  }, [running]);

  const index = useMemo(() => indexOf(payload.sessions), [payload.sessions]);
  const groupOf = useCallback((sessionId: string) => index.get(sessionId) ?? null, [index]);

  /**
   * 连点时以**最后一下**为准：两次请求先后到达的顺序不保证，先发的后到会把后发的结果
   * 盖回去。记下这一场最后一次搬到了哪，只有最后那一趟的结果算数。
   */
  const latestIntent = useRef(new Map<string, number>());
  const seq = useRef(0);

  const assign = useCallback(
    async (sessionId: string, tagId: string | null) => {
      const before = index.get(sessionId) ?? null;
      const ticket = ++seq.current;
      latestIntent.current.set(sessionId, ticket);
      const move = (from: GroupsPayload, target: string | null): GroupsPayload => {
        const sessions: Record<string, string[]> = {};
        for (const [id, members] of Object.entries(from.sessions)) {
          sessions[id] = members.filter((sid) => sid !== sessionId);
        }
        if (target && sessions[target]) sessions[target] = [...sessions[target], sessionId];
        return { ...from, sessions };
      };
      setPayload((prev) => move(prev, tagId));
      try {
        const authoritative = await putAssign(sessionId, tagId);
        if (latestIntent.current.get(sessionId) === ticket) setPayload(authoritative);
      } catch (e) {
        if (latestIntent.current.get(sessionId) === ticket) setPayload((prev) => move(prev, before));
        throw e;
      }
    },
    [index]
  );

  const createTag = useCallback(async (name: string) => {
    const next = await postTag(name);
    setPayload(next);
    const key = name.trim().replace(/\s+/g, ' ').toLocaleLowerCase();
    const created = next.tags.find((t) => t.name.toLocaleLowerCase() === key);
    if (!created) throw new Error(i18n.t('workbench.errors.tagCreateFailedPlain'));
    return created;
  }, []);

  const deleteTag = useCallback(async (tagId: string) => {
    setPayload(await removeTag(tagId));
  }, []);

  const runAi = useCallback(async () => {
    setPayload(await postAi());
  }, []);

  const isCollapsed = useCallback(
    // 没记过的：「未分组」默认摊开（新进来的会话都在这），各标签默认折起。
    (key: string) => collapsed[key] ?? key !== UNGROUPED,
    [collapsed]
  );

  const toggleCollapsed = useCallback((key: string) => {
    setCollapsedState((prev) => {
      const next = { ...prev, [key]: !(prev[key] ?? key !== UNGROUPED) };
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next));
      } catch {
        // 存不下也照常折叠，只是下次打开回到默认。
      }
      return next;
    });
  }, []);

  const sizeOf = useCallback(
    (tagId: string) => payload.sessions[tagId]?.length ?? 0,
    [payload.sessions]
  );

  return {
    tags: payload.tags,
    groupOf,
    sizeOf,
    assign,
    createTag,
    deleteTag,
    aiJob: payload.ai_job,
    runAi,
    isCollapsed,
    toggleCollapsed,
  };
}
