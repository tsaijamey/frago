/**
 * 站内通用浮窗。
 *
 * ## 点遮罩不关窗
 *
 * 这个浮窗从前点周围那片暗底就关掉了。听上去方便，代价是**人填到一半的东西说没就没**：
 * 新建会话里挑好的目录、打了一半的第一句话、配方密钥框里刚粘进去的那串钥匙——鼠标在窗
 * 外多点一下，全都不见，而且没有任何东西提示刚才发生了什么，更没有撤回的办法。
 *
 * 分界线在这里：**要人做决定或者要人填东西的浮窗，只能由人明确表示"我不要了"才关**——
 * 按右上角的叉，或者按 Esc。那两个动作都是冲着关窗去的，点窗外不是。
 *
 * 反过来，只是来报个信、不承载任何输入的东西（比如消息提示条 Toast），点哪都能打发掉
 * 才顺手，那类不走这个组件。真有信息类的东西要用这个壳，把 `dismissOnBackdrop` 打开，
 * 但打开之前先问一句：这窗里有没有一样东西是人输进去的。有，就不该开。
 */

import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  /**
   * 点窗外那片暗底算不算"关窗"。默认不算。
   *
   * 只有纯粹报信、人在里面什么都不用填的浮窗才该打开它。
   */
  dismissOnBackdrop?: boolean;
}

export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  footer,
  dismissOnBackdrop = false,
}: ModalProps) {
  // Escape key handler
  useEffect(() => {
    if (!isOpen) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Render to document.body using portal
  return createPortal(
    <div
      className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[1100]"
      onClick={
        dismissOnBackdrop
          ? (e) => {
              if (e.target === e.currentTarget) onClose();
            }
          : undefined
      }
    >
      <div className="bg-[var(--bg-base)] rounded-lg shadow-xl max-w-md w-full mx-4 border border-[var(--border-color)]">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--border-color)]">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            {title}
          </h3>
          <button
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            aria-label="Close modal"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-4">
          {children}
        </div>

        {/* Footer (optional) */}
        {footer && (
          <div className="flex gap-2 p-4 border-t border-[var(--border-color)]">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
