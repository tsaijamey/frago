import { createPortal } from 'react-dom';
import { useAppStore, type ToastType } from '@/stores/appStore';

interface ToastProps {
  id: string;
  message: string;
  type: ToastType;
}

export default function Toast({ id, message, type }: ToastProps) {
  const { dismissToast } = useAppStore();

  return (
    <div className={`toast toast-${type}`} onClick={() => dismissToast(id)}>
      <span>{message}</span>
    </div>
  );
}

/**
 * 全局 Toast 容器：通过 Portal 挂载到 document.body，脱离 #root 内部任何局部层叠上下文，
 * 并配合 base.css 的 z-index: 1150 始终浮在全站浮窗（1100 / 1101）之上、断连遮罩（1200）之下。
 */
export function ToastContainer() {
  const toasts = useAppStore((s) => s.toasts);
  if (toasts.length === 0) return null;

  return createPortal(
    <div className="toast-container" data-testid="toast-container">
      {toasts.map((toast) => (
        <Toast key={toast.id} {...toast} />
      ))}
    </div>,
    document.body,
  );
}
