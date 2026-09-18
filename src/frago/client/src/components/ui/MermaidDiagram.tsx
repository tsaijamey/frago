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
 */

import { memo, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
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

function MermaidDiagram({ source }: { source: string }) {
  const { t } = useTranslation();
  const theme = useDocumentTheme();
  const baseId = `mmd${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const seq = useRef(0);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);

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
    <div
      ref={host}
      data-testid="mermaid-diagram"
      className="my-2 flex justify-center overflow-x-auto rounded-[10px] border border-border-color bg-bg-secondary p-3.5 [&_svg]:h-auto [&_svg]:max-w-full"
      // mermaid 以 strict 安全级别渲染，输出的 SVG 已经过它自己的净化
      dangerouslySetInnerHTML={svg ? { __html: svg } : undefined}
    >
      {svg ? undefined : (
        <span className="py-6 text-[12px] text-text-muted">{t('common.diagramRendering')}</span>
      )}
    </div>
  );
}

export default memo(MermaidDiagram);
