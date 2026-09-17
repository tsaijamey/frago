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
 */

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { Quote } from 'lucide-react';

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

export interface SelectionQuoteProps {
  /** 记录流的滚动容器。只认圈在它里面的选区，别处（左栏、输入框）一概不管。 */
  containerRef: RefObject<HTMLElement>;
  /** 换会话时把按钮与高亮一起收掉——那段选区是在上一场里圈的。 */
  sessionId: string | null;
  /** 按了「引用」。交出去的是去掉首尾空白的原文。 */
  onQuote: (text: string) => void;
}

export default function SelectionQuote({ containerRef, sessionId, onQuote }: SelectionQuoteProps) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<string>('');
  const [spot, setSpot] = useState<{ left: number; top: number } | null>(null);
  // 按住拖的过程中不弹按钮：选区每动一下都会来一次通知，那时候摆出来它只会挡住正在选的字。
  const dragging = useRef(false);
  // 按钮自己那一块。手按下去的那一刻要先问一句「按的是不是它」——见下面 onPointerDown。
  const menu = useRef<HTMLDivElement>(null);

  const dropEcho = useCallback(() => {
    highlightBox()?.delete(ECHO_NAME);
  }, []);

  const clear = useCallback(() => {
    setPicked('');
    setSpot(null);
    dropEcho();
  }, [dropEcho]);

  /** 把选区读一遍：该不该给按钮、给在哪、要不要标绿。 */
  const sync = useCallback(() => {
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
    const ranges = echoRanges(root, text);
    if (!ranges.length) {
      box.delete(ECHO_NAME);
      return;
    }
    const Ctor = (window as unknown as { Highlight?: new (...r: Range[]) => unknown }).Highlight;
    if (!Ctor) return;
    box.set(ECHO_NAME, new Ctor(...ranges));
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

  return (
    <div
      ref={menu}
      data-testid="selection-quote"
      style={{ left: spot.left, top: spot.top }}
      className="fixed z-30 -translate-x-1/2 -translate-y-full"
    >
      <button
        type="button"
        data-testid="selection-quote-btn"
        // 按下去之前不许让选区消失：pointerdown 一旦落到按钮上，浏览器会先把记录流里的
        // 选区收掉，等到 click 时手上已经没有那段文字了。
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          onQuote(picked);
          document.getSelection()?.removeAllRanges();
          clear();
        }}
        /* 悬停不许换底色。`--bg-hover` 是一层半透明的白（深色主题）或黑（浅色主题），
           压在实心底色上才成立；这颗按钮浮在记录流上方，底色一换成它，按钮底下的正文
           就直接透上来跟按钮上的字叠在一起，两层字谁都读不清。悬停改由边框转成品牌色、
           字也跟着转来表达，底色自始至终是不透明的。 */
        className="flex items-center gap-1.5 rounded-[8px] border border-border-color bg-bg-card px-2.5 py-1 text-[12px] font-medium text-text-primary shadow-lg transition-colors hover:border-border-accent hover:bg-bg-elevated hover:text-accent-primary"
      >
        <Quote size={12} strokeWidth={1.8} />
        {t('workbench.stream.quote')}
      </button>
    </div>
  );
}
