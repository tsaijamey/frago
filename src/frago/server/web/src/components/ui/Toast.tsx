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
