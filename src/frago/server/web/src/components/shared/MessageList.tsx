import { useRef, useEffect, useCallback, type RefObject, type ReactNode } from 'react';
import type { UnifiedMessage } from '@/types/message';
import MessageCard from './MessageCard';

interface MessageListProps {
  messages: UnifiedMessage[];
  /** Whether to auto-scroll to the bottom when new messages arrive */
  autoScroll?: boolean;
  /** Whether to show typing indicator for streaming messages */
  showTypingIndicator?: boolean;
  /** Gap between messages (Tailwind class) */
  gap?: string;
  /** Callback when scroll position changes (for restoring scroll position) */
  onScrollChange?: (scrollTop: number) => void;
  /** Initial scroll position to restore */
  initialScrollPosition?: number;
  /** Class name for the container */
  className?: string;
  /** Ref for scrolling to the end of messages */
  messagesEndRef?: RefObject<HTMLDivElement>;
  /** Custom empty state component (shown when no messages) */
  emptyState?: ReactNode;
}

/**
 * Unified message list component for displaying conversation history.
 * Used by both New Task and Task Detail pages.
 * Supports auto-scrolling and scroll position restoration.
 */
export default function MessageList({
  messages,
  autoScroll = true,
  showTypingIndicator = true,
  gap = 'gap-scaled-5',
  onScrollChange,
  initialScrollPosition,
  className = '',
  messagesEndRef,
  emptyState,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isUserScrolling = useRef(false);
  const lastMessageCount = useRef(messages.length);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (!autoScroll || !containerRef.current) return;

    // Only auto-scroll if:
    // 1. New messages were added (not just content updates)
    // 2. User is not actively scrolling
    const hasNewMessages = messages.length > lastMessageCount.current;
    lastMessageCount.current = messages.length;

    if (hasNewMessages && !isUserScrolling.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, autoScroll]);

  // Restore initial scroll position
  useEffect(() => {
    if (initialScrollPosition !== undefined && containerRef.current) {
      containerRef.current.scrollTop = initialScrollPosition;
    }
  }, [initialScrollPosition]);

  // Track user scrolling
  const handleScroll = useCallback(() => {
    if (!containerRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;

    // User is scrolling if not near bottom
    isUserScrolling.current = !isNearBottom;

    // Report scroll position
    onScrollChange?.(scrollTop);
  }, [onScrollChange]);

  // Reset user scrolling flag when they scroll back to bottom
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.addEventListener('scroll', handleScroll);
    return () => container.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  if (messages.length === 0) {
    if (emptyState) {
      return <>{emptyState}</>;
    }
    return (
      <div className={`flex-1 flex items-center justify-center ${className}`}>
        <div className="text-[var(--text-muted)] text-scaled-sm">No messages yet</div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`flex-1 overflow-y-auto p-scaled-4 ${className}`}
    >
      <div className={`flex flex-col ${gap}`}>
        {messages.map((message) => (
          <MessageCard
            key={message.id}
            message={message}
            showTypingIndicator={showTypingIndicator}
          />
        ))}
        {messagesEndRef && <div ref={messagesEndRef} />}
      </div>
    </div>
  );
}
