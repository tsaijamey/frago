import { RefObject } from 'react';
import { Terminal } from 'lucide-react';
import MessageItem from './MessageItem';
import type { ConsoleMessage } from '@/types/console';

interface MessageListProps {
  messages: ConsoleMessage[];
  messagesEndRef: RefObject<HTMLDivElement>;
}

export default function MessageList({ messages, messagesEndRef }: MessageListProps) {
  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] p-scaled-8">
        <div className="text-center">
          <Terminal size={48} strokeWidth={1.5} className="mx-auto mb-scaled-2 opacity-40" />
          <div className="text-scaled-lg mb-scaled-1">Console</div>
          <div className="text-scaled-sm">
            Start a conversation with Claude Code
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-scaled-4 space-y-4">
      {messages.map((msg, index) => (
        <MessageItem key={index} message={msg} />
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
}
