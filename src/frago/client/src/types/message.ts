/**
 * Unified message type for both New Task and Task Detail pages.
 * Supports real-time streaming (New Task) and historical display (Task Detail).
 */

export type MessageType = 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';

export type MessageStatus = 'executing' | 'success' | 'error';

export interface UnifiedMessage {
  /** Unique identifier for the message */
  id: string;

  /** Message type */
  type: MessageType;

  /** Message content (text, JSON, or command output) */
  content: string;

  /** ISO timestamp */
  timestamp: string;

  /** Tool name (for tool_call and tool_result) */
  tool_name?: string;

  /** Tool call ID (for pairing tool_call with tool_result) */
  tool_call_id?: string;

  /** Additional metadata */
  metadata?: {
    status?: MessageStatus;
    result?: string | Record<string, unknown>;
    [key: string]: unknown;
  };

  /** Whether the message is complete (false = still streaming) */
  done?: boolean;
}

/**
 * Configuration for each message type's visual appearance
 */
export interface MessageTypeConfig {
  /** Display label key (for i18n) */
  labelKey: string;

  /** Avatar background color CSS variable */
  avatarColorVar: string;

  /** Avatar content (text or emoji) */
  avatarContent: string;

  /** Whether to use an icon instead of text (lucide icon name) */
  avatarIcon?: string;
}

/**
 * Convert ConsoleMessage to UnifiedMessage
 */
export function toUnifiedMessage(
  msg: {
    type: MessageType;
    content: string;
    timestamp: string;
    tool_name?: string;
    tool_call_id?: string;
    metadata?: Record<string, unknown>;
    done?: boolean;
  },
  index: number
): UnifiedMessage {
  return {
    id: `msg-${index}`,
    type: msg.type,
    content: msg.content,
    timestamp: msg.timestamp,
    tool_name: msg.tool_name,
    tool_call_id: msg.tool_call_id,
    metadata: msg.metadata as UnifiedMessage['metadata'],
    done: msg.done,
  };
}

/**
 * Convert TaskStep to UnifiedMessage
 */
export function taskStepToUnifiedMessage(step: {
  step_id: number;
  type: MessageType;
  timestamp: string;
  content: string;
  tool_name?: string | null;
  tool_status?: string | null;
  tool_call_id?: string;
}): UnifiedMessage {
  return {
    id: `step-${step.step_id}`,
    type: step.type,
    content: step.content,
    timestamp: step.timestamp,
    tool_name: step.tool_name ?? undefined,
    tool_call_id: step.tool_call_id,
    metadata: step.tool_status
      ? { status: step.tool_status as MessageStatus }
      : undefined,
    done: true, // TaskStep is always complete (historical data)
  };
}

export const MESSAGE_TYPE_CONFIG: Record<MessageType, MessageTypeConfig> = {
  user: {
    labelKey: 'messages.you',
    avatarColorVar: '--accent-primary',
    avatarContent: 'U',
  },
  assistant: {
    labelKey: 'messages.claude',
    avatarColorVar: '--accent-success',
    avatarContent: 'C',
  },
  tool_call: {
    labelKey: 'messages.tool',
    avatarColorVar: '--accent-warning',
    avatarContent: '\u{1F527}', // 🔧
  },
  tool_result: {
    labelKey: 'messages.result',
    avatarColorVar: '--accent-success',
    avatarContent: '\u2713', // ✓
  },
  system: {
    labelKey: 'messages.system',
    avatarColorVar: '--text-secondary',
    avatarContent: '',
    avatarIcon: 'settings',
  },
};
