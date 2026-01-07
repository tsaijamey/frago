import { useRef } from 'react';
import { Send } from 'lucide-react';
import { modKey } from '../../hooks/usePlatform';
import DirectoryAutocomplete from '../ui/DirectoryAutocomplete';

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
      <div className="task-input-wrapper relative">
        <DirectoryAutocomplete
          value={value}
          onChange={onChange}
          textareaRef={textareaRef}
        />
        <textarea
          ref={textareaRef}
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
