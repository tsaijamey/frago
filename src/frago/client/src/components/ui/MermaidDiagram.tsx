/**
 * 把一段 mermaid 源码画成图。
 *
 * 样式不在前端这边：`frago view`、`frago apps use mermaid` 也画同样的图，三处共用包内
 * `resources/viewer/mermaid/frago-theme.js` 这一份，NEVER 在这里另抄一套。
 *
 * **mermaid 不进主包。** 前端构建把所有代码打成一个文件，mermaid 12 本身有五百多万
 * 字节，塞进去等于让每一次打开界面都多解析四五倍的脚本——绝大多数页面一张图都没有。
 * 所以它作为独立文件随构建产出，第一次真遇到图时才用 `<script>` 取回来，之后整页复用。
 *
 * 渲染要排队：`mermaid.initialize` 是全局的，两张图同时画，后一张的主题会串到前一张上。
 * 画不出来时退回源码，并说一句为什么——代理还在往外吐字时图是半截的，这是常态，
 * 不当成报错渲染成红色。
 *
 * 图挤在会话栏那一列里，窄屏上字号被压得很小，所以角上留一个「放大查看」：点开是一个
 * 只看不填的浮窗，照 `sessionWorkbench/AttachedImages` 那个看图浮窗的规矩来——点遮罩、
 * 按 Esc、点叉都能关。浮窗里的图按它的自然宽度摆，比窗宽就横向滚、比窗高就纵向滚，
 * 滚动条是界面全局那一套细条，不另造。
 */

import { memo, useEffect, useId, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Maximize2, X } from 'lucide-react';
import type { Mermaid } from 'mermaid';
import mermaidUrl from 'mermaid/dist/mermaid.min.js?url';
// 普通脚本，加载时把 fragoMermaid 挂到全局上
import '../../../../resources/viewer/mermaid/frago-theme.js';

type DiagramTheme = 'dark' | 'light';

declare global {
  // eslint-disable-next-line no-var
  var fragoMermaid: {
    config: (mode: DiagramTheme) => Parameters<Mermaid['initialize']>[0];
    postProcess: (svg: SVGSVGElement) => void;
  };
}

let loading: Promise<Mermaid> | null = null;

function loadMermaid(): Promise<Mermaid> {
  const host = window as unknown as { mermaid?: Mermaid };
  if (host.mermaid) return Promise.resolve(host.mermaid);
  if (!loading) {
    loading = new Promise<Mermaid>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = mermaidUrl;
      script.async = true;
      script.onload = () =>
        host.mermaid ? resolve(host.mermaid) : reject(new Error('mermaid not found after load'));
      script.onerror = () => {
        // 放掉这次失败，下一张图还能再试
        loading = null;
        script.remove();
        reject(new Error('failed to load mermaid'));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}

let queue: Promise<unknown> = Promise.resolve();

function renderSerial(id: string, source: string, mode: DiagramTheme): Promise<string> {
  const job = queue.then(async () => {
    const mermaid = await loadMermaid();
    mermaid.initialize(globalThis.fragoMermaid.config(mode));
    try {
      const { svg } = await mermaid.render(id, source);
      return svg;
    } finally {
      // 解析失败时 mermaid 会在 body 上留下一个画着报错的临时节点
      document.getElementById(`d${id}`)?.remove();
    }
  });
  queue = job.catch(() => undefined);
  return job;
}

function useDocumentTheme(): DiagramTheme {
  const read = (): DiagramTheme =>
    document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  const [theme, setTheme] = useState<DiagramTheme>(read);
  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(read()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    return () => observer.disconnect();
  }, []);
  return theme;
}

// 代理边写边推时源码每几十毫秒变一次，等它停一停再画
const SETTLE_MS = 250;

/** 图的自然宽度（像素）。mermaid 配的是 `useMaxWidth: false`，尺寸写在 svg 自己的属性上；
 *  万一只有 viewBox，就拿 viewBox 的宽度兜底。取不到时返回 0，浮窗退回按窗宽铺满。 */
function naturalWidth(svg: SVGSVGElement): number {
  const own = Number(svg.getAttribute('width'));
  if (Number.isFinite(own) && own > 0) return own;
  const box = svg.viewBox?.baseVal;
  return box && box.width > 0 ? box.width : 0;
}

function MermaidDiagram({ source }: { source: string }) {
  const { t } = useTranslation();
  const theme = useDocumentTheme();
  const baseId = `mmd${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const seq = useRef(0);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);
  const [zoomWidth, setZoomWidth] = useState(0);
  const host = useRef<HTMLDivElement>(null);
  const zoomHost = useRef<HTMLDivElement>(null);

  const openZoom = () => {
    const el = host.current?.querySelector('svg');
    setZoomWidth(el ? naturalWidth(el) : 0);
    setZoomed(true);
  };

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      const id = `${baseId}-${seq.current++}`;
      renderSerial(id, source, theme).then(
        (out) => {
          if (cancelled) return;
          setSvg(out);
          setError(null);
        },
        (e: unknown) => {
          if (cancelled) return;
          setSvg(null);
          setError(e instanceof Error ? e.message : String(e));
        },
      );
    }, SETTLE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [baseId, source, theme]);

  useEffect(() => {
    const el = host.current?.querySelector('svg');
    if (el) globalThis.fragoMermaid.postProcess(el);
  }, [svg]);

  // 浮窗里是同一段 svg 的又一份拷贝，postProcess 补的样式得再走一遍（时序图的分组框靠它）。
  useEffect(() => {
    if (!zoomed) return;
    const el = zoomHost.current?.querySelector('svg');
    if (el) globalThis.fragoMermaid.postProcess(el);
  }, [zoomed, svg]);

  if (error) {
    return (
      <div className="my-2" data-testid="mermaid-fallback">
        <pre className="code-block">
          <code>{source}</code>
        </pre>
        <p className="mt-1 break-words text-[11px] text-text-muted">
          {t('common.diagramFailed', { reason: error })}
        </p>
      </div>
    );
  }

  return (
    <div className="group relative my-2">
      <div
        ref={host}
        data-testid="mermaid-diagram"
        className="flex justify-center overflow-x-auto rounded-[10px] border border-border-color bg-bg-secondary p-3.5 [&_svg]:h-auto [&_svg]:max-w-full"
        // mermaid 以 strict 安全级别渲染，输出的 SVG 已经过它自己的净化
        dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
      >
        {svg ? undefined : (
          <span className="py-6 text-[12px] text-text-muted">{t('common.diagramRendering')}</span>
        )}
      </div>
      {svg ? (
        <button
          type="button"
          data-testid="mermaid-zoom"
          onClick={openZoom}
          title={t('common.zoomDiagram')}
          aria-label={t('common.zoomDiagram')}
          className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md border border-border-color bg-bg-base px-2 py-1 text-[11px] text-text-muted opacity-70 transition-opacity hover:text-text-primary hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100"
        >
          <Maximize2 size={13} />
          {t('common.zoomDiagram')}
        </button>
      ) : null}
      {zoomed && svg ? (
        <DiagramViewer
          svg={svg}
          width={zoomWidth}
          title={t('common.diagramViewerTitle')}
          closeLabel={t('common.close')}
          hostRef={zoomHost}
          onClose={() => setZoomed(false)}
        />
      ) : null}
    </div>
  );
}

function DiagramViewer({
  svg,
  width,
  title,
  closeLabel,
  hostRef,
  onClose,
}: {
  svg: string;
  /** 图比这个宽度窄时铺满窗宽放大，比窗宽就按自然宽度横向滚。0 表示取不到，铺满。 */
  width: number;
  title: string;
  closeLabel: string;
  hostRef: RefObject<HTMLDivElement>;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div
      data-testid="mermaid-viewer"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 flex max-h-[88vh] w-[min(1280px,92vw)] flex-col overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-base)] shadow-xl">
        <header className="flex items-center gap-2 border-b border-[var(--border-color)] px-3 py-2">
          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-text-secondary">
            {title}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            title={closeLabel}
            className="shrink-0 text-text-muted hover:text-text-primary"
          >
            <X size={17} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto bg-bg-secondary p-4">
          <div
            ref={hostRef}
            style={width > 0 ? { minWidth: width } : undefined}
            className="mx-auto [&_svg]:h-auto [&_svg]:w-full [&_svg]:max-w-none"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>
    </div>,
    document.body
  );
}

export default memo(MermaidDiagram);
