/**
 * 人随一句话发过的图：一排缩略图，点开是一个看原图的小浮窗。
 *
 * 从前这里摆的是 agent 看的那段「[附带图片，…]」加一串绝对路径，人得自己去盘上翻才知道
 * 当时发的是哪张。缩略图跟输入框里待发那一排（`AttachmentStrip`）同一个尺寸与样子——
 * 发出去之前长什么样，发出去之后还是什么样。
 *
 * 浮窗只是看图，里面没有任何人要填的东西，所以点周围暗底、按 Esc、点右上角的叉都能关
 * （`Modal` 开头那段分界说的正是这一类）。
 *
 * 图取不回（文件被删了、或者这张不在 frago 的上传目录底下）时，缩略图换成一块写着
 * 「图片已不在」的灰块，路径放进悬停提示里——不藏，人还能照着路径去找。
 */

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { ExternalLink, ImageOff, X } from 'lucide-react';
import type { AttachedImageRef } from '@/utils/attachedImages';

export default function AttachedImages({ images }: { images: AttachedImageRef[] }) {
  const [open, setOpen] = useState<AttachedImageRef | null>(null);
  if (!images.length) return null;
  return (
    <>
      <div className="mt-2 flex flex-wrap gap-2" data-testid="attached-images">
        {images.map((image, i) => (
          <Thumb key={`${image.path}-${i}`} image={image} onOpen={() => setOpen(image)} />
        ))}
      </div>
      {open ? <Viewer image={open} onClose={() => setOpen(null)} /> : null}
    </>
  );
}

function Thumb({ image, onOpen }: { image: AttachedImageRef; onOpen: () => void }) {
  const { t } = useTranslation();
  const [broken, setBroken] = useState(!image.url);
  const box =
    'h-16 w-16 shrink-0 overflow-hidden rounded-[8px] border border-border-color bg-bg-subtle';

  if (broken || !image.url) {
    return (
      <div
        data-testid="attached-image-missing"
        title={image.path}
        className={`${box} flex flex-col items-center justify-center gap-1 text-text-dim`}
      >
        <ImageOff size={16} strokeWidth={1.5} />
        <span className="text-[10px]">{t('workbench.record.imageGone')}</span>
      </div>
    );
  }
  return (
    <button
      type="button"
      data-testid="attached-image"
      title={image.path}
      aria-label={t('workbench.record.openImage', { name: image.name })}
      onClick={onOpen}
      className={`${box} cursor-zoom-in hover:border-text-muted`}
    >
      <img
        src={image.url}
        alt={image.name}
        loading="lazy"
        onError={() => setBroken(true)}
        className="h-full w-full object-cover"
      />
    </button>
  );
}

function Viewer({ image, onClose }: { image: AttachedImageRef; onClose: () => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return createPortal(
    <div
      data-testid="attached-image-viewer"
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 flex max-h-[85vh] max-w-[min(960px,90vw)] flex-col overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-base)] shadow-xl">
        <header className="flex items-center gap-2 border-b border-[var(--border-color)] px-3 py-2">
          <span
            className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-secondary"
            title={image.path}
          >
            {image.path}
          </span>
          {image.url ? (
            <a
              href={image.url}
              target="_blank"
              rel="noreferrer"
              aria-label={t('workbench.record.openImageNewTab')}
              title={t('workbench.record.openImageNewTab')}
              className="shrink-0 text-text-muted hover:text-text-primary"
            >
              <ExternalLink size={15} />
            </a>
          ) : null}
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="shrink-0 text-text-muted hover:text-text-primary"
          >
            <X size={17} />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-2">
          <img
            src={image.url ?? ''}
            alt={image.name}
            className="mx-auto block max-h-[calc(85vh-60px)] max-w-full object-contain"
          />
        </div>
      </div>
    </div>,
    document.body
  );
}
