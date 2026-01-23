import { useTranslation } from 'react-i18next';
import { PlusCircle, Square } from 'lucide-react';

interface NewTaskControlsProps {
  sessionId: string | null;
  isRunning: boolean;
  onNewSession: () => void;
  onStop: () => void;
}

export default function NewTaskControls({
  sessionId,
  isRunning,
  onNewSession,
  onStop
}: NewTaskControlsProps) {
  const { t } = useTranslation();

  return (
    <div className="card">
      <div className="flex items-center justify-between gap-scaled-4">
        {/* Session Status - left */}
        <div className="flex items-center gap-scaled-2">
          <div className={`w-2 h-2 rounded-full ${isRunning ? 'bg-[var(--accent-success)] animate-pulse' : 'bg-[var(--text-muted)]'}`} />
          <span className="text-scaled-sm text-[var(--text-muted)]">
            {sessionId ? `${t('console.session')}: ${sessionId.substring(0, 8)}...` : t('console.noActiveSession')}
          </span>
        </div>

        {/* Right group: Action Buttons */}
        <div className="flex items-center gap-scaled-2">
          {isRunning ? (
            <button
              type="button"
              className="btn btn-ghost flex items-center gap-scaled-2 text-[var(--accent-error)]"
              onClick={onStop}
            >
              <Square className="icon-scaled-sm fill-current" />
              {t('console.stop')}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost flex items-center gap-scaled-2"
              onClick={onNewSession}
              disabled={!sessionId}
            >
              <PlusCircle className="icon-scaled-sm" />
              {t('console.newSession')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
