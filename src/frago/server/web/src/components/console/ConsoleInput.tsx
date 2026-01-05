import { Send } from 'lucide-react';
import { modKey } from '../../hooks/usePlatform';

interface ConsoleInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function ConsoleInput({
  value,
  onChange,
  onSend,
  disabled = false,
  placeholder = 'Type your message...'
}: ConsoleInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!disabled && value.trim()) {
        onSend();
      }
    }
  };

  return (
    <div>
      <div className="task-input-wrapper">
        <textarea
          className="task-input"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          aria-label="Message input"
        />
        <button
          type="button"
          className={`task-input-btn ${value.trim() ? 'visible' : ''}`}
          onClick={onSend}
          disabled={disabled || !value.trim()}
        >
          <Send className="icon-scaled-md" />
        </button>
      </div>
      <div className="text-scaled-xs text-[var(--text-muted)] mt-scaled-2">
        {modKey}+Enter to send
      </div>
    </div>
  );
}
