/**
 * FilePreview — 文件浏览器右半边那一栏：左边选中的那一份摆在这里。
 *
 * **按类分派，不按内容猜。** 图片、音视频、pdf 交给浏览器自己的标签去取（`<img>`、
 * `<video>`、`<iframe>`），它们比任何自绘的查看器都强，也不需要把字节搬进界面；
 * markdown、html 与其它文档交给服务端的 viewer 渲染，代码取回来在页面里染色。
 *
 * **markdown 为什么也交给服务端，而不是在页面里用那个现成的 markdown 组件摆。** 试过
 * 后者：文档里写的相对图片地址（`docs/images/logo.png` 这种）按界面的源去解，一律取不到，
 * 摆出来是一排破图；正文里内嵌的 HTML 也会被当成代码块原样显示。这两样在
 * `frago view` 那条路上都是对的（它把文件旁边的资源目录一起摆，按文件自己的基准解），
 * 所以这里不再自己摆一遍。
 *
 * **取不到就照实说。** 过大、不是文本、服务端不给，各是各的话。NEVER 摆半份当整份。
 *
 * 染色那一段与浮窗共用（`useHighlightedHtml`），不在这一侧再写一遍。
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { FileQuestion, Loader2 } from 'lucide-react';
import { absoluteUrl, prepareFileView, rawFileUrl } from '@/api';
import { langOf } from '@/components/sessionWorkbench/filePaths';
import { humanSize, useHighlightedHtml } from '@/components/sessionWorkbench/FileViewer';
import { kindOf } from './fileKind';

/** 当文本读回来的上限。过了这一档就不摆内容——读回来也没有人一行行看。 */
const MAX_TEXT_BYTES = 1024 * 1024;

export interface FilePreviewProps {
  /** 绝对路径，服务端认的就是这一份。 */
  path: string;
  name: string;
  /** 清单里报的字节数；目录为 null。 */
  size: number | null;
}

/** 取一份文件的文本。返回 `null` 文本表示这一份不是文本。 */
function useFileText(path: string, enabled: boolean) {
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setText(null);
    setError(null);
    setLoading(true);
    fetch(rawFileUrl(path))
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((body) => {
        if (!alive) return;
        // 头一段里有 NUL 就当它不是文本。服务端分「读不成文本」用的也是这条界线，
        // 界面这一侧认同一件事，别在两处各定一个说法。
        setText(body.slice(0, 4096).includes('\u0000') ? null : body);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [path, enabled]);

  return { text, loading, error };
}

/** 摆一段话的地方：四个角居中，图标在上。 */
function Notice({ icon, title, detail }: { icon: ReactNode; title: string; detail?: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-[12px] leading-relaxed text-text-muted">
      {icon}
      <span>{title}</span>
      {detail ? <span className="max-w-[380px] text-text-dim">{detail}</span> : null}
    </div>
  );
}

/** 交给服务端渲染的那几类（markdown、html）：先把这一份准备成 viewer 的一份，再嵌它那个页面。 */
function ViewerFrame({ path, name }: { path: string; name: string }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setUrl(null);
    setError(null);
    prepareFileView(path)
      .then((prep) => {
        if (alive) setUrl(absoluteUrl(prep.url));
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [path]);

  if (error) return <Notice icon={<FileQuestion size={28} strokeWidth={1.4} />} title={t('files.previewFailed')} detail={error} />;
  if (url === null)
    return (
      <p className="flex h-full items-center justify-center gap-2 text-[12px] text-text-muted">
        <Loader2 size={14} className="animate-spin" />
        {t('files.loadingContent')}
      </p>
    );
  return <iframe title={name} src={url} className="h-full w-full border-0 bg-bg-base" />;
}

/** 代码与认不出来的那些：取回正文，在页面里摆，跟界面主题走。 */
function TextPreview({ path, name }: { path: string; name: string }) {
  const { t } = useTranslation();
  const { text, loading, error } = useFileText(path, true);
  const lang = useMemo(() => langOf(name), [name]);
  const html = useHighlightedHtml(text, lang);

  if (error)
    return <Notice icon={<FileQuestion size={28} strokeWidth={1.4} />} title={t('files.previewFailed')} detail={error} />;
  if (loading)
    return (
      <p className="flex h-full items-center justify-center gap-2 text-[12px] text-text-muted">
        <Loader2 size={14} className="animate-spin" />
        {t('files.loadingContent')}
      </p>
    );
  if (text === null)
    return (
      <Notice
        icon={<FileQuestion size={28} strokeWidth={1.4} />}
        title={t('files.notText')}
        detail={t('files.binaryHint')}
      />
    );

  return (
    <pre className="h-full overflow-auto bg-bg-base p-4 font-mono text-[12px] leading-[1.6] text-text-secondary">
      {html !== null ? (
        <code className="hljs" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <code className="hljs">{text}</code>
      )}
    </pre>
  );
}

export default function FilePreview({ path, name, size }: FilePreviewProps) {
  const { t } = useTranslation();
  const kind = useMemo(() => kindOf(name), [name]);

  if (kind === 'image') {
    return (
      <div className="flex h-full items-center justify-center overflow-auto bg-bg-base p-4">
        <img src={rawFileUrl(path)} alt={name} className="max-h-full max-w-full object-contain" />
      </div>
    );
  }

  if (kind === 'video') {
    return (
      <div className="flex h-full items-center justify-center bg-bg-base p-4">
        <video src={rawFileUrl(path)} controls className="max-h-full max-w-full" />
      </div>
    );
  }

  if (kind === 'audio') {
    return (
      <div className="flex h-full items-center justify-center bg-bg-base p-4">
        <audio src={rawFileUrl(path)} controls className="w-[min(520px,100%)]" />
      </div>
    );
  }

  if (kind === 'pdf') {
    // pdf 走浏览器自带的阅读器：`disposition=inline` 不能省，带了 attachment 它就变成下载。
    return <iframe title={name} src={rawFileUrl(path)} className="h-full w-full border-0 bg-bg-base" />;
  }

  // markdown 与 html 都走服务端那条管线，理由写在文件头上。
  if (kind === 'html' || kind === 'markdown') return <ViewerFrame path={path} name={name} />;

  if (kind === 'binary') {
    return (
      <Notice
        icon={<FileQuestion size={28} strokeWidth={1.4} />}
        title={t('files.notText')}
        detail={t('files.binaryHint')}
      />
    );
  }

  if (size !== null && size > MAX_TEXT_BYTES) {
    return (
      <Notice
        icon={<FileQuestion size={28} strokeWidth={1.4} />}
        title={t('files.tooLarge', { size: humanSize(size) })}
      />
    );
  }

  return <TextPreview path={path} name={name} />;
}
