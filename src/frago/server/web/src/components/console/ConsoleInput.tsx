import { Send } from 'lucide-react';

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
    <div className="card">
      <div className="flex gap-scaled-3 items-end">
        <textarea
          className="flex-1 resize-none bg-transparent border-none outline-none text-[var(--text-primary)] placeholder-[var(--text-muted)] font-sans text-scaled-base p-0"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={3}
          aria-label="Message input"
        />
        <button
          type="button"
          className="btn btn-primary flex items-center gap-scaled-2 shrink-0"
          onClick={onSend}
          disabled={disabled || !value.trim()}
        >
          <Send className="icon-scaled-sm" />
          Send
        </button>
      </div>
      <div className="text-scaled-xs text-[var(--text-muted)] mt-scaled-2">
        Ctrl+Enter to send
      </div>
    </div>
  );
}
