import { useState } from 'react';
import { useTasks } from '@/hooks/useTasks';
import { startAgentTask } from '@/api';
import TaskCard from './TaskCard';
import EmptyState from '@/components/ui/EmptyState';
import { Send, ClipboardList } from 'lucide-react';

export default function TaskList() {
  const { tasks, viewDetail, refresh } = useTasks();
  const [prompt, setPrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

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

  return (
    <div className="flex flex-col h-full">
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
