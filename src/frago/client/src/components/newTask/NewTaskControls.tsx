import { useTranslation } from 'react-i18next';
import { Plus, Square } from 'lucide-react';

interface NewTaskControlsProps {
  isRunning: boolean;
  onNewSession: () => void;
  onStop: () => void;
}

export default function NewTaskControls({
  isRunning,
  onNewSession,
  onStop
}: NewTaskControlsProps) {
  const { t } = useTranslation();

  return (
    <div className="flex items-center justify-between">
      {/* Left: New Session button */}
      <button
        type="button"
        className="header-btn"
        onClick={onNewSession}
      >
        <Plus className="w-4 h-4" />
        <span>{t('console.newSession')}</span>
      </button>

      {/* Right: Stop button (only when running) */}
      {isRunning && (
        <button
          type="button"
          className="header-btn text-[var(--accent-error)]"
          onClick={onStop}
        >
          <Square className="w-4 h-4 fill-current" />
          <span>{t('console.stop')}</span>
        </button>
      )}
    </div>
  );
}
