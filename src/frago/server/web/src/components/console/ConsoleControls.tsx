import { PlusCircle, Square } from 'lucide-react';

interface ConsoleControlsProps {
  sessionId: string | null;
  isRunning: boolean;
  autoApprove: boolean;
  onNewSession: () => void;
  onStop: () => void;
}

export default function ConsoleControls({
  sessionId,
  isRunning,
  autoApprove,
  onNewSession,
  onStop
}: ConsoleControlsProps) {
  return (
    <div className="card">
      <div className="flex flex-wrap items-center gap-scaled-4">
        {/* Session Status */}
        <div className="flex items-center gap-scaled-2">
          <div className={`w-2 h-2 rounded-full ${isRunning ? 'bg-[var(--accent-success)] animate-pulse' : 'bg-[var(--text-muted)]'}`} />
          <span className="text-scaled-sm text-[var(--text-muted)]">
            {sessionId ? `Session: ${sessionId.substring(0, 8)}...` : 'No active session'}
          </span>
        </div>

        {/* Auto-approve Toggle (always enabled, not editable) */}
        <div className="flex items-center gap-scaled-2 opacity-60">
          <input
            id="auto-approve"
            type="checkbox"
            className="w-4 h-4 cursor-not-allowed"
            checked={autoApprove}
            disabled
            aria-label="Auto-approve tools (always enabled)"
          />
          <label htmlFor="auto-approve" className="text-scaled-sm text-[var(--text-muted)] cursor-not-allowed">
            Auto-approve
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
