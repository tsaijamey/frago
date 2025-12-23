import { useState, useEffect, useRef } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getTaskDetail, continueAgentTask } from '@/api';
import StepList from './StepList';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import { Send, MessageSquarePlus, ChevronDown, ChevronRight } from 'lucide-react';

// Format date time
function formatDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString('en-US', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// Format duration
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export default function TaskDetail() {
  const { taskDetail, isLoading, switchPage, setTaskDetail, showToast } = useAppStore();

  // Continue feature state
  const [showContinue, setShowContinue] = useState(false);
  const [continuePrompt, setContinuePrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Collapse state
  const [infoCollapsed, setInfoCollapsed] = useState(false);

  // Whether can continue conversation (only completed and error status)
  const canContinue = taskDetail?.status === 'completed' || taskDetail?.status === 'error';

  // Auto refresh detail (running status 3 seconds, other status 10 seconds)
  useEffect(() => {
    if (!taskDetail) return;

    const refreshInterval = taskDetail.status === 'running' ? 3000 : 10000;

    const refreshDetail = async () => {
      try {
        const updated = await getTaskDetail(taskDetail.session_id);
        setTaskDetail(updated);
      } catch (error) {
        console.error('Failed to refresh task detail:', error);
      }
    };

    const interval = setInterval(refreshDetail, refreshInterval);
    return () => clearInterval(interval);
  }, [taskDetail?.session_id, taskDetail?.status, setTaskDetail]);

  // Auto focus when input expands
  useEffect(() => {
    if (showContinue && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [showContinue]);

  // Continue conversation submit
  const handleContinueSubmit = async () => {
    const trimmed = continuePrompt.trim();
    if (!trimmed || isSubmitting || !taskDetail) return;

    setIsSubmitting(true);
    try {
      const result = await continueAgentTask(taskDetail.session_id, trimmed);
      if (result.status === 'ok') {
        setContinuePrompt('');
        setShowContinue(false);
        showToast('Continue conversation request sent', 'success');
        // Refresh detail to get new status
        const updated = await getTaskDetail(taskDetail.session_id);
        setTaskDetail(updated);
      } else {
        showToast(result.error || 'Send failed', 'error');
      }
    } catch (error) {
      console.error('Failed to continue task:', error);
      showToast('Send failed', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleContinueKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleContinueSubmit();
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!taskDetail) {
    return (
      <div className="text-[var(--text-muted)] text-center py-scaled-8">
        Task does not exist or has been deleted
      </div>
    );
  }

  if (taskDetail.error) {
    return (
      <div className="text-[var(--accent-error)] text-center py-scaled-8">
        Failed to load: {taskDetail.error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden gap-4 p-scaled-4">
      {/* Fixed header area */}
      <div className="shrink-0 flex flex-col gap-4">
        {/* Back button */}
        <button
          className="btn btn-ghost self-start"
          onClick={() => switchPage('tasks')}
        >
          ← Back to Task List
        </button>

        {/* Task info card - collapsible */}
        <div className="card">
          {/* Title row - click to collapse */}
          <div
            className="flex justify-between items-center cursor-pointer select-none"
            onClick={() => setInfoCollapsed(!infoCollapsed)}
          >
            <div className="flex items-center gap-scaled-2 flex-1 min-w-0">
              {infoCollapsed ? (
                <ChevronRight className="icon-scaled-md text-[var(--text-muted)] shrink-0" />
              ) : (
                <ChevronDown className="icon-scaled-md text-[var(--text-muted)] shrink-0" />
              )}
              <h2 className="text-scaled-lg font-medium text-[var(--text-primary)] truncate">
                {taskDetail.name}
              </h2>
              {/* Show status summary when collapsed */}
              {infoCollapsed && (
                <span className={`status-${taskDetail.status} text-scaled-sm ml-scaled-2 shrink-0`}>
                  {taskDetail.status}
                </span>
              )}
            </div>
            {/* Continue button - placed on the right of title */}
            {canContinue && !showContinue && (
              <button
                className="btn btn-primary flex items-center gap-scaled-2 ml-scaled-4 shrink-0"
                onClick={(e) => {
                  e.stopPropagation();
                  setShowContinue(true);
                }}
              >
                <MessageSquarePlus className="icon-scaled-md" />
                Continue Conversation
              </button>
            )}
            {/* Running status hint */}
            {taskDetail.status === 'running' && (
              <div className="flex items-center gap-scaled-2 text-scaled-sm text-[var(--accent-warning)] ml-scaled-4 shrink-0">
                <LoadingSpinner size="sm" />
                Running
              </div>
            )}
          </div>

          {/* Details - collapsible */}
          {!infoCollapsed && (
            <div className="space-y-2 text-scaled-sm mt-scaled-4">
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)]">Status</span>
                <span className={`status-${taskDetail.status}`}>{taskDetail.status}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)]">Start Time</span>
                <span>{formatDateTime(taskDetail.started_at)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)]">Duration</span>
                <span>{formatDuration(taskDetail.duration_ms)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)]">Step Count</span>
                <span>{taskDetail.step_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)]">Tool Calls</span>
                <span>{taskDetail.tool_call_count}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--text-muted)] shrink-0">Project Path</span>
                <span className="font-mono text-scaled-xs text-right break-all ml-scaled-4">{taskDetail.project_path}</span>
              </div>
            </div>
          )}
        </div>

        {/* Continue input area */}
        {showContinue && (
          <div className="card">
            <div className="task-input-wrapper">
              <textarea
                ref={textareaRef}
                className="task-input"
                placeholder="Enter content to continue the conversation..."
                value={continuePrompt}
                onChange={(e) => setContinuePrompt(e.target.value)}
                onKeyDown={handleContinueKeyDown}
              />
              <button
                className={`task-input-btn ${continuePrompt.trim() ? 'visible' : ''}`}
                onClick={handleContinueSubmit}
                disabled={isSubmitting || !continuePrompt.trim()}
              >
                {isSubmitting ? (
                  <div className="spinner" />
                ) : (
                  <Send className="icon-scaled-md" />
                )}
              </button>
            </div>
            <div className="text-scaled-xs text-[var(--text-muted)] mt-scaled-2">
              Ctrl+Enter to send ·
              <button
                className="text-[var(--accent-primary)] hover:underline ml-scaled-1"
                onClick={() => setShowContinue(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Step list area - takes remaining space, scrolls internally */}
      <div className="card flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between mb-scaled-3 shrink-0">
          <h3 className="font-medium text-[var(--accent-primary)]">
            Execution Steps
          </h3>
        </div>

        {/* StepList takes remaining space */}
        <div className="flex-1 min-h-0">
          <StepList steps={[...taskDetail.steps].reverse()} />
        </div>
      </div>
    </div>
  );
}
