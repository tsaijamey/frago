import { useTranslation } from 'react-i18next';
import { PlusCircle, Square } from 'lucide-react';

interface ConsoleControlsProps {
  sessionId: string | null;
  isRunning: boolean;
  onNewSession: () => void;
  onStop: () => void;
}

export default function ConsoleControls({
  sessionId,
  isRunning,
  onNewSession,
  onStop
}: ConsoleControlsProps) {
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

        {/* Right group: Auto-approve reminder + Action Buttons */}
        <div className="flex items-center gap-scaled-4">
          {/* Auto-approve indicator - reminds user before action */}
          <div className="flex items-center gap-scaled-2 opacity-60">
            <input
              id="auto-approve"
              type="checkbox"
              className="w-4 h-4 cursor-not-allowed"
              checked
              disabled
              aria-label={t('console.autoApprove')}
            />
            <label htmlFor="auto-approve" className="text-scaled-sm text-[var(--text-muted)] cursor-not-allowed">
              {t('console.autoApprove')}
            </label>
          </div>

          {/* Action Buttons */}
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
    </div>
  );
}
