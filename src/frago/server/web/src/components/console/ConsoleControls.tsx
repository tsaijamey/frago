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
  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-scaled-4">
        {/* Session Status */}
        <div className="flex items-center gap-scaled-2">
          <div className={`w-2 h-2 rounded-full ${isRunning ? 'bg-[var(--accent-success)] animate-pulse' : 'bg-[var(--text-muted)]'}`} />
          <span className="text-scaled-sm text-[var(--text-muted)]">
            {sessionId ? `Session: ${sessionId.substring(0, 8)}...` : 'No active session'}
          </span>
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
              Stop
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost flex items-center gap-scaled-2"
              onClick={onNewSession}
              disabled={!sessionId}
            >
              <PlusCircle className="icon-scaled-sm" />
              New Session
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
