import { useState } from 'react';
import { useTasks } from '@/hooks/useTasks';
import { startAgentTask } from '@/api/pywebview';
import TaskCard from './TaskCard';
import EmptyState from '@/components/ui/EmptyState';

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
      {/* 输入区域 */}
      <div className="task-input-wrapper">
        <textarea
          className="task-input"
          placeholder="描述你想要执行的任务..."
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
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
            </svg>
          )}
        </button>
      </div>

      {/* 任务列表 */}
      {tasks.length === 0 ? (
        <EmptyState
          icon="📋"
          title="暂无任务"
          description="输入任务描述开始你的第一个任务"
        />
      ) : (
        <div className="flex flex-col gap-2 flex-1 overflow-y-auto">
          {tasks.map((task) => (
            <TaskCard
              key={task.session_id}
              task={task}
              onClick={() => viewDetail(task.session_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
