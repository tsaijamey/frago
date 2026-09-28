/**
 * SelectionQuote — 在记录流里圈中一段文字之后冒出来的那个小按钮，以及「同字回声」。
 *
 * 人在记录流里读到一句要追问的话，从前只能自己复制、切到输入框、再手动打上引号。
 * 圈中文字就把「引用」递到手边，一按那句话连同引用格式落进输入框，光标停在接着说的
 * 位置上。
 *
 * 两条分野，按圈中的字数走：
 *
 * | 圈中 | 给什么 |
 * |---|---|
 * | 五个字及以上 | 只给「引用」按钮 |
 * | 不到五个字 | 「引用」按钮，外加把整条记录流里一模一样的文字全部标绿 |
 *
 * 短到三两个字的多半是个名字、一个编号、一个开关名——人圈它不是要引用，是想知道
 * 「这个词在这场会话里还出现在哪」。所以短选区额外点亮全部同字，长选区不点：整段话
 * 在别处不会重复出现，标出来只有一处，等于白闪一下。
 *
 * 三条实现上的约束：
 *
 * 1. **标绿不许碰 DOM。** 记录流里的正文是 markdown 渲染出来的树，往里插标签会把它
 *    拆开——代码块、链接、表格都可能当场变形，而且 React 下一次渲染又会把插进去的
 *    东西抹掉。这里走 CSS 自定义高亮（`CSS.highlights`）：只递交一组文本范围，浏览器
 *    自己把那几段涂绿，DOM 一个字不动。浏览器不认这套就不标，按钮照常给。
 * 2. **拖选过程中不弹按钮。** 圈选是按住拖的，选区每动一下都会触发一次变更；拖到
 *    一半就把按钮摆出来，它会一路跟着鼠标跑，还会挡住正在选的字。松手才算数。
 * 3. **按钮贴着选区，跟着滚。** 位置按选区此刻的屏幕矩形算，滚动容器一滚就重算；
 *    选区滚出视野就把按钮收起来，高亮留着——人正是滚下去看别处那几个绿字的。
 *
 * **「暂存」与「引用」并排，都只留图标。** 代理一次列出好几个待决的点，人更愿意一条一条
 * 答；暂存把圈中的那段先放进右栏下半的列表，过会儿再逐条填进输入框。圈选那一刻对这段话
 * 的判断最清楚，所以点了暂存就在原地展开一个小框写想法——不强制，回车留空也存。点外面
 * 算作不存。两个按钮只画图标，名字在悬停时给：两颗带字的按钮浮在正文上，挡住的字比
 * 它们要引的那段还多。
 *
 * **标注要能在刷新之后找回原处。** 暂存与引用都会记下「圈选起点在哪一条记录里、这段文字
 * 在那一条里是第几次出现」（见 {@link markAnchor}）。找回时用同一套算法（见
 * {@link findMarkRange}），记下与找回永远对得上。只认正文类记录（挂着 `data-record-body`
 * 的那一层）：选区起点不在任何正文里时不给暂存，引用照旧。
 */

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Layers, Quote } from 'lucide-react';

/** 这套高亮在浏览器里的名字，与 `globals.css` 里 `::highlight()` 那条选择器同名。 */
const ECHO_NAME = 'workbench-quote-echo';

/** 圈中不到这么多字，才额外把同字全标绿。 */
export const ECHO_MAX_CHARS = 5;

/** 一次最多标这么多处。真有一个词出现上千次，标完只会糊成一片，也白耗一帧。 */
const ECHO_LIMIT = 400;

/** 按钮与选区之间留的空隙。 */
const MENU_GAP = 8;

interface HighlightBox {
  set(name: string, value: unknown): void;
  delete(name: string): void;
}

/** 浏览器认不认 CSS 自定义高亮。不认就只给按钮，不标绿。 */
function highlightBox(): HighlightBox | null {
  const api = (CSS as unknown as { highlights?: HighlightBox }).highlights;
  return api ?? null;
}

/**
 * 记录流里几套高亮谁压谁：同字标绿 > 没用过的暂存 > 引用（含用过的暂存）。
 *
 * 跳回原处时「闪一下」压在所有人上面：它只亮一瞬，那一瞬就是要人一眼找到落点。
 */
export const HIGHLIGHT_PRIORITY = {
  flash: 4,
  echo: 3,
  stack: 2,
  quote: 1,
} as const;

/** 按名字交一组范围给浏览器去涂；空的就把这个名字撤掉。浏览器不认这套就什么都不做。 */
export function paintHighlight(name: string, ranges: Range[], priority: number): void {
  const box = highlightBox();
  if (!box) return;
  if (!ranges.length) {
    box.delete(name);
    return;
  }
  const Ctor = (window as unknown as { Highlight?: new (...r: Range[]) => { priority?: number } })
    .Highlight;
  if (!Ctor) return;
  const highlight = new Ctor(...ranges);
  highlight.priority = priority;
  box.set(name, highlight);
}

/**
 * 在这棵树里找出所有一模一样的文字，交回它们各自的范围。
 *
 * 逐个文本节点找，所以跨标签断开的那几处（比如 `他**说**了`里的「说了」）找不到。
 * 这里认的是「一个词在别处原样又出现一次」，那种被行内标记切断的写法不在其中。
 */
export function echoRanges(root: Node, needle: string): Range[] {
  const found: Range[] = [];
  if (!needle) return found;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    const text = node.nodeValue ?? '';
    let from = text.indexOf(needle);
    while (from !== -1) {
      const range = document.createRange();
      range.setStart(node, from);
      range.setEnd(node, from + needle.length);
      found.push(range);
      if (found.length >= ECHO_LIMIT) return found;
      from = text.indexOf(needle, from + needle.length);
    }
    node = walker.nextNode();
  }
  return found;
}

// ── 标注的锚点：记下与找回 ────────────────────────────────────────────────

/** 正文类记录外面那一层的记号。只在这一层里记锚点、着色、找原处。 */
export const RECORD_BODY_ATTR = 'data-record-body';

/** 一段标注在记录流里的位置：哪一条记录、这段文字、在那一条里第几次出现。 */
export interface MarkAnchor {
  record_id: string;
  text: string;
  occurrence: number;
}

/**
 * 一条记录铺平之后的正文，**去掉全部空白**，外加每个字落在哪个文本节点的第几位。
 *
 * 去空白是因为两边拿到的字不是同一种写法：圈选时交出来的是浏览器按版面拼的选区文本，
 * 段与段、列表项之间会多出换行；找回时读的是文本节点，那里没有这些换行。两边都去掉
 * 空白再比，markdown 的分段、缩进、代码块的换行就都对得上了。代价是「a b」与「ab」算
 * 同一段——标注只是定位，这点模糊可以接受。
 */
export interface FlatText {
  text: string;
  nodes: Text[];
  /** 第 i 个字在 `nodes` 里的哪一个。 */
  nodeAt: number[];
  /** 第 i 个字在那个节点里的第几位。 */
  offsetAt: number[];
}

const SPACE = /\s/;

export function squeeze(text: string): string {
  return text.replace(/\s+/g, '');
}

export function flatten(root: Node): FlatText {
  const nodes: Text[] = [];
  const nodeAt: number[] = [];
  const offsetAt: number[] = [];
  let text = '';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode() as Text | null;
  while (node) {
    const value = node.nodeValue ?? '';
    const index = nodes.length;
    nodes.push(node);
    for (let i = 0; i < value.length; i += 1) {
      if (SPACE.test(value[i])) continue;
      text += value[i];
      nodeAt.push(index);
      offsetAt.push(i);
    }
    node = walker.nextNode() as Text | null;
  }
  return { text, nodes, nodeAt, offsetAt };
}

/** 去空白之后，`needle` 在 `hay` 里每一处出现的起点。 */
function starts(hay: string, needle: string): number[] {
  const found: number[] = [];
  if (!needle) return found;
  let from = hay.indexOf(needle);
  while (from !== -1) {
    found.push(from);
    from = hay.indexOf(needle, from + 1);
  }
  return found;
}

export function rangeOf(flat: FlatText, from: number, to: number): Range {
  const range = document.createRange();
  range.setStart(flat.nodes[flat.nodeAt[from]], flat.offsetAt[from]);
  range.setEnd(flat.nodes[flat.nodeAt[to - 1]], flat.offsetAt[to - 1] + 1);
  return range;
}

/** 跨记录的选区只在起点那条里着色：起点那条的尾巴正好是这段文字的开头，至少这么多字才算。 */
const TAIL_MIN_CHARS = 2;

/**
 * 在这条记录里找回一段标注，交回它的范围；找不到交回 null。
 *
 * 1. 第 `occurrence` 次出现就是它。出现的次数不够（记录被改写过），算找不到。
 * 2. 整段一次都没出现：多半是跨记录圈的，这段文字只有开头落在这一条的末尾。那就找
 *    「这段文字最长的开头，恰好是这一条的结尾」，着那一截。
 */
export function findMarkRange(root: Node, text: string, occurrence: number): Range | null {
  const flat = flatten(root);
  const span = markSpan(flat, text, occurrence);
  return span ? rangeOf(flat, span[0], span[1]) : null;
}

/** 与 {@link findMarkRange} 同一个规矩，交回的是铺平之后的起止位置 `[from, to)`。 */
export function markSpan(flat: FlatText, text: string, occurrence: number): [number, number] | null {
  const needle = squeeze(text);
  if (!needle) return null;
  const hits = starts(flat.text, needle);
  if (hits.length) {
    const at = hits[occurrence];
    return at === undefined ? null : [at, at + needle.length];
  }
  const hay = flat.text;
  for (let p = Math.max(0, hay.length - needle.length + 1); p <= hay.length - TAIL_MIN_CHARS; p += 1) {
    if (hay[p] !== needle[0]) continue;
    if (needle.startsWith(hay.slice(p))) return [p, hay.length];
  }
  return null;
}

/**
 * 这个选区的锚点：起点落在哪一条正文记录里，这段文字在那一条里是第几次出现。
 *
 * 起点不在记录流的任何正文里时交回 null——暂存按钮就不给。
 */
export function markAnchor(container: Node, range: Range, text: string): MarkAnchor | null {
  const start =
    range.startContainer.nodeType === Node.ELEMENT_NODE
      ? (range.startContainer as Element)
      : range.startContainer.parentElement;
  const body = start?.closest(`[${RECORD_BODY_ATTR}]`);
  const recordId = body?.getAttribute('data-record-id');
  if (!body || !recordId || !container.contains(body)) return null;
  // 起点之前那一截有多少个非空白字——与 findMarkRange 同一把尺子量。
  const before = document.createRange();
  before.setStart(body, 0);
  before.setEnd(range.startContainer, range.startOffset);
  const offset = squeeze(before.toString()).length;
  const hits = starts(flatten(body).text, squeeze(text));
  const occurrence = hits.filter((at) => at < offset).length;
  return {
    record_id: recordId,
    text,
    occurrence: hits.length ? Math.min(occurrence, hits.length - 1) : 0,
  };
}

export interface SelectionQuoteProps {
  /** 记录流的滚动容器。只认圈在它里面的选区，别处（左栏、输入框）一概不管。 */
  containerRef: RefObject<HTMLElement>;
  /** 换会话时把按钮与高亮一起收掉——那段选区是在上一场里圈的。 */
  sessionId: string | null;
  /**
   * 按了「引用」。交出去的是去掉首尾空白的原文；选区起点落在正文记录里时，一并交出
   * 锚点，好让页面把这次引用记成一条标注。
   */
  onQuote: (text: string, anchor?: MarkAnchor) => void;
  /** 按了「暂存」并写完（或跳过）想法。不给就不画暂存按钮。 */
  onStack?: (anchor: MarkAnchor, note: string) => void;
}

export default function SelectionQuote({
  containerRef,
  sessionId,
  onQuote,
  onStack,
}: SelectionQuoteProps) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<string>('');
  const [anchor, setAnchor] = useState<MarkAnchor | null>(null);
  const [spot, setSpot] = useState<{ left: number; top: number } | null>(null);
  /** 点了暂存、正在写想法。这时选区已经让给了输入框，不许再按选区收摊。 */
  const [noting, setNoting] = useState(false);
  const notingRef = useRef(false);
  const [note, setNote] = useState('');
  // 按住拖的过程中不弹按钮：选区每动一下都会来一次通知，那时候摆出来它只会挡住正在选的字。
  const dragging = useRef(false);
  // 按钮自己那一块。手按下去的那一刻要先问一句「按的是不是它」——见下面 onPointerDown。
  const menu = useRef<HTMLDivElement>(null);

  const dropEcho = useCallback(() => {
    highlightBox()?.delete(ECHO_NAME);
  }, []);

  const clear = useCallback(() => {
    setPicked('');
    setAnchor(null);
    setSpot(null);
    setNoting(false);
    notingRef.current = false;
    setNote('');
    dropEcho();
  }, [dropEcho]);

  /** 把选区读一遍：该不该给按钮、给在哪、要不要标绿。 */
  const sync = useCallback(() => {
    // 正在写想法：焦点在输入框里，选区早就不在记录流里了，这时读选区只会把框收掉。
    if (notingRef.current) return;
    const root = containerRef.current;
    const selection = document.getSelection();
    if (!root || !selection || selection.rangeCount === 0 || selection.isCollapsed) {
      clear();
      return;
    }
    const range = selection.getRangeAt(0);
    if (!root.contains(range.commonAncestorContainer)) {
      clear();
      return;
    }
    const text = selection.toString().trim();
    if (!text) {
      clear();
      return;
    }

    const rect = range.getBoundingClientRect();
    const view = root.getBoundingClientRect();
    // 选区被滚出记录流的可视范围了：按钮收起来，绿字留着。
    const inView = rect.bottom > view.top && rect.top < view.bottom;
    setPicked(text);
    setAnchor(markAnchor(root, range, text));
    setSpot(
      inView
        ? {
            left: Math.min(Math.max(rect.left + rect.width / 2, 56), window.innerWidth - 56),
            top: Math.max(rect.top - MENU_GAP, MENU_GAP + 24),
          }
        : null
    );

    const box = highlightBox();
    if (!box) return;
    // 短选区才点亮同字。长选区在别处不会原样重现，标出来只有自己这一处。
    if ([...text].length >= ECHO_MAX_CHARS) {
      box.delete(ECHO_NAME);
      return;
    }
    // 同字标绿压在引用、暂存的底色上面：人此刻圈它，就是想看它还出现在哪。
    paintHighlight(ECHO_NAME, echoRanges(root, text), HIGHLIGHT_PRIORITY.echo);
  }, [clear, containerRef]);

  useEffect(() => {
    const onSelectionChange = () => {
      if (dragging.current) return;
      sync();
    };
    const onPointerDown = (e: PointerEvent) => {
      // **按在按钮上的那一下不算新一轮圈选。** 手按下去先于点击生效，这里若照常收摊，
      // 按钮在点击送达之前就从界面上消失了，那一下点在空处——症状正是「按了引用什么都
      // 没发生」，而且按钮一闪而过，人根本看不出它是被自己按没的。
      if (e.target instanceof Node && menu.current?.contains(e.target)) return;
      dragging.current = true;
      // 新一轮圈选开始，上一轮的按钮与绿字当场退场——留着会让人以为它说的是现在这一段。
      clear();
    };
    const onPointerUp = () => {
      dragging.current = false;
      // 松手那一刻选区才定下来，让浏览器把这一轮的选区变更走完再读。
      setTimeout(sync, 0);
    };
    const onViewChange = () => {
      if (dragging.current) return;
      sync();
    };

    document.addEventListener('selectionchange', onSelectionChange);
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('pointerup', onPointerUp);
    // 滚动事件不冒泡，只有在捕获阶段才收得到记录流那一层滚出来的那些。
    window.addEventListener('scroll', onViewChange, true);
    window.addEventListener('resize', onViewChange);
    return () => {
      document.removeEventListener('selectionchange', onSelectionChange);
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('scroll', onViewChange, true);
      window.removeEventListener('resize', onViewChange);
    };
  }, [clear, sync]);

  // 换会话、或这块走了：绿字必须一起走。它挂在浏览器上，不随 React 的树消失。
  useEffect(() => clear, [clear, sessionId]);

  if (!picked || !spot) return null;

  const done = () => {
    document.getSelection()?.removeAllRanges();
    clear();
  };

  /** 暂存落定：想法去掉首尾空白，留空就是不写。 */
  const stack = () => {
    if (anchor && onStack) onStack(anchor, note.trim());
    done();
  };

  /* 实心品牌绿，32px 见方，与 Send 同一种写法（字色走 --text-on-accent，两套主题各有
     答案）。「每屏至多一个实心绿」不管这两颗：它们只在圈选松手后出现，那一刻人手要点的
     就是它们，是这一瞬间的主动作（主人 09-28 定，例外写在原型 design-notes.md）。
     从前是中性浮层底加细边，跟记录流底色太近，浮在正文上认不出按钮在哪。
     悬停不许换成半透明底色（`--bg-hover` 压上去，底下的正文会透上来跟图标叠在一起），
     只提一档亮度，底色自始至终不透明。 */
  const iconBtn =
    'flex h-8 w-8 items-center justify-center rounded-[8px] bg-accent-primary text-[var(--text-on-accent)] shadow-lg transition-[filter] hover:brightness-110';

  return (
    <div
      ref={menu}
      data-testid="selection-quote"
      style={{ left: spot.left, top: spot.top }}
      className="fixed z-30 -translate-x-1/2 -translate-y-full"
    >
      {noting ? (
        <form
          data-testid="selection-stack-note"
          onSubmit={(e) => {
            e.preventDefault();
            stack();
          }}
          className="flex w-[280px] max-w-[80vw] items-center gap-1.5 rounded-[10px] border border-border-color bg-bg-card p-1.5 shadow-lg"
        >
          <Layers size={13} strokeWidth={1.8} className="ml-1 shrink-0 text-accent-warning" />
          <input
            autoFocus
            data-testid="selection-stack-input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              // Esc 也存：点了暂存就是要记下这一段，想法只是附带的；不想存的人点外面。
              if (e.key === 'Escape') {
                e.preventDefault();
                stack();
              }
            }}
            placeholder={t('workbench.stream.stackNotePlaceholder')}
            aria-label={t('workbench.stream.stackNotePlaceholder')}
            className="min-w-0 flex-1 bg-transparent px-1 text-[12px] text-text-primary outline-none placeholder:text-text-muted"
          />
          <button
            type="submit"
            data-testid="selection-stack-save"
            className="shrink-0 rounded-[6px] border border-border-color px-2 py-[2px] text-[11px] text-text-secondary transition-colors hover:border-border-accent hover:text-accent-primary"
          >
            {t('workbench.stream.stackNoteSave')}
          </button>
        </form>
      ) : (
        <div className="flex items-center gap-1">
          <button
            type="button"
            data-testid="selection-quote-btn"
            title={t('workbench.stream.quote')}
            aria-label={t('workbench.stream.quote')}
            // 按下去之前不许让选区消失：pointerdown 一旦落到按钮上，浏览器会先把记录流里的
            // 选区收掉，等到 click 时手上已经没有那段文字了。
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              if (anchor) onQuote(picked, anchor);
              else onQuote(picked);
              done();
            }}
            className={iconBtn}
          >
            <Quote size={15} strokeWidth={1.9} />
          </button>
          {onStack && anchor ? (
            <button
              type="button"
              data-testid="selection-stack-btn"
              title={t('workbench.stream.stack')}
              aria-label={t('workbench.stream.stack')}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                notingRef.current = true;
                setNoting(true);
              }}
              className={iconBtn}
            >
              <Layers size={15} strokeWidth={1.9} />
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}
