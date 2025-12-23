import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}

export default function Modal({ isOpen, onClose, title, children, footer }: ModalProps) {
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
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1100]"
      onClick={(e) => {
        // Close on backdrop click
        if (e.target === e.currentTarget) onClose();
      }}
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
