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
 * 图挤在会话栏那一列里，窄屏上字号被压得很小，所以角上留一个「放大查看」：点开是始终占满
 * 视口 90%（`90vw × 90vh`，对标 Calendar / Timeline 浮窗契约）的全画布弹窗，点遮罩、按 Esc、
 * 点右上角关闭都能关。弹窗画布按 SVG 自然宽高与画布可用空间等比自适应居中放大，并支持缩放与拖拽。
 */

import {
  memo,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type RefObject,
  type WheelEvent as ReactWheelEvent,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Check, Code2, Copy, Download, Maximize2, Minus, Plus, RotateCcw, X } from 'lucide-react';
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

export const MIN_VIEWER_FIT_SCALE = 0.5;
export const MAX_VIEWER_FIT_SCALE = 2.5;
export const MIN_VIEWER_SCALE = 0.25;
export const MAX_VIEWER_SCALE = 4;

/**
 * 计算 90vw × 90vh 弹窗画布内流程图的自适应展示尺寸：
 * - 默认（zoomFactor = 1）按画布可用宽高与 SVG 自然宽高计算等比缩放倍率 fitScale（夹在 0.5× ~ 2.5×），
 *   让小流程图自动放大撑满画布且不破框、窄高流程图按高度受限等比居中而不纵向撑爆；
 * - 叠加用户手动缩放因子 zoomFactor 后夹在 [0.25×, 4×] 范围内。
 */
export function computeViewerStageDimensions(
  naturalW: number,
  naturalH: number,
  canvasW: number,
  canvasH: number,
  zoomFactor: number = 1,
): { width: number; height: number; fitScale: number; effectiveScale: number } {
  const baseW = naturalW > 0 ? naturalW : 640;
  const baseH = naturalH > 0 ? naturalH : 360;
  const availW = canvasW > 0 ? canvasW : 960;
  const availH = canvasH > 0 ? canvasH : 560;
  const rawFit = Math.min(availW / baseW, availH / baseH);
  const fitScale = Math.max(MIN_VIEWER_FIT_SCALE, Math.min(MAX_VIEWER_FIT_SCALE, rawFit));
  const factor = Number.isFinite(zoomFactor) && zoomFactor > 0 ? zoomFactor : 1;
  const effectiveScale = Math.max(MIN_VIEWER_SCALE, Math.min(MAX_VIEWER_SCALE, fitScale * factor));
  return {
    width: Math.max(1, Math.round(baseW * effectiveScale)),
    height: Math.max(1, Math.round(baseH * effectiveScale)),
    fitScale,
    effectiveScale,
  };
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
  'inline-flex items-center gap-1 rounded-md border border-border-color bg-bg-base px-2 py-0.5 text-[11px] text-text-muted transition-colors hover:text-text-primary';

function MermaidDiagram({ source }: { source: string }) {
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');
  const theme = useDocumentTheme();
  const baseId = `mmd${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const seq = useRef(0);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<'diag' | 'src'>('diag');
  const [zoomed, setZoomed] = useState(false);
  const [zoomNaturalSize, setZoomNaturalSize] = useState<{ width: number; height: number }>({
    width: 0,
    height: 0,
  });
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
    setZoomNaturalSize(el ? naturalSize(el) : { width: 0, height: 0 });
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
    if (mode !== 'diag') return;
    const el = host.current?.querySelector('svg');
    if (el) globalThis.fragoMermaid?.postProcess(el);
  }, [svg, mode]);

  // 浮窗里是同一段 svg 的又一份拷贝，postProcess 补的样式得再走一遍（时序图的分组框靠它）。
  useEffect(() => {
    if (!zoomed) return;
    const el = zoomHost.current?.querySelector('svg');
    if (el) globalThis.fragoMermaid?.postProcess(el);
  }, [zoomed, svg]);

  if (error) {
    return (
      <div className="my-2 min-w-0 max-w-full" data-testid="mermaid-fallback">
        <pre className="code-block min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          <code className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{source}</code>
        </pre>
        <p className="mt-1 break-words text-[11px] text-text-muted">
          {t('common.diagramFailed', { reason: error })}
        </p>
      </div>
    );
  }

  return (
    <div className="mmd-card group my-2" data-testid="mermaid-card">
      <div className="mmd-hd">
        <span>
          <b>Mermaid</b>
        </span>
        <div data-testid="mermaid-toolbar" className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            data-testid="mermaid-mode-toggle"
            onClick={() => setMode((m) => (m === 'diag' ? 'src' : 'diag'))}
            className={TOOLBAR_BTN_CLASS}
          >
            <Code2 size={13} />
            <span>
              {mode === 'src'
                ? isZh
                  ? '图形'
                  : 'Diagram'
                : isZh
                  ? '源码'
                  : 'Source'}
            </span>
          </button>
          {svg && mode === 'diag' ? (
            <>
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
            </>
          ) : null}
        </div>
      </div>
      {mode === 'src' ? (
        <pre
          className="mmd-src min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
          data-testid="mermaid-source"
        >
          <code className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{source}</code>
        </pre>
      ) : (
        <div
          ref={host}
          data-testid="mermaid-diagram"
          className="mermaid-diagram mmd-body flex justify-center overflow-x-auto [&_svg]:h-auto [&_svg]:max-w-full"
          // mermaid 以 strict 安全级别渲染，输出的 SVG 已经过它自己的净化
          dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
        >
          {svg ? undefined : (
            <span className="py-6 text-[12px] text-text-muted">{t('common.diagramRendering')}</span>
          )}
        </div>
      )}
      {zoomed && svg ? (
        <DiagramViewer
          svg={svg}
          naturalDims={zoomNaturalSize}
          isZh={Boolean(isZh)}
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
  naturalDims,
  isZh,
  title,
  closeLabel,
  hostRef,
  onClose,
}: {
  svg: string;
  naturalDims: { width: number; height: number };
  isZh: boolean;
  title: string;
  closeLabel: string;
  hostRef: RefObject<HTMLDivElement>;
  onClose: () => void;
}) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [zoomFactor, setZoomFactor] = useState(1);
  const [canvasSize, setCanvasSize] = useState<{ width: number; height: number }>(() => ({
    width: typeof window !== 'undefined' ? Math.max(320, Math.round(window.innerWidth * 0.9 - 48)) : 960,
    height: typeof window !== 'undefined' ? Math.max(240, Math.round(window.innerHeight * 0.9 - 96)) : 560,
  }));
  const [measuredSvgSize, setMeasuredSvgSize] = useState<{ width: number; height: number }>(
    naturalDims,
  );
  const dragState = useRef<{
    active: boolean;
    startX: number;
    startY: number;
    scrollLeft: number;
    scrollTop: number;
  }>({ active: false, startX: 0, startY: 0, scrollLeft: 0, scrollTop: 0 });

  const updateCanvasMetrics = useCallback(() => {
    const el = canvasRef.current;
    if (el && el.clientWidth > 0 && el.clientHeight > 0) {
      setCanvasSize({
        width: Math.max(160, el.clientWidth - 48),
        height: Math.max(120, el.clientHeight - 48),
      });
    } else if (typeof window !== 'undefined') {
      setCanvasSize({
        width: Math.max(160, Math.round(window.innerWidth * 0.9 - 48)),
        height: Math.max(120, Math.round(window.innerHeight * 0.9 - 96)),
      });
    }
  }, []);

  useEffect(() => {
    updateCanvasMetrics();
    window.addEventListener('resize', updateCanvasMetrics);
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined' && canvasRef.current) {
      ro = new ResizeObserver(() => updateCanvasMetrics());
      ro.observe(canvasRef.current);
    }
    return () => {
      window.removeEventListener('resize', updateCanvasMetrics);
      ro?.disconnect();
    };
  }, [updateCanvasMetrics]);

  useEffect(() => {
    const svgEl = hostRef.current?.querySelector('svg');
    if (!svgEl) return;
    const nat =
      naturalDims.width > 0 && naturalDims.height > 0 ? naturalDims : naturalSize(svgEl);
    if (nat.width > 0 && nat.height > 0) {
      setMeasuredSvgSize(nat);
      if (!svgEl.getAttribute('viewBox')) {
        svgEl.setAttribute('viewBox', `0 0 ${nat.width} ${nat.height}`);
      }
    }
    svgEl.style.maxWidth = 'none';
    svgEl.style.maxHeight = 'none';
    svgEl.style.width = '100%';
    svgEl.style.height = '100%';
  }, [svg, naturalDims, hostRef]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const effNatW = measuredSvgSize.width > 0 ? measuredSvgSize.width : naturalDims.width;
  const effNatH = measuredSvgSize.height > 0 ? measuredSvgSize.height : naturalDims.height;
  const stage = computeViewerStageDimensions(
    effNatW,
    effNatH,
    canvasSize.width,
    canvasSize.height,
    zoomFactor,
  );

  const adjustZoom = (delta: number) => {
    setZoomFactor((prev) => Math.max(0.25, Math.min(3, Math.round((prev + delta) * 100) / 100)));
  };

  const handleWheel = (e: ReactWheelEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      adjustZoom(e.deltaY < 0 ? 0.15 : -0.15);
    }
  };

  const handleMouseDown = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (e.button !== 0 || !canvasRef.current) return;
    dragState.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      scrollLeft: canvasRef.current.scrollLeft,
      scrollTop: canvasRef.current.scrollTop,
    };
  };

  const handleMouseMove = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (!dragState.current.active || !canvasRef.current) return;
    canvasRef.current.scrollLeft = dragState.current.scrollLeft - (e.clientX - dragState.current.startX);
    canvasRef.current.scrollTop = dragState.current.scrollTop - (e.clientY - dragState.current.startY);
  };

  const stopDrag = () => {
    dragState.current.active = false;
  };

  return createPortal(
    <div
      data-testid="mermaid-viewer"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="ui-modal-backdrop mmd-viewer-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        data-testid="mermaid-viewer-frame"
        className="ui-modal-frame mmd-viewer-frame"
        style={{
          width: '90vw',
          height: '90vh',
          maxWidth: '90vw',
          maxHeight: '90vh',
          boxSizing: 'border-box',
        }}
      >
        <header className="ui-modal-head">
          <span className="ui-modal-title">{title}</span>
          <div
            data-testid="mermaid-viewer-toolbar"
            className="ml-auto flex items-center gap-1.5"
          >
            <button
              type="button"
              data-testid="mermaid-viewer-zoom-out"
              onClick={() => adjustZoom(-0.25)}
              title={isZh ? '缩小' : 'Zoom out'}
              aria-label={isZh ? '缩小' : 'Zoom out'}
              className="flex h-7 w-7 items-center justify-center rounded-[6px] border border-border-color bg-bg-secondary text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
            >
              <Minus size={14} />
            </button>
            <button
              type="button"
              data-testid="mermaid-viewer-zoom-reset"
              onClick={() => setZoomFactor(1)}
              title={isZh ? '重置自适应比例' : 'Reset to fit'}
              aria-label={isZh ? '重置自适应比例' : 'Reset to fit'}
              className="inline-flex h-7 min-w-[58px] items-center justify-center gap-1 rounded-[6px] border border-border-color bg-bg-secondary px-2 font-mono text-[11.5px] tabular-nums text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
            >
              <span>{Math.round(stage.effectiveScale * 100)}%</span>
              {zoomFactor !== 1 ? <RotateCcw size={11} /> : null}
            </button>
            <button
              type="button"
              data-testid="mermaid-viewer-zoom-in"
              onClick={() => adjustZoom(0.25)}
              title={isZh ? '放大' : 'Zoom in'}
              aria-label={isZh ? '放大' : 'Zoom in'}
              className="flex h-7 w-7 items-center justify-center rounded-[6px] border border-border-color bg-bg-secondary text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
            >
              <Plus size={14} />
            </button>
            <button
              type="button"
              data-testid="mermaid-viewer-close"
              onClick={onClose}
              aria-label={closeLabel}
              title={closeLabel}
              className="ui-icon-btn ui-modal-close"
            >
              <X size={17} />
            </button>
          </div>
        </header>
        <div
          ref={canvasRef}
          data-testid="mermaid-viewer-canvas"
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={stopDrag}
          onMouseLeave={stopDrag}
          className="ui-modal-body ui-modal-body--flush mmd-viewer-canvas"
        >
          <div
            ref={hostRef}
            data-testid="mermaid-viewer-stage"
            style={{ width: `${stage.width}px`, height: `${stage.height}px` }}
            className="mmd-viewer-stage"
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>
    </div>,
    document.body
  );
}

export default memo(MermaidDiagram);
