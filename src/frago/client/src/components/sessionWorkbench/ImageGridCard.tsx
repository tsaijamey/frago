/**
 * ImageGridCard — 会话内自适应屏幕宽度的图片网格卡片与点击放大浮窗。
 *
 * 由 `frago image` CLI 工具生成的 `frago_ui_component: "image-grid"` 数据驱动：
 * 1. **自适应屏幕网格布局**：按图片数量与视口断点自动切换 1~4 列网格（或按显式指定的
 *    `columns` 排列），单图保持完整画面比例展示，多图对齐成整洁的网格单元并附带图注。
 * 2. **点击放大浮窗预览**：点击任意图片弹出全屏半透明预览浮窗，支持 Esc / 点击暗底 / 关闭键
 *    退出，多图时支持左右方向键与前后按钮切换，并可在新标签页打开原图。
 * 3. **视觉守全局纪律**：卡片使用主题中性色（`bg-bg-card`、`border-border-color`），字号仅用
 *    11 / 12 / 13，不输出任何斜杠进度比值或百分比。
 */

import { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Image as ImageIcon,
  ImageOff,
  Maximize2,
  X,
} from 'lucide-react';
import type { ImageGridBlock, ImageGridItem } from '@/utils/imageGridBlock';

/**
 * 根据图片总数与可选的固定列数，返回自适应屏幕的 Tailwind Grid 列类名。
 */
export function resolveGridColsClass(count: number, columns: number | null): string {
  const target = columns ?? (count <= 1 ? 1 : count === 2 ? 2 : count === 3 ? 3 : 4);
  switch (target) {
    case 1:
      return 'grid-cols-1';
    case 2:
      return 'grid-cols-1 sm:grid-cols-2';
    case 3:
      return 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3';
    default:
      return count === 4 && columns === null
        ? 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4'
        : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';
  }
}

export default function ImageGridCard({ block }: { block: ImageGridBlock }) {
  const { t } = useTranslation();
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const { images, title, columns } = block;
  if (!images.length) return null;

  const single = images.length === 1 && columns !== 2 && columns !== 3 && columns !== 4;
  const gridCols = resolveGridColsClass(images.length, columns);

  return (
    <>
      <section
        data-testid="image-grid-card"
        data-columns={columns ?? 'auto'}
        className="mt-2.5 min-w-0 rounded-[10px] border border-border-color bg-bg-card p-3"
      >
        <header className="mb-2.5 flex items-center gap-2 text-[11px] text-text-muted">
          <ImageIcon size={13} className="shrink-0 text-text-secondary" />
          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-text-primary">
            {title || t('workbench.record.imageGrid.defaultTitle')}
          </span>
          <span className="shrink-0 rounded-full bg-bg-subtle px-2 py-[1px] font-mono text-[11px] text-text-muted">
            {t('workbench.record.imageGrid.count', { count: images.length })}
          </span>
        </header>

        <div
          data-testid="image-grid-layout"
          className={`grid gap-2.5 ${gridCols}`}
        >
          {images.map((item, idx) => (
            <ImageGridTile
              key={`${item.raw}-${idx}`}
              item={item}
              single={single}
              onOpen={() => setActiveIndex(idx)}
            />
          ))}
        </div>
      </section>

      {activeIndex !== null && images[activeIndex] ? (
        <ImageGridLightbox
          images={images}
          index={activeIndex}
          onChangeIndex={setActiveIndex}
          onClose={() => setActiveIndex(null)}
        />
      ) : null}
    </>
  );
}

function ImageGridTile({
  item,
  single,
  onOpen,
}: {
  item: ImageGridItem;
  single: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const [broken, setBroken] = useState(!item.src);
  const label = item.caption || item.name;

  return (
    <figure className="group flex min-w-0 flex-col overflow-hidden rounded-[8px] border border-border-color bg-bg-subtle transition-colors hover:border-text-muted">
      {broken || !item.src ? (
        <div
          data-testid="image-grid-item-missing"
          title={item.raw}
          className={`flex w-full flex-col items-center justify-center gap-1.5 px-3 text-text-dim ${
            single ? 'h-48' : 'aspect-[16/10]'
          }`}
        >
          <ImageOff size={20} strokeWidth={1.5} />
          <span className="text-[11px]">{t('workbench.record.imageGone')}</span>
          <span className="max-w-full truncate font-mono text-[11px] text-text-muted">
            {item.raw}
          </span>
        </div>
      ) : (
        <button
          type="button"
          data-testid="image-grid-item"
          title={item.raw}
          aria-label={t('workbench.record.openImage', { name: label })}
          onClick={onOpen}
          className="relative block w-full cursor-zoom-in overflow-hidden bg-bg-subtle text-left focus:outline-none"
        >
          <img
            src={item.src}
            alt={label}
            loading="lazy"
            onError={() => setBroken(true)}
            className={
              single
                ? 'mx-auto block max-h-[380px] w-full object-contain transition-transform duration-200 group-hover:scale-[1.01]'
                : 'aspect-[16/10] w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]'
            }
          />
          <span className="pointer-events-none absolute right-2 top-2 inline-flex items-center gap-1 rounded-[6px] bg-black/55 px-1.5 py-0.5 text-[11px] text-white opacity-0 transition-opacity duration-150 group-hover:opacity-100">
            <Maximize2 size={11} />
            <span>{t('workbench.record.imageGrid.zoomHint')}</span>
          </span>
        </button>
      )}
      <figcaption className="flex min-w-0 items-center justify-between gap-2 border-t border-border-color bg-bg-card px-2.5 py-1.5">
        <span
          className="min-w-0 flex-1 truncate text-[12px] leading-[1.45] text-text-secondary"
          title={label}
        >
          {label}
        </span>
      </figcaption>
    </figure>
  );
}

function ImageGridLightbox({
  images,
  index,
  onChangeIndex,
  onClose,
}: {
  images: ImageGridItem[];
  index: number;
  onChangeIndex: (next: number) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const current = images[index];
  const hasMultiple = images.length > 1;

  const goPrev = useCallback(() => {
    onChangeIndex((index - 1 + images.length) % images.length);
  }, [images.length, index, onChangeIndex]);

  const goNext = useCallback(() => {
    onChangeIndex((index + 1) % images.length);
  }, [images.length, index, onChangeIndex]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (hasMultiple && e.key === 'ArrowLeft') {
        goPrev();
      } else if (hasMultiple && e.key === 'ArrowRight') {
        goNext();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [goNext, goPrev, hasMultiple, onClose]);

  return createPortal(
    <div
      data-testid="image-grid-viewer"
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="mx-4 flex max-h-[88vh] max-w-[min(1080px,92vw)] flex-col overflow-hidden rounded-lg border border-[var(--border-color)] bg-[var(--bg-base)] shadow-xl">
        <header className="flex items-center gap-2 border-b border-[var(--border-color)] px-3 py-2">
          <div className="min-w-0 flex-1">
            {current.caption ? (
              <div className="truncate text-[12px] font-medium text-text-primary">
                {current.caption}
              </div>
            ) : null}
            <div
              className="truncate font-mono text-[11px] text-text-secondary"
              title={current.raw}
            >
              {current.raw}
            </div>
          </div>

          {hasMultiple ? (
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                data-testid="image-grid-prev"
                onClick={goPrev}
                aria-label={t('workbench.record.imageGrid.prev')}
                title={t('workbench.record.imageGrid.prev')}
                className="inline-flex h-6 w-6 items-center justify-center rounded-[6px] border border-border-color text-text-secondary hover:bg-bg-hover hover:text-text-primary"
              >
                <ChevronLeft size={14} />
              </button>
              <button
                type="button"
                data-testid="image-grid-next"
                onClick={goNext}
                aria-label={t('workbench.record.imageGrid.next')}
                title={t('workbench.record.imageGrid.next')}
                className="inline-flex h-6 w-6 items-center justify-center rounded-[6px] border border-border-color text-text-secondary hover:bg-bg-hover hover:text-text-primary"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          ) : null}

          {current.src ? (
            <a
              href={current.src}
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
            data-testid="image-grid-close"
            onClick={onClose}
            aria-label={t('common.close')}
            className="shrink-0 text-text-muted hover:text-text-primary"
          >
            <X size={17} />
          </button>
        </header>

        <div className="relative min-h-0 flex-1 overflow-auto p-3">
          <img
            data-testid="image-grid-viewer-img"
            src={current.src}
            alt={current.caption || current.name}
            className="mx-auto block max-h-[calc(88vh-68px)] max-w-full object-contain"
          />
        </div>
      </div>
    </div>,
    document.body
  );
}
