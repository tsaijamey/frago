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
 * 4. **看哪一类由人挑，条数照实报。** 一场会话里对话只占几十分之一，其余是工具、旁路
 *    注入和引擎记账。全都铺开是"什么都在"，也是"什么都找不着"。所以顶上给一排镜头，
 *    每一档带真实条数——**筛掉的东西必须在条数上看得见**，否则筛完像是那些事没发生过。
 */

import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type UIEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Inbox, Loader2 } from 'lucide-react';
import RecordCard, { KIND_GROUP } from './RecordCard';
import type { WorkbenchRecord } from '@/hooks/useWorkbenchRecords';

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
    return record.payload.source === 'hook' ? 'hook' : 'system';
  }
  return KIND_GROUP[record.kind] === 'tool' ? 'tool' : 'system';
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
  /** 刚投了一句话进去、还没见 agent 有任何动静。为真时流的末尾挂一条"在等"。 */
  awaitingAgent?: boolean;
}

export default function RecordStream({
  sessionId,
  records,
  loading,
  loadingOlder,
  hasOlder,
  error,
  onLoadOlder,
  awaitingAgent = false,
}: RecordStreamProps) {
  const { t } = useTranslation();
  const [lens, setLens] = useState<StreamLens>('all');

  /** 每一档各有几条。筛掉的也要报出真实条数，否则筛完像是那些事没发生过。 */
  const counts = useMemo(() => {
    const tally: Record<StreamLens, number> = {
      all: records.length,
      talk: 0,
      hook: 0,
      tool: 0,
      system: 0,
    };
    for (const record of records) tally[lensOf(record)] += 1;
    return tally;
  }, [records]);

  const visible = useMemo(
    () => (lens === 'all' ? records : records.filter((r) => lensOf(r) === lens)),
    [records, lens]
  );

  const groups = useMemo(() => groupRecords(visible), [visible]);

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
  }, [lens, scrollToBottom]);

  // "在等 agent 开口"那一条也是内容，它一冒出来就要看得见——跟着的人正是为了看它。
  // 人自己滚上去看别的时不打扰。
  useLayoutEffect(() => {
    if (awaitingAgent && followArmed.current) scrollToBottom('smooth');
  }, [awaitingAgent, scrollToBottom]);

  /** 人的滚动输入留下一张短期通行证：随后的 onScroll 按手动处理。 */
  const noteManualIntent = useCallback(() => {
    manualIntentUntil.current = Date.now() + MANUAL_INTENT_MS;
    // 人一伸手，程序那次滚动就作废——接下来的每一个事件都是人的，不许再被当成动画余波。
    programmaticUntil.current = 0;
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
        <p className="text-[13px]">{t('workbench.stream.pickSession')}</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      {records.length ? (
        <div
          data-testid="stream-lens"
          className="flex shrink-0 flex-wrap items-center gap-1 border-b border-border-color px-5 py-2"
        >
          {LENS_ORDER.map((id) => (
            <button
              key={id}
              type="button"
              onClick={() => setLens(id)}
              aria-pressed={lens === id}
              data-testid={`lens-${id}`}
              disabled={counts[id] === 0}
              /* 镜头是操作面，不是数据：选中态走中性填充加一档字重。
                 与左栏那两行筛选同一套写法——同一种东西在两个地方长得一样。 */
              className={`rounded-[6px] px-2 py-[3px] text-[11px] transition-colors duration-200 disabled:opacity-40 ${
                lens === id
                  ? 'bg-bg-active font-medium text-text-primary'
                  : 'text-text-muted hover:bg-bg-hover hover:text-text-secondary'
              }`}
            >
              {t(LENS_LABEL_KEY[id])}
              <span className="ml-1 font-mono opacity-60">{counts[id]}</span>
            </button>
          ))}
        </div>
      ) : null}

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        onWheel={noteManualIntent}
        onTouchMove={noteManualIntent}
        onKeyDown={handleKeyDown}
        onMouseDown={handleMouseDown}
        /* 滚动容器的内距契约：上 16 下 40。底下比上面厚，是因为滚到底那一刻最后一条
           不该被硬切在容器边框上，而输入框就压在下面。 */
        className="min-h-0 flex-1 overflow-y-auto px-5 pb-10 pt-4"
        data-testid="record-stream-scroll"
      >
        <div className="mx-auto flex w-full max-w-[760px] min-w-0 flex-col gap-3">
          {loadingOlder ? (
            <p className="flex items-center justify-center gap-2 py-2 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              {t('workbench.stream.loadingOlder')}
            </p>
          ) : null}

          {!hasOlder && records.length ? (
            <p className="py-2 text-center text-[11px] text-text-muted">
              {t('workbench.stream.streamStart', { n: records.length })}
            </p>
          ) : null}

          {error ? (
            <p className="rounded-[6px] bg-bg-subtle px-3 py-2 text-[12px] text-text-secondary">
              {error}
            </p>
          ) : null}

          {records.length && !visible.length ? (
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

          {groups.map((group, index) => {
            if (!group.groupId || group.records.length === 1) {
              return group.records.map((record) => (
                <RecordCard key={record.id} record={record} sessionId={sessionId} />
              ));
            }
            const model = modelOf(group.records);
            return (
              /* **归组不再是一个盒子。**
                 从前这里是一圈边加一层纸色，里面每张卡自己又是一圈边加一层纸色，
                 外面还有滚动容器的内距——一条工具输出要穿过四层内距才见得到字。
                 归组要表达的只是"下面这几条属于同一次回复"，一行小字标题加上紧一档的
                 行距就说清了；盒子不但没多说什么，还把每条记录的可用宽度削掉两回。 */
              <section
                key={`${group.groupId}-${index}`}
                data-testid="record-group"
                className="flex min-w-0 flex-col gap-1.5"
              >
                {/* 容器头只写模型名与本组条数。分组编号一个字都不露。 */}
                <header className="flex items-center gap-2 px-1 text-[11px] text-text-dim">
                  <span>{t('workbench.stream.sameReply')}</span>
                  {model ? <span className="font-mono">{model}</span> : null}
                  <span className="font-mono">
                    {t('workbench.stream.groupCount', { n: group.records.length })}
                  </span>
                  <span className="h-px flex-1 bg-border-color" />
                </header>
                {group.records.map((record) => (
                  <RecordCard key={record.id} record={record} sessionId={sessionId} />
                ))}
              </section>
            );
          })}

          {loading ? (
            <p className="flex items-center justify-center gap-2 py-4 text-[12px] text-text-muted">
              <Loader2 size={13} className="animate-spin" />
              {t('workbench.stream.loading')}
            </p>
          ) : null}

          {/* 从按下发送到第一条新记录落盘，中间隔着一次投喂加一轮冷启动。那段空窗里
              界面上一个字都不变，人只能猜「是没发出去还是它在想」。这一条就是答它。 */}
          {awaitingAgent ? (
            <p
              data-testid="awaiting-agent"
              className="flex items-center justify-center gap-2 py-3 text-[12px] text-text-muted"
            >
              <Loader2 size={13} className="animate-spin" />
              {t('workbench.stream.awaitingAgent')}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
