/**
 * FilePeek — 从别处点开一份文件时浮在上面的那一层。
 *
 * 会话记录流里圈中一段文字、按了那颗预览按钮，人就该**留在这一页**看到那份文件：翻到
 * 文件页去等于把刚读到的那一句丢下。所以这里是一层浮窗，右下角那一套与文件页右边一模一样
 * （`FilePreview`），不在这一侧再写一遍怎么摆。
 *
 * 与文件页的浮窗（`FileViewer`）不是一回事：那一个是会话文件清单上的一眼，带 ‹ › 逐份翻
 * 与改动对照，跟着清单走；这一份是从正文里蹦出来的单份，没有清单可翻。
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy, FolderOpen, X } from 'lucide-react';
import { revealPath } from '@/api';
import { baseOf, dirOf, withTilde } from '@/components/sessionWorkbench/filePaths';
import FilePreview from './FilePreview';

export interface FilePeekProps {
  /** 服务端解出来的绝对路径。 */
  path: string;
  /** 探针报的字节数；不知道时为 null。 */
  size: number | null;
  onClose: () => void;
}

export default function FilePeek({ path, size, onClose }: FilePeekProps) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  // Esc 关。挂着 document 上：焦点多半落在浮层里的某个按钮上，挂在窗口元素上会漏掉
  // 点过按钮之后的那几次按键（与文件页那个浮窗同一个做法）。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const iconBtn =
    'inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary';

  return (
    <div
      data-testid="file-peek"
      className="fixed inset-0 z-[80] flex items-center justify-center p-5"
      role="dialog"
      aria-modal="true"
      aria-label={baseOf(path)}
    >
      <div
        data-testid="file-peek-backdrop"
        className="absolute inset-0 bg-[var(--bg-overlay)]"
        onClick={onClose}
      />

      <div className="relative flex h-[min(76vh,680px)] w-[min(900px,100%)] flex-col overflow-hidden rounded-[12px] border border-border-strong bg-bg-primary shadow-2xl">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border-color px-3">
          <span className="min-w-0 flex-1 truncate font-mono text-[12px]">
            <span className="text-text-dim" title={dirOf(path)}>
              {withTilde(dirOf(path))}
            </span>
            <b className="ml-1 font-medium text-text-primary">{baseOf(path)}</b>
          </span>
          <button
            type="button"
            data-testid="file-peek-copy"
            title={t('files.copyPath')}
            aria-label={t('files.copyPath')}
            onClick={() => {
              void navigator.clipboard
                ?.writeText(path)
                .then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1_500);
                })
                .catch(() => {
                  /* 剪贴板不给用就算了 */
                });
            }}
            className={iconBtn}
          >
            {copied ? <Check size={14} className="text-accent-primary" /> : <Copy size={14} />}
          </button>
          <button
            type="button"
            data-testid="file-peek-reveal"
            title={t('files.reveal')}
            aria-label={t('files.reveal')}
            onClick={() => {
              void revealPath(path).catch(() => {
                /* 打不开（平台不支持、路径没了）：不打断人，右边那份内容还在 */
              });
            }}
            className={iconBtn}
          >
            <FolderOpen size={14} />
          </button>
          <button
            type="button"
            data-testid="file-peek-close"
            title={t('files.close')}
            aria-label={t('files.close')}
            onClick={onClose}
            className={iconBtn}
          >
            <X size={14} />
          </button>
        </div>

        <div className="min-h-0 flex-1">
          <FilePreview key={path} path={path} name={baseOf(path)} size={size} />
        </div>
      </div>
    </div>
  );
}
