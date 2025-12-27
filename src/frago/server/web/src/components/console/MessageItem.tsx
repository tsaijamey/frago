import type { ConsoleMessage } from './ConsolePage';
import BashContent from '../tasks/content/BashContent';
import JsonContent from '../tasks/content/JsonContent';

interface MessageItemProps {
  message: ConsoleMessage;
}

export default function MessageItem({ message }: MessageItemProps) {
  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  // User message
  if (message.type === 'user') {
    return (
      <div className="flex gap-scaled-3 items-start">
        <div className="w-8 h-8 rounded-full bg-[var(--accent-primary)] flex items-center justify-center text-white shrink-0 text-scaled-sm font-medium">
          U
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-scaled-2 mb-scaled-1">
            <span className="font-medium text-[var(--text-primary)]">You</span>
            <span className="text-scaled-xs text-[var(--text-muted)]">
              {formatTimestamp(message.timestamp)}
            </span>
          </div>
          <div className="text-[var(--text-primary)] whitespace-pre-wrap break-words">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  // Assistant message
  if (message.type === 'assistant') {
    return (
      <div className="flex gap-scaled-3 items-start">
        <div className="w-8 h-8 rounded-full bg-[var(--accent-success)] flex items-center justify-center text-white shrink-0 text-scaled-sm font-medium">
          C
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-scaled-2 mb-scaled-1">
            <span className="font-medium text-[var(--text-primary)]">Claude</span>
            <span className="text-scaled-xs text-[var(--text-muted)]">
              {formatTimestamp(message.timestamp)}
            </span>
            {!message.done && (
              <span className="text-scaled-xs text-[var(--accent-warning)]">typing...</span>
            )}
          </div>
          <div className="text-[var(--text-primary)] whitespace-pre-wrap break-words">
            {message.content}
            {!message.done && <span className="inline-block w-2 h-4 bg-[var(--accent-primary)] ml-1 animate-pulse" />}
          </div>
        </div>
      </div>
    );
  }

  // Tool call
  if (message.type === 'tool_call') {
    const isExecuting = message.metadata?.status === 'executing';
    return (
      <div className="flex gap-scaled-3 items-start">
        <div className="w-8 h-8 rounded-full bg-[var(--accent-warning)] flex items-center justify-center text-white shrink-0 text-scaled-sm font-medium">
          🔧
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-scaled-2 mb-scaled-1">
            <span className="font-medium text-[var(--text-primary)]">Tool: {message.tool_name}</span>
            <span className="text-scaled-xs text-[var(--text-muted)]">
              {formatTimestamp(message.timestamp)}
            </span>
            {isExecuting && (
              <span className="text-scaled-xs text-[var(--accent-warning)]">executing...</span>
            )}
          </div>
          <div className="bg-[var(--bg-elevated)] rounded p-scaled-3 border border-[var(--border-subtle)]">
            {message.tool_name === 'Bash' ? (
              <BashContent content={message.content} />
            ) : (
              <JsonContent content={message.content} />
            )}
          </div>
        </div>
      </div>
    );
  }

  // Tool result
  if (message.type === 'tool_result') {
    const isSuccess = message.metadata?.status === 'success';
    const result = message.metadata?.result || message.content;

    return (
      <div className="flex gap-scaled-3 items-start">
        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-white shrink-0 text-scaled-sm font-medium ${
          isSuccess ? 'bg-[var(--accent-success)]' : 'bg-[var(--accent-error)]'
        }`}>
          {isSuccess ? '✓' : '✗'}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-scaled-2 mb-scaled-1">
            <span className="font-medium text-[var(--text-primary)]">
              Result: {message.tool_name}
            </span>
            <span className="text-scaled-xs text-[var(--text-muted)]">
              {formatTimestamp(message.timestamp)}
            </span>
            <span className={`text-scaled-xs ${
              isSuccess ? 'text-[var(--accent-success)]' : 'text-[var(--accent-error)]'
            }`}>
              {isSuccess ? 'success' : 'error'}
            </span>
          </div>
          <div className="bg-[var(--bg-elevated)] rounded p-scaled-3 border border-[var(--border-subtle)] text-scaled-sm">
            <pre className="whitespace-pre-wrap break-words font-mono text-scaled-xs">
              {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    );
  }

  // System message
  return (
    <div className="flex justify-center">
      <div className="text-scaled-sm text-[var(--text-muted)] italic">
        {message.content}
      </div>
    </div>
  );
}
