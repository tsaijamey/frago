/**
 * useSessionMarks — 一场会话的标注：记录流里引用过、暂存过的那些文字。
 *
 * 标注存在服务端，放在这场会话的备份目录里（`GET/PUT /api/workbench/sessions/{sid}/marks`），
 * 与右栏旁路 AI 的槽位同一个地方。换浏览器、清站点数据、刷新之后列表和底色都还在——
 * 标注跟着会话走，不跟着浏览器走。
 *
 * 三条纪律：
 *
 * 1. **点下去那一刻界面就改，不等服务端。** 暂存、改想法、删、挪顺序都是人手上的小动作，
 *    等一次往返才动会像卡住。改完把**整份**交给服务端覆盖。
 * 2. **存不下就回到存下的那一份，并且说一次。** 服务端拒绝或者连不上，界面退回最后一份
 *    确认落盘的样子，NEVER 让界面停在一个盘上并不存在的状态。连着几次改都失败只提示
 *    一次——一串一模一样的报错只会把人吓到。
 * 3. **一次只送一份，按先后送。** 连着点几下会有几份在路上；不排队的话，先发的那份可能
 *    后到，把后面的改动盖回去。所以一份送完再送下一份，每次送的都是此刻最新的那一份。
 *
 * 换会话先清空再读：上一场的标注不许在下一场的记录流里着色哪怕一帧。
 *
 * **分支标注归服务端管**（spec 20260928-webui-session-branch）。它是起分支、收口时由服务端
 * 写进同一个文件的，页面既不新建也不改它，只在服务端动过之后用 `syncBranches` 把盘上那几条
 * 取回来。整份交回去时带着手上那份旧的也不要紧：服务端以盘上的分出去的会话与收口状态为准。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import i18n from '@/i18n';
import { getSessionMarks, putSessionMarks } from '@/api';
import type { WorkbenchMark, WorkbenchMarkKind } from '@/types/api';
import { useUIStore } from '@/stores/uiStore';

export type { WorkbenchMark, WorkbenchMarkKind } from '@/types/api';

/** 暂存或引用那一刻，划选按钮交过来的东西。其余字段由这里补齐。 */
export interface NewMark {
  /** 分支标注只由服务端追加，页面不新建。 */
  kind: Exclude<WorkbenchMarkKind, 'branch'>;
  record_id: string;
  text: string;
  occurrence: number;
  note?: string;
}

export interface SessionMarksState {
  /** 全部标注，数组顺序就是暂存列表的显示顺序。 */
  marks: WorkbenchMark[];
  /** 这场的标注读回来了没有。没读回来之前列表显示空，但不说「还没有暂存」。 */
  loaded: boolean;
  /** 新增一条，交回补齐之后的那一条。没选会话时什么都不做，交回 null。 */
  addMark: (input: NewMark) => WorkbenchMark | null;
  /**
   * 一次新增几条，可以指定是哪一场。引用发出成功才落标注，而接口要等整整一轮才回来，
   * 人这中间常常已经切去别的会话——`sessionId` 不是眼下这一场时，读那一场、接上、整份
   * 写回去，不碰眼下这一场的列表（与 `markUsed` 同一个道理）。
   */
  addMarks: (inputs: NewMark[], sessionId?: string) => void;
  /** 改想法。 */
  setNote: (id: string, note: string) => void;
  /** 删一条。 */
  remove: (id: string) => void;
  /** 把这一条挪到 `to` 这个位置（按整份数组算）。 */
  move: (id: string, to: number) => void;
  /**
   * 这几条标成「用过了」。已经用过的不再改时刻。
   *
   * `sessionId` 给了而且不是眼下这一场：发出去那句话要等整整一轮才回来，人这中间常常
   * 已经切去别的会话。那就直接读那一场的标注、改完写回去，不碰眼下这一场的列表。
   */
  markUsed: (ids: string[], sessionId?: string) => void;
  /**
   * 把盘上的分支标注取回来并进手上这一份：起完分支、收完口之后调。只动分支那几条，
   * 人手上还没送出去的引用、暂存改动原样留着；不往回送。
   */
  syncBranches: () => Promise<void>;
}

/** 用盘上的分支标注替换手上那一份里的分支标注；位置照旧，新的接在后面。 */
export function withServerBranches(list: WorkbenchMark[], server: WorkbenchMark[]): WorkbenchMark[] {
  const fresh = new Map(server.filter((m) => m.kind === 'branch').map((m) => [m.id, m]));
  const out = list.map((m) => (m.kind === 'branch' ? (fresh.get(m.id) ?? m) : m));
  const known = new Set(list.map((m) => m.id));
  for (const [id, m] of fresh) if (!known.has(id)) out.push(m);
  return out;
}

/** 在一份标注里把这几条标成用过了。已经用过的不再改时刻。 */
function withUsed(list: WorkbenchMark[], ids: string[], now: number): WorkbenchMark[] {
  const want = new Set(ids);
  return list.map((m) => (want.has(m.id) && !m.used ? { ...m, used: true, used_at: now } : m));
}

/** 划选按钮交过来的那几项补齐成一条完整的标注。 */
function toMark(input: NewMark): WorkbenchMark {
  return {
    id: newMarkId(),
    kind: input.kind,
    record_id: input.record_id,
    text: input.text,
    occurrence: input.occurrence,
    note: input.note ?? '',
    used: false,
    created_at: Date.now(),
    used_at: null,
  };
}

/** `mk_` 加一串随机字。服务端只认它非空、不重复。 */
export function newMarkId(): string {
  const rand =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 16)
      : Math.random().toString(36).slice(2, 18);
  return `mk_${rand}`;
}

export function useSessionMarks(sessionId: string | null): SessionMarksState {
  const [marks, setMarks] = useState<WorkbenchMark[]>([]);
  const [loaded, setLoaded] = useState(false);
  /** 此刻界面上的那一份。几次改动连在一起时，每一次都得接着上一次的结果改。 */
  const current = useRef<WorkbenchMark[]>([]);
  /** 最后一份确认落盘的。存不下时退回它。 */
  const confirmed = useRef<WorkbenchMark[]>([]);
  /** 当前是哪一场。异步回来的结果对不上就扔掉。 */
  const sidRef = useRef<string | null>(sessionId);
  /** 有一份在路上；它回来之前再改就只记一笔「还要送」。 */
  const inFlight = useRef(false);
  const dirty = useRef(false);
  /** 这一串连续失败已经提示过了。成功一次就重新算。 */
  const warned = useRef(false);
  /**
   * 盘上那一份读没读回来：pending 还在读、ok 读回来了、failed 没读到。
   *
   * 送出去的是**整份**，所以没读回来之前 NEVER 送：那时手上只有这一眼新加的几条，送出去
   * 等于把盘上原有的全抹掉。读到之前的改动先留在界面上，读回来合并了再送；没读到的
   * 这一场一律按存不下处理。
   */
  const readState = useRef<'pending' | 'ok' | 'failed'>('pending');
  // 读取那条效应要在读回来时补送一次；它不能把 flush 列进依赖（一变就重读一遍）。
  const flushRef = useRef<() => Promise<void>>(async () => {});

  const apply = useCallback((next: WorkbenchMark[]) => {
    current.current = next;
    setMarks(next);
  }, []);

  // 换会话：先清空，再读。上一场的标注不许在这一场着色哪怕一帧。
  useEffect(() => {
    sidRef.current = sessionId;
    inFlight.current = false;
    dirty.current = false;
    warned.current = false;
    readState.current = 'pending';
    confirmed.current = [];
    apply([]);
    setLoaded(false);
    if (!sessionId) return;
    let alive = true;
    getSessionMarks(sessionId)
      .then((body) => {
        if (!alive || sidRef.current !== sessionId) return;
        const list = Array.isArray(body?.marks) ? body.marks : [];
        confirmed.current = list;
        readState.current = 'ok';
        // 读回来之前人已经动过手（刚打开就划选暂存）：盘上的在前，这一眼新加的接在后面。
        const known = new Set(list.map((m) => m.id));
        apply([...list, ...current.current.filter((m) => !known.has(m.id))]);
        setLoaded(true);
        if (dirty.current) void flushRef.current();
      })
      .catch(() => {
        if (!alive || sidRef.current !== sessionId) return;
        // 取不到就当还没有标注，界面照常摆得出来；但这一场不许写盘，见 readState。
        readState.current = 'failed';
        setLoaded(true);
        if (dirty.current) void flushRef.current();
      });
    return () => {
      alive = false;
    };
  }, [sessionId, apply]);

  /** 把此刻那一份送出去。在路上的那份回来之后，若中途又改过，接着送最新的。 */
  const flush = useCallback(async () => {
    const sid = sidRef.current;
    if (!sid || inFlight.current || readState.current === 'pending') return;
    inFlight.current = true;
    dirty.current = false;
    const snapshot = current.current;
    try {
      if (readState.current === 'failed') {
        throw new Error(i18n.t('workbench.errors.marksNotLoaded'));
      }
      await putSessionMarks(sid, { version: 1, marks: snapshot });
      if (sidRef.current !== sid) return;
      confirmed.current = snapshot;
      warned.current = false;
    } catch (e) {
      if (sidRef.current !== sid) return;
      // 退回最后一份落了盘的。这之后排着的改动也一并作废——它们是接着失败那一份改的。
      dirty.current = false;
      apply(confirmed.current);
      if (!warned.current) {
        warned.current = true;
        useUIStore.getState().showToast(
          i18n.t('workbench.errors.marksSaveFailed', {
            reason: e instanceof Error ? e.message : String(e),
          }),
          'error'
        );
      }
    } finally {
      if (sidRef.current === sid) {
        inFlight.current = false;
        if (dirty.current) void flush();
      }
    }
  }, [apply]);
  flushRef.current = flush;

  const commit = useCallback(
    (next: WorkbenchMark[]) => {
      if (!sidRef.current) return;
      apply(next);
      dirty.current = true;
      void flush();
    },
    [apply, flush]
  );

  const addMark = useCallback(
    (input: NewMark): WorkbenchMark | null => {
      if (!sidRef.current) return null;
      const mark = toMark(input);
      commit([...current.current, mark]);
      return mark;
    },
    [commit]
  );

  const addMarks = useCallback(
    (inputs: NewMark[], sessionId?: string) => {
      if (!inputs.length) return;
      if (sessionId && sessionId !== sidRef.current) {
        void (async () => {
          try {
            const body = await getSessionMarks(sessionId);
            const list = Array.isArray(body?.marks) ? body.marks : [];
            await putSessionMarks(sessionId, { version: 1, marks: [...list, ...inputs.map(toMark)] });
          } catch (e) {
            useUIStore.getState().showToast(
              i18n.t('workbench.errors.marksSaveFailed', {
                reason: e instanceof Error ? e.message : String(e),
              }),
              'error'
            );
          }
        })();
        return;
      }
      if (!sidRef.current) return;
      commit([...current.current, ...inputs.map(toMark)]);
    },
    [commit]
  );

  const setNote = useCallback(
    (id: string, note: string) => {
      const list = current.current;
      if (!list.some((m) => m.id === id && m.note !== note)) return;
      commit(list.map((m) => (m.id === id ? { ...m, note } : m)));
    },
    [commit]
  );

  const remove = useCallback(
    (id: string) => {
      const list = current.current;
      if (!list.some((m) => m.id === id)) return;
      commit(list.filter((m) => m.id !== id));
    },
    [commit]
  );

  const move = useCallback(
    (id: string, to: number) => {
      const list = current.current;
      const from = list.findIndex((m) => m.id === id);
      if (from === -1) return;
      const target = Math.min(Math.max(0, to), list.length - 1);
      if (target === from) return;
      const next = [...list];
      const [item] = next.splice(from, 1);
      next.splice(target, 0, item);
      commit(next);
    },
    [commit]
  );

  const markUsed = useCallback(
    (ids: string[], sessionId?: string) => {
      if (sessionId && sessionId !== sidRef.current) {
        // 人已经切走了：那一场的标注不在手上，读一份、改完整份写回去。
        void (async () => {
          try {
            const body = await getSessionMarks(sessionId);
            const list = Array.isArray(body?.marks) ? body.marks : [];
            if (!list.some((m) => ids.includes(m.id) && !m.used)) return;
            await putSessionMarks(sessionId, { version: 1, marks: withUsed(list, ids, Date.now()) });
          } catch (e) {
            useUIStore.getState().showToast(
              i18n.t('workbench.errors.marksSaveFailed', {
                reason: e instanceof Error ? e.message : String(e),
              }),
              'error'
            );
          }
        })();
        return;
      }
      const list = current.current;
      const want = new Set(ids);
      if (!list.some((m) => want.has(m.id) && !m.used)) return;
      commit(withUsed(list, ids, Date.now()));
    },
    [commit]
  );

  const syncBranches = useCallback(async () => {
    const sid = sidRef.current;
    if (!sid) return;
    try {
      const body = await getSessionMarks(sid);
      if (sidRef.current !== sid) return;
      const server = Array.isArray(body?.marks) ? body.marks : [];
      confirmed.current = withServerBranches(confirmed.current, server);
      apply(withServerBranches(current.current, server));
    } catch {
      // 取不回来只是这一刻看不到虚线，下次换回这场会话会重读。不打断人。
    }
  }, [apply]);

  return { marks, loaded, addMark, addMarks, setNote, remove, move, markUsed, syncBranches };
}
