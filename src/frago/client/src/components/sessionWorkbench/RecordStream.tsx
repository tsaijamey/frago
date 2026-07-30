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
 *    锚定）不算手动，NEVER 因此解除。
 * 3. **同一次模型回复要视觉归组，分组编号不显示。** `group_id` 是三十几位的机器标识，
 *    对人零意义。归组只体现为一个包住多张卡的容器，容器头写模型名与本组条数。
 */

import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type UIEvent,
} from 'react';
import { Inbox, Loader2 } from 'lucide-react';
import RecordCard from './RecordCard';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

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

/** 这一组里模型叫什么。取组内第一条报了模型的记录，报不出就不显示。 */
function modelOf(records: WorkbenchRecord[]): string {
  for (const record of records) {
    const model = record.payload.model;
    if (typeof model === 'string' && model) return model;
  }
  return '';
}

/** 离顶部多近算「在翻更早的」，触发前插。 */
const NEAR_TOP_PX = 240;
/** 离底部多近算「人就在底部」，手动滚到这里立即重新武装自动滚动。 */
const AT_BOTTOM_PX = 60;
/** 手动输入事件后多久之内的滚动算是人滚的。程序滚动不在这个窗口里。 */
const MANUAL_INTENT_MS = 400;
/** 解除后多久没再手动滚动，新条目进来时自动滚动复活。 */
const REARM_AFTER_MS = 10_000;

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
}

export default function RecordStream({
  sessionId,
  records,
  loading,
  loadingOlder,
  hasOlder,
  error,
  onLoadOlder,
}: RecordStreamProps) {
  const groups = useMemo(() => groupRecords(records), [records]);

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

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  // 换会话：一切归零，默认重新武装——新打开的会话就该落在最新内容上。
  // 必须是布局效应且声明在记录流效应之前：挂载时普通效应跑在布局效应之后，会把记录流
  // 效应刚记下的首尾编号抹掉，下一帧追加就被误判成初装，视口不由分说沉到底。
  useLayoutEffect(() => {
    followArmed.current = true;
    lastManualScrollAt.current = 0;
    manualIntentUntil.current = 0;
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
        scrollToBottom();
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

  /** 人的滚动输入留下一张短期通行证：随后的 onScroll 按手动处理。 */
  const noteManualIntent = useCallback(() => {
    manualIntentUntil.current = Date.now() + MANUAL_INTENT_MS;
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
      if (now <= manualIntentUntil.current) {
        lastManualScrollAt.current = now;
        followArmed.current =
          el.scrollHeight - el.scrollTop - el.clientHeight < AT_BOTTOM_PX;
      }

      // 翻到顶附近：钉住当前几何，取更早的一页前插。
      if (el.scrollTop < NEAR_TOP_PX) {
        if (olderArmed.current && hasOlder && !loadingOlder) {
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

  if (!sessionId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-text-muted">
        <Inbox size={44} strokeWidth={1.4} />
        <p className="text-[13px]">从左边挑一场会话，记录会在这里逐条铺开</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onWheel={noteManualIntent}
        onTouchMove={noteManualIntent}
        onKeyDown={handleKeyDown}
        onMouseDown={handleMouseDown}
        className="min-h-0 flex-1 overflow-y-auto px-5 py-4"
        data-testid="record-stream-scroll"
      >
        <div className="mx-auto flex w-full max-w-[760px] min-w-0 flex-col gap-4">
          {loadingOlder ? (
            <p className="flex items-center justify-center gap-2 py-2 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              取更早的记录
            </p>
          ) : null}

          {!hasOlder && records.length ? (
            <p className="py-2 text-center text-[11px] text-text-muted">
              这是这场会话的开头，共 {records.length} 条记录
            </p>
          ) : null}

          {error ? (
            <p className="rounded-[6px] bg-bg-subtle px-3 py-2 text-[12px] text-text-secondary">
              {error}
            </p>
          ) : null}

          {!records.length && !loading && !error ? (
            <div className="flex flex-col items-center gap-3 py-16 text-text-muted">
              <Inbox size={44} strokeWidth={1.4} />
              <p className="text-[13px]">这场会话只有元信息，一条记录都没留下</p>
              <p className="text-[12px]">它不是坏了，是当时什么都没发生</p>
            </div>
          ) : null}

          {groups.map((group, index) => {
            if (!group.groupId || group.records.length === 1) {
              return group.records.map((record) => (
                <RecordCard key={record.id} record={record} sessionId={sessionId} />
              ));
            }
            const model = modelOf(group.records);
            return (
              <section
                key={`${group.groupId}-${index}`}
                data-testid="record-group"
                className="min-w-0 rounded-[14px] border border-border-color bg-bg-subtle px-3 pb-3 pt-2"
              >
                {/* 容器头只写模型名与本组条数。分组编号一个字都不露。 */}
                <header className="mb-2 flex items-center gap-2 text-[11px] text-text-muted">
                  <span>同一次回复</span>
                  {model ? (
                    <span className="rounded-full bg-bg-card px-2 py-[1px] font-mono">
                      {model}
                    </span>
                  ) : null}
                  <span className="font-mono">本组 {group.records.length} 条</span>
                </header>
                <div className="flex min-w-0 flex-col gap-2">
                  {group.records.map((record) => (
                    <RecordCard key={record.id} record={record} sessionId={sessionId} />
                  ))}
                </div>
              </section>
            );
          })}

          {loading ? (
            <p className="flex items-center justify-center gap-2 py-4 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              取记录中
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
