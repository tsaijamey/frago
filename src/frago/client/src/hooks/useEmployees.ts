/**
 * useEmployees — 员工页在界面这一侧的取数。
 *
 * 一个员工就是一个岗位编制（`~/.frago/employees/<编号>.json`）：它管着哪几块 `~/.frago/data`
 * 目录、管着哪些知识域与配方、起会话时默认用哪家内核。服务端 `routes/employees.py` 把读写
 * 与领地校验全做完了，这一侧只负责取、存、把服务端的原话摆出来。
 *
 * **清单为空是服务端的事，不是这一页的事。** 服务端读清单时发现一个员工都没有，会先落一个
 * 内置的 `stock` 岗位再回。这一侧 NEVER 自己造一个占位岗位——那会让「本机有哪些岗位」这句话
 * 有两个来源，而其中一个凭空编。
 *
 * 两类失败分开报：清单取不到（服务没起来、路由没挂）与某个员工的详情取不到（编号不存在）。
 * 前者整页说取不到，后者只让那一张卡片说。
 */

import { useCallback, useEffect, useState } from 'react';
import i18n from '@/i18n';
import { useDataStore } from '@/stores/dataStore';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** 一个员工编制的本体，字段与服务端的 `EmployeePostRecord` 对齐。 */
export interface EmployeePost {
  member_post_id: string;
  title: string;
  agent_kernel: string;
  description: string;
  work_scope: string;
  cwd: string;
  knowledge_domains: string[];
  recipes: string[];
  data_slots: string[];
  schedule_ids: string[];
  active_session_ids: string[];
  allowed_commands: string[];
  skills?: string[];
  color?: string;
  created_at: string;
  updated_at: string;
  /** 清单接口顺带给的一行总览：几个槽位、每个槽位几项、合计几项。 */
  data_summary: {
    slot_count: number;
    entry_count: number;
    slots: { slot_path: string; exists: boolean; entry_count: number }[];
  };
}

/** 一个槽位扫出来的那一层：槽位本身就是一件件工作的容器，再往下是每件工作的内部。 */
export interface DataSlotScan {
  slot_path: string;
  resolved_path: string;
  exists: boolean;
  total_count: number;
  entries: { name: string; summary: string; file_count: number }[];
}

/** 账本里一条认领项的来路：叫什么、凭什么认的。 */
export interface ClaimedSlot {
  path: string;
  name: string;
  /** 是不是人手绑的（而不是巡检认出来的）。 */
  bound?: boolean;
  /** 巡检时靠什么认出来的，如 `name` / `entry_summary`。 */
  discovered_by?: string;
  /** 认领依据的原文片段，让人能核对「凭什么说这块归他」。 */
  evidence?: string;
}

export interface ClaimedRecipe {
  name: string;
  display_title?: string;
  description?: string;
}

export interface ClaimedDomain {
  name: string;
  purpose?: string;
  doc_count?: number;
}

export interface ClaimedSession {
  session_id: string;
  title: string;
  first_prompt_summary?: string;
}

export interface ClaimedGlossaryTerm {
  term: string;
  meaning: string;
  mapped_targets?: string[];
}

/**
 * 账本摘要 —— 员工自己巡检一趟认下了什么。
 *
 * 四栏各有一个「几条」的计数，明细在 `claimed_details` 里。计数与明细分开，是因为列表接口
 * 只要计数（卡片上那一行摘要），而弹窗要明细。`claimed_details` 可以没有：老账本没存明细
 * 时不代表「一条没认」，所以页面 NEVER 拿它缺席当空。
 */
export interface LedgerSummary {
  member_post_id: string;
  updated_at: string;
  last_synced_at: string;
  claimed_resources: {
    data_slots: string[];
    recipe_count: number;
    knowledge_domain_count: number;
    matched_session_count: number;
  };
  claimed_details?: {
    data_slots: ClaimedSlot[];
    recipes: ClaimedRecipe[];
    knowledge_domains: ClaimedDomain[];
    matched_sessions: ClaimedSession[];
    glossary: ClaimedGlossaryTerm[];
  };
  excluded_resources?: {
    data_slots: string[];
    recipes: string[];
    knowledge_domains: string[];
  };
}

/** 本机上还能往这个员工身上绑的东西：数据目录、知识域、配方各一份候选。 */
export interface AvailableResources {
  data_slots: { path: string; name: string }[];
  knowledge_domains: { name: string; purpose: string }[];
  recipes: { name: string; display_title: string; description: string }[];
}

/** 某个员工的详情：编制本身、领地索引、账本、可补绑的候选，以及新会话会自动带入的那段语境原文。 */
export interface EmployeeDetail {
  employee: EmployeePost;
  managed_data: {
    member_post_id: string;
    data_slots: DataSlotScan[];
    knowledge_domains: string[];
    recipes: string[];
  };
  /** 还没巡检过的岗位没有账本，这里是 null——那是「还没查」，不是「没查到」。 */
  ledger?: LedgerSummary | null;
  available_resources?: AvailableResources;
  business_context_block: string;
}

/** 建或改一个员工时交上去的那一份。`cwd` / `work_scope` 给 null 表示这一栏不动。 */
export interface EmployeeUpsert {
  member_post_id: string;
  title: string;
  agent_kernel: string;
  description: string;
  work_scope: string | null;
  cwd: string | null;
  knowledge_domains: string[];
  recipes: string[];
  data_slots: string[];
  schedule_ids: string[];
  allowed_commands: string[];
  skills?: string[];
  color?: string;
}

async function readError(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail || fallback;
  } catch {
    return fallback;
  }
}

export async function fetchEmployees(): Promise<EmployeePost[]> {
  const res = await fetch(`${API_BASE_URL}/api/employees`);
  if (!res.ok) {
    throw new Error(
      await readError(res, i18n.t('employees.errors.listFailed', { status: res.status }))
    );
  }
  const body = (await res.json()) as { employees?: EmployeePost[] };
  return body.employees ?? [];
}

export async function fetchEmployee(memberPostId: string): Promise<EmployeeDetail> {
  const res = await fetch(
    `${API_BASE_URL}/api/employees/${encodeURIComponent(memberPostId)}`
  );
  if (!res.ok) {
    throw new Error(
      await readError(res, i18n.t('employees.errors.detailFailed', { status: res.status }))
    );
  }
  return (await res.json()) as EmployeeDetail;
}

/**
 * 存一个员工。新建走 `POST`、改动走 `PUT`，两条路收的是同一份东西。
 *
 * 编号不存在时服务端回 404 而**不顺手新建一个**：人以为自己在改某个岗位的领地，实际改的是
 * 一个刚被凭空建出来的同名岗位，两边的期望当场分岔。
 */
export async function saveEmployee(
  input: EmployeeUpsert,
  options: { create: boolean }
): Promise<EmployeePost> {
  const url = options.create
    ? `${API_BASE_URL}/api/employees`
    : `${API_BASE_URL}/api/employees/${encodeURIComponent(input.member_post_id)}`;
  const res = await fetch(url, {
    method: options.create ? 'POST' : 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    throw new Error(
      await readError(res, i18n.t('employees.errors.saveFailed', { status: res.status }))
    );
  }
  return (await res.json()) as EmployeePost;
}

/**
 * 手动触发一次该员工的巡检记账。
 *
 * `full` 为真时丢掉游标重扫一遍，用于「改过岗位职责、想重新认领」的场合。默认走增量：
 * 指纹没变的资源直接跳过，所以第二次点通常是「新增 0」——那不是没干活，是没活可干。
 *
 * 返回的是巡检结果本身（新增几条、跳了几条），页面不解释它，只拿它当「这一趟跑完了」的
 * 信号，随后重取详情。所以这里给 `unknown`，NEVER 在这一侧另造一份与账本并行的形状。
 */
export async function syncEmployeeLedger(
  memberPostId: string,
  full = true
): Promise<unknown> {
  const res = await fetch(
    `${API_BASE_URL}/api/employees/${encodeURIComponent(memberPostId)}/sync-ledger?full=${
      full ? 'true' : 'false'
    }`,
    { method: 'POST' }
  );
  if (!res.ok) {
    throw new Error(
      await readError(res, i18n.t('employees.errors.syncFailed', { status: res.status }))
    );
  }
  return res.json();
}

/** 在员工领地里登记一个归档目录。越界由服务端的契约当场拒绝，这一侧不另判一遍。 */
export async function registerEmployeeData(
  memberPostId: string,
  input: { folder_name: string; summary?: string; slot_path?: string }
): Promise<unknown> {
  const res = await fetch(
    `${API_BASE_URL}/api/employees/${encodeURIComponent(memberPostId)}/data`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }
  );
  if (!res.ok) {
    throw new Error(
      await readError(res, i18n.t('employees.errors.dataFailed', { status: res.status }))
    );
  }
  return res.json();
}

export interface EmployeeListState {
  employees: EmployeePost[];
  loading: boolean;
  error: string | null;
  /** 立刻重取一次，给刷新按钮与存完之后的收尾用。 */
  reload: () => void;
}

/**
 * 清单只在页面看得见时取。
 *
 * `enabled` 关掉时不发请求——页面被宿主藏起来时没人看，占着服务端没有意义（与
 * `useAutoRefresh` 的判据同一条）。
 */
export function useEmployeeList(enabled = true): EmployeeListState {
  const [employees, setEmployees] = useState<EmployeePost[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setLoading(true);
    fetchEmployees()
      .then((list) => {
        if (!alive) return;
        setEmployees(list);
        useDataStore.getState().setEmployees(list);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        // 取不到就明说取不到，NEVER 退回一份空清单——空清单在页面上是「本机没有员工」，
        // 而真相是这一趟没问着，两句话人分不出来。
        setError(e instanceof Error ? e.message : i18n.t('employees.errors.listFailedPlain'));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [enabled, nonce]);

  return { employees, loading, error, reload };
}
