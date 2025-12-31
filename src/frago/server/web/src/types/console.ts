/**
 * Console message types and interfaces
 */

export interface ConsoleMessage {
  type: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';
  content: string;
  timestamp: string;
  tool_name?: string;
  tool_call_id?: string;
  metadata?: Record<string, unknown>;
  done?: boolean; // for streaming assistant messages
}
