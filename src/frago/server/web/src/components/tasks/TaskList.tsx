import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useTasks } from '@/hooks/useTasks';
import { startAgentTask } from '@/api';
import TaskCard from './TaskCard';
import EmptyState from '@/components/ui/EmptyState';
import DirectoryAutocomplete from '@/components/ui/DirectoryAutocomplete';
import { recordDirectoriesFromText } from '@/utils/recentDirectories';
import { Send, ClipboardList } from 'lucide-react';

export default function TaskList() {
  const { t } = useTranslation();
  const { tasks, viewDetail, refresh } = useTasks();
  const [prompt, setPrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isSubmitting) return;

    // Record directories from the prompt
    recordDirectoriesFromText(trimmed);

    setIsSubmitting(true);
    try {
      const result = await startAgentTask(trimmed);
      if (result.status === 'ok') {
        setPrompt('');
        refresh?.();
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Task List */}
      {tasks.length === 0 ? (
        <EmptyState
          Icon={ClipboardList}
          title={t('tasks.noTasks')}
          description={t('tasks.noTasksDescription')}
        />
      ) : (
        <div className="page-scroll flex flex-col gap-2">
          {tasks.map((task) => (
            <TaskCard
              key={task.session_id}
              task={task}
              onClick={() => viewDetail(task.session_id)}
            />
          ))}
        </div>
      )}

      {/* Input Area - Fixed at Bottom */}
      <div className="task-input-area">
        <div className="task-input-wrapper relative">
          <DirectoryAutocomplete
            value={prompt}
            onChange={setPrompt}
            textareaRef={textareaRef}
          />
          <textarea
            ref={textareaRef}
            className="task-input"
            placeholder={t('tasks.inputPlaceholder')}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="Task prompt input"
          />
          <button
            type="button"
            className={`task-input-btn ${prompt.trim() ? 'visible' : ''}`}
            onClick={handleSubmit}
            disabled={isSubmitting || !prompt.trim()}
          >
            {isSubmitting ? (
              <div className="spinner" />
            ) : (
              <Send size={16} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
