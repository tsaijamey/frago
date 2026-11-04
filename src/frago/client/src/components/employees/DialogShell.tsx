/**
 * 员工页两个弹窗共用的壳。
 *
 * **点遮罩不关窗**，与站内通用浮窗（`components/ui/Modal`）同一条规矩：这两个窗里都有
 * 人刚填进去的东西——打了一半的第一句话、挑好的目录、改到一半的岗位说明。鼠标在窗外多
 * 点一下全都不见，而且没有任何东西提示刚才发生了什么，更没有撤回的办法。关窗只有两个
 * 明确的动作：右上角的叉，或 Esc。
 *
 * 不复用 `Modal` 是因为宽度：那个壳固定 `max-w-md`，而这里要装业务语境原文与纳管目录
 * 清单，448px 装不下。高度也不一样——内容长了要能滚，但页头与页脚要钉住不动。
 */

import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface DialogShellProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** 窗口宽度上限（px）。语境预览要宽一些，编辑弹窗窄一些。 */
  width?: number;
  /** 关窗这件事此刻能不能做。起会话正起着一半时不让关，否则人看不到结果。 */
  closable?: boolean;
}

export default function DialogShell({
  title,
  onClose,
  children,
  footer,
  width = 520,
  closable = true,
}: DialogShellProps) {
  useEffect(() => {
    if (!closable) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [closable, onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[1100] flex items-start justify-center overflow-y-auto bg-black/50 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="my-8 flex max-h-[calc(100vh-4rem)] w-full flex-col rounded-lg border border-border-color bg-bg-base shadow-xl"
        style={{ maxWidth: `min(${width}px, 100%)` }}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border-color px-4 py-3">
          <h3 className="min-w-0 truncate text-[14px] font-semibold text-text-primary">{title}</h3>
          {closable ? (
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 text-text-muted transition-colors hover:text-text-primary"
              aria-label="Close"
            >
              <X size={18} strokeWidth={1.5} />
            </button>
          ) : null}
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-3.5">
          {children}
        </div>

        {footer ? (
          <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border-color px-4 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body
  );
}
