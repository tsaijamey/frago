import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getTaskDetail, continueAgentTask, generateTaskTitle } from '@/api';
import StepList from './StepList';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import DirectoryAutocomplete from '@/components/ui/DirectoryAutocomplete';
import Modal from '@/components/ui/Modal';
import { recordDirectoriesFromText } from '@/utils/recentDirectories';
import { Send, Info, Zap, ArrowLeft, RefreshCw } from 'lucide-react';
import { modKey } from '@/hooks/usePlatform';

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
  const { t } = useTranslation();
  const { taskDetail, isLoading, switchPage, setTaskDetail, showToast } = useAppStore();

  // Continue feature state
  const [continuePrompt, setContinuePrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Details modal state
  const [showDetailsModal, setShowDetailsModal] = useState(false);

  // Title generation state
  const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);

  // Whether can continue conversation (only completed and error status)
  const canContinue = taskDetail?.status === 'completed' || taskDetail?.status === 'error';

  // Generate AI title for the task
  const handleGenerateTitle = async () => {
    if (!taskDetail || isGeneratingTitle) return;

    setIsGeneratingTitle(true);
    try {
      const result = await generateTaskTitle(taskDetail.session_id);
      if (result.status === 'ok' && result.title) {
        // Update the task detail with new title
        setTaskDetail({ ...taskDetail, name: result.title });
        showToast(t('tasks.titleGenerated'), 'success');
      } else {
        showToast(result.error || t('tasks.titleGenerationFailed'), 'error');
      }
    } catch (error) {
      console.error('Failed to generate title:', error);
      showToast(t('tasks.titleGenerationFailed'), 'error');
    } finally {
      setIsGeneratingTitle(false);
    }
  };

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

  // Auto focus when page loads and can continue
  useEffect(() => {
    if (canContinue && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [canContinue]);

  // Continue conversation submit
  const handleContinueSubmit = async () => {
    const trimmed = continuePrompt.trim();
    if (!trimmed || isSubmitting || !taskDetail) return;

    // Record directories from the prompt
    recordDirectoriesFromText(trimmed);

    setIsSubmitting(true);
    try {
      const result = await continueAgentTask(taskDetail.session_id, trimmed);
      if (result.status === 'ok') {
        setContinuePrompt('');
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
        {t('tasks.taskNotExist')}
      </div>
    );
  }

  if (taskDetail.error) {
    return (
      <div className="text-[var(--accent-error)] text-center py-scaled-8">
        {t('tasks.failedToLoad')}: {taskDetail.error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 flex items-center gap-4 px-6 py-5">
        {/* Back button - icon only */}
        <button
          type="button"
          className="w-9 h-9 flex items-center justify-center rounded-lg bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] transition-colors shrink-0"
          onClick={() => switchPage('tasks')}
          aria-label={t('tasks.backToTaskList')}
        >
          <ArrowLeft className="w-[18px] h-[18px]" />
        </button>

        {/* Title */}
        <h2 className="text-lg font-semibold text-[var(--text-primary)] truncate max-w-[50%]">
          {taskDetail.name}
        </h2>

        {/* Generate AI title button */}
        <button
          type="button"
          className="text-[var(--text-muted)] hover:text-[var(--accent-primary)] transition-colors shrink-0"
          onClick={handleGenerateTitle}
          disabled={isGeneratingTitle}
          title={t('tasks.generateTitle')}
          aria-label={t('tasks.generateTitle')}
        >
          {isGeneratingTitle ? (
            <LoadingSpinner size="sm" />
          ) : (
            <Zap className="w-4 h-4" />
          )}
        </button>

        {/* Sync indicator (running status) */}
        {taskDetail.status === 'running' && (
          <RefreshCw className="w-4 h-4 text-[var(--text-muted)] animate-spin shrink-0" />
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Details button - pill style */}
        <button
          type="button"
          className="flex items-center gap-1.5 px-3 py-2 rounded-md bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] text-[13px] font-medium transition-colors shrink-0"
          onClick={() => setShowDetailsModal(true)}
        >
          <Info className="w-3.5 h-3.5" />
          {t('tasks.showDetails')}
        </button>
      </div>

      {/* Content area - message list */}
      <div className="flex-1 min-h-0 overflow-hidden px-6">
        <StepList
          sessionId={taskDetail.session_id}
          initialSteps={taskDetail.steps}
          totalSteps={taskDetail.steps_total}
          hasMore={taskDetail.has_more_steps}
          isRunning={taskDetail.status === 'running'}
        />
      </div>

      {/* Input area - at the very bottom */}
      {canContinue && (
        <div className="shrink-0 px-6 pt-4 pb-6">
          <div className="task-input-wrapper relative">
            <DirectoryAutocomplete
              value={continuePrompt}
              onChange={setContinuePrompt}
              textareaRef={textareaRef}
            />
            <textarea
              ref={textareaRef}
              className="task-input"
              placeholder={t('tasks.enterContinueContent')}
              value={continuePrompt}
              onChange={(e) => setContinuePrompt(e.target.value)}
              onKeyDown={handleContinueKeyDown}
              aria-label="Continue conversation input"
            />
            <button
              type="button"
              className={`task-input-btn ${continuePrompt.trim() ? 'visible' : ''}`}
              onClick={handleContinueSubmit}
              disabled={isSubmitting || !continuePrompt.trim()}
            >
              {isSubmitting ? (
                <div className="spinner" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>
          <div className="text-xs text-[var(--text-muted)] mt-2">
            {modKey}+Enter to send
          </div>
        </div>
      )}

      {/* Task details modal */}
      <Modal
        isOpen={showDetailsModal}
        onClose={() => setShowDetailsModal(false)}
        title={t('tasks.taskDetails')}
      >
        <div className="space-y-3 text-scaled-sm">
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">{t('tasks.statusLabel')}</span>
            <span className={`status-${taskDetail.status}`}>{taskDetail.status}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">{t('tasks.startTime')}</span>
            <span>{formatDateTime(taskDetail.started_at)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">{t('tasks.duration')}</span>
            <span>{formatDuration(taskDetail.duration_ms)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">{t('tasks.stepCount')}</span>
            <span>{taskDetail.step_count}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">{t('tasks.toolCalls')}</span>
            <span>{taskDetail.tool_call_count}</span>
          </div>
        </div>
      </Modal>
    </div>
  );
}
