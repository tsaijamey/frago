import { useState } from 'react';
import { useTasks } from '@/hooks/useTasks';
import { startAgentTask } from '@/api';
import { useAppStore } from '@/stores/appStore';
import TaskCard from './TaskCard';
import EmptyState from '@/components/ui/EmptyState';
import { Send, ClipboardList } from 'lucide-react';

export default function TaskList() {
  const { tasks, viewDetail, refresh } = useTasks();
  const { config, updateConfig } = useAppStore();
  const [prompt, setPrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const aiTitleEnabled = config?.ai_title_enabled ?? false;

  const handleSubmit = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isSubmitting) return;

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

  const handleAiTitleToggle = async (checked: boolean) => {
    await updateConfig({ ai_title_enabled: checked });
    // Refresh tasks to apply new setting
    refresh?.();
  };

  return (
    <div className="flex flex-col h-full">
      {/* AI Title Toggle */}
      <div className="flex items-center justify-end px-4 py-2 border-b border-gray-200 dark:border-gray-700">
        <label className="flex items-center gap-2 cursor-pointer text-sm text-gray-500 dark:text-gray-400">
          <input
            type="checkbox"
            checked={aiTitleEnabled}
            onChange={(e) => handleAiTitleToggle(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            aria-label="Enable AI title generation"
          />
          <span>Use haiku to generate readable titles</span>
        </label>
      </div>

      {/* Task List */}
      {tasks.length === 0 ? (
        <EmptyState
          Icon={ClipboardList}
          title="No Tasks"
          description="Enter a task description to start your first task"
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
        <div className="task-input-wrapper">
        <textarea
          className="task-input"
          placeholder="Describe the task you want to execute..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
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
