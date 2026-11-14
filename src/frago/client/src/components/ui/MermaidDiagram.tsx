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
import { Check, Copy, Download, Maximize2, X } from 'lucide-react';
import type { Mermaid } from 'mermaid';
import mermaidUrl from 'mermaid/dist/mermaid.min.js?url';
// 普通脚本，加载时把 fragoMermaid 挂到全局上
import '../../../../resources/viewer/mermaid/frago-theme.js';

export type DiagramTheme = 'dark' | 'light';

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

/** 图的自然宽高（逻辑像素）。mermaid 配的是 `useMaxWidth: false`，优先读 viewBox 与数值型 width/height；
 *  万一写成百分比（如 `width="100%"`），会落到 viewBox 或实测包围盒上。 */
export function naturalSize(svg: SVGSVGElement): { width: number; height: number } {
  const ownW = Number(svg.getAttribute('width'));
  const ownH = Number(svg.getAttribute('height'));
  const vbAttr = svg.getAttribute('viewBox');
  let vbW = 0;
  let vbH = 0;
  if (vbAttr) {
    const parts = vbAttr
      .trim()
      .split(/[\s,]+/)
      .map(Number);
    if (
      parts.length === 4 &&
      Number.isFinite(parts[2]) &&
      parts[2] > 0 &&
      Number.isFinite(parts[3]) &&
      parts[3] > 0
    ) {
      vbW = parts[2];
      vbH = parts[3];
    }
  }
  if ((vbW <= 0 || vbH <= 0) && svg.viewBox?.baseVal) {
    if (svg.viewBox.baseVal.width > 0) vbW = svg.viewBox.baseVal.width;
    if (svg.viewBox.baseVal.height > 0) vbH = svg.viewBox.baseVal.height;
  }
  const rect = typeof svg.getBoundingClientRect === 'function' ? svg.getBoundingClientRect() : null;
  const width =
    Number.isFinite(ownW) && ownW > 0 ? ownW : vbW > 0 ? vbW : rect && rect.width > 0 ? rect.width : 0;
  const height =
    Number.isFinite(ownH) && ownH > 0 ? ownH : vbH > 0 ? vbH : rect && rect.height > 0 ? rect.height : 0;
  return { width, height };
}

function naturalWidth(svg: SVGSVGElement): number {
  return naturalSize(svg).width;
}

/**
 * 导出成 PNG 的尺寸规格：
 * - 至少 2× 矢量超采样（Retina 下跟随 ceil(devicePixelRatio)），让 14px 节点字和 11.5px 边标签
 *   在位图里至少达到 28px / 23px 物理像素，笔画边缘不发虚；
 * - 窄小流程图自动把倍率抬到使输出总宽 ≥ 1600px（最高封顶 4×），避免三四个节点的小图导出后
 *   贴到聊天窗或文档里被二次拉大而糊掉；
 * - 四周留 24px（逻辑像素）同主题实心底色留白（深色 #1a1a1a / 浅色 #f7f7f7），防止圆角框描边贴边被裁、
 *   以及深色图的浅色字落在透明底上看不清；
 * - 单边硬上限 8192px，守住浏览器 Canvas 硬件纹理上限。
 */
export const MIN_EXPORT_WIDTH = 1600;
export const MIN_EXPORT_SCALE = 2;
export const MAX_EXPORT_SCALE = 4;
export const MAX_CANVAS_SIDE = 8192;
export const EXPORT_PADDING = 24;

export function computeExportDimensions(
  naturalW: number,
  naturalH: number,
  dpr: number = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1,
): { width: number; height: number; scale: number; pad: number } {
  const baseW = Math.max(1, naturalW);
  const baseH = Math.max(1, naturalH);
  const contentWithPadW = baseW + EXPORT_PADDING * 2;
  const contentWithPadH = baseH + EXPORT_PADDING * 2;
  const neededForMinWidth = MIN_EXPORT_WIDTH / contentWithPadW;
  const rawScale = Math.max(MIN_EXPORT_SCALE, Math.ceil(dpr || 1), neededForMinWidth);
  const maxAllowedScale = Math.min(
    MAX_EXPORT_SCALE,
    MAX_CANVAS_SIDE / contentWithPadW,
    MAX_CANVAS_SIDE / contentWithPadH,
  );
  const scale = Math.max(1, Math.min(rawScale, maxAllowedScale));
  const width = Math.round(contentWithPadW * scale);
  const height = Math.round(contentWithPadH * scale);
  const pad = Math.round(EXPORT_PADDING * scale);
  return { width, height, scale, pad };
}

export async function renderSvgToPngBlob(
  svg: SVGSVGElement,
  theme: DiagramTheme,
): Promise<Blob> {
  const { width: natW, height: natH } = naturalSize(svg);
  const baseW = natW > 0 ? natW : 800;
  const baseH = natH > 0 ? natH : 600;
  const { width, height, scale, pad } = computeExportDimensions(baseW, baseH);
  const drawW = Math.round(baseW * scale);
  const drawH = Math.round(baseH * scale);

  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  if (!clone.getAttribute('viewBox')) {
    clone.setAttribute('viewBox', `0 0 ${baseW} ${baseH}`);
  }
  clone.setAttribute('width', String(drawW));
  clone.setAttribute('height', String(drawH));
  clone.style.maxWidth = 'none';
  clone.style.width = `${drawW}px`;
  clone.style.height = `${drawH}px`;
  // mermaid 内置的 stylis 会把 themeCSS 里的 `foreignObject` 转成全小写 `foreignobject`，
  // 在 HTML 文档里大小写不敏感能命中，但序列化成独立 XML (`image/svg+xml`) 后大小写敏感会失效，
  // 导致悬在段落左侧的状态记号（✓ / ● / !）被默认 overflow 裁掉。这里显式补在节点上。
  clone.querySelectorAll('foreignObject').forEach((fo) => {
    fo.setAttribute('overflow', 'visible');
    fo.style.overflow = 'visible';
  });

  const xml = new XMLSerializer().serializeToString(clone);
  const dataUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;

  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.decoding = 'sync';
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('failed to rasterize diagram svg'));
    image.src = dataUrl;
  });

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('canvas 2d context unavailable');

  ctx.fillStyle = theme === 'light' ? '#f7f7f7' : '#1a1a1a';
  ctx.fillRect(0, 0, width, height);
  ctx.drawImage(img, pad, pad, drawW, drawH);

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('canvas toBlob returned null'));
    }, 'image/png');
  });
}

const TOOLBAR_BTN_CLASS =
  'inline-flex items-center gap-1 rounded-md border border-border-color bg-bg-base px-2 py-1 text-[11px] text-text-muted opacity-70 transition-opacity hover:text-text-primary hover:opacity-100 focus-visible:opacity-100 group-hover:opacity-100';

function MermaidDiagram({ source }: { source: string }) {
  const { t } = useTranslation();
  const theme = useDocumentTheme();
  const baseId = `mmd${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const seq = useRef(0);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);
  const [zoomWidth, setZoomWidth] = useState(0);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<number | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const zoomHost = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    };
  }, []);

  const openZoom = () => {
    const el = host.current?.querySelector('svg');
    setZoomWidth(el ? naturalWidth(el) : 0);
    setZoomed(true);
  };

  const copyImage = async () => {
    const el = host.current?.querySelector('svg');
    if (!el || !navigator.clipboard?.write) return;
    const blobPromise = renderSvgToPngBlob(el, theme);
    try {
      if (typeof ClipboardItem !== 'undefined') {
        try {
          await navigator.clipboard.write([
            new ClipboardItem({ 'image/png': blobPromise }),
          ]);
        } catch {
          const blob = await blobPromise;
          await navigator.clipboard.write([
            new ClipboardItem({ 'image/png': blob }),
          ]);
        }
      }
      setCopied(true);
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
      copyTimer.current = window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // 剪贴板被拒或不可用时静默回退
    }
  };

  const downloadImage = async () => {
    const el = host.current?.querySelector('svg');
    if (!el) return;
    try {
      const blob = await renderSvgToPngBlob(el, theme);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `diagram-${Date.now()}.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      // 导出失败时静默回退
    }
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
        className="mermaid-diagram flex justify-center overflow-x-auto rounded-[10px] border border-border-color bg-bg-secondary px-3.5 pb-3.5 pt-10 [&_svg]:h-auto [&_svg]:max-w-full"
        // mermaid 以 strict 安全级别渲染，输出的 SVG 已经过它自己的净化
        dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
      >
        {svg ? undefined : (
          <span className="py-6 text-[12px] text-text-muted">{t('common.diagramRendering')}</span>
        )}
      </div>
      {svg ? (
        <div
          data-testid="mermaid-toolbar"
          className="absolute right-2 top-2 flex items-center gap-1"
        >
          <button
            type="button"
            data-testid="mermaid-copy"
            onClick={copyImage}
            title={copied ? t('common.diagramCopied') : t('common.copyDiagram')}
            aria-label={copied ? t('common.diagramCopied') : t('common.copyDiagram')}
            className={TOOLBAR_BTN_CLASS}
          >
            {copied ? <Check size={13} /> : <Copy size={13} />}
            {copied ? t('common.diagramCopied') : t('common.copyDiagram')}
          </button>
          <button
            type="button"
            data-testid="mermaid-download"
            onClick={downloadImage}
            title={t('common.downloadDiagram')}
            aria-label={t('common.downloadDiagram')}
            className={TOOLBAR_BTN_CLASS}
          >
            <Download size={13} />
            {t('common.downloadDiagram')}
          </button>
          <button
            type="button"
            data-testid="mermaid-zoom"
            onClick={openZoom}
            title={t('common.zoomDiagram')}
            aria-label={t('common.zoomDiagram')}
            className={TOOLBAR_BTN_CLASS}
          >
            <Maximize2 size={13} />
            {t('common.zoomDiagram')}
          </button>
        </div>
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
      className="ui-modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="ui-modal-frame ui-modal-frame--wide">
        <header className="ui-modal-head">
          <span className="ui-modal-title">{title}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            title={closeLabel}
            className="ui-icon-btn ui-modal-close"
          >
            <X size={17} />
          </button>
        </header>
        <div className="ui-modal-body ui-modal-body--flush">
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
