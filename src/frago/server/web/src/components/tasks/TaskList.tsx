import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useTasks } from '@/hooks/useTasks';
import { startAgentTask } from '@/api';
import TaskCard from './TaskCard';
import WelcomeScreen from './WelcomeScreen';
import DirectoryAutocomplete from '@/components/ui/DirectoryAutocomplete';
import { recordDirectoriesFromText } from '@/utils/recentDirectories';
import { Send } from 'lucide-react';

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

  const handleExampleClick = (examplePrompt: string) => {
    setPrompt(examplePrompt);
    textareaRef.current?.focus();
  };

  const inputArea = (
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
  );

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col h-full">
        <WelcomeScreen onExampleClick={handleExampleClick}>
          {inputArea}
        </WelcomeScreen>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="page-scroll flex flex-col gap-2">
        {tasks.map((task) => (
          <TaskCard
            key={task.session_id}
            task={task}
            onClick={() => viewDetail(task.session_id)}
          />
        ))}
      </div>
      <div className="task-input-area">{inputArea}</div>
    </div>
  );
}
