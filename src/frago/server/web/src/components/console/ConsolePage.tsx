import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import ConsoleControls from './ConsoleControls';
import MessageList from './MessageList';
import ConsoleInput from './ConsoleInput';

export interface ConsoleMessage {
  type: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';
  content: string;
  timestamp: string;
  tool_name?: string;
  tool_call_id?: string;
  metadata?: Record<string, any>;
  done?: boolean; // for streaming assistant messages
}

export default function ConsolePage() {
  const { t } = useTranslation();
  const { showToast } = useAppStore();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConsoleMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isRunning, setIsRunning] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // WebSocket connection
  useEffect(() => {
    // Connect to WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
    };

    return () => {
      ws.close();
    };
  }, []);

  // Use ref to track sessionId for WebSocket handler (avoids stale closure)
  const sessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const handleWebSocketMessage = (data: any) => {
    // Only handle messages for current session (or accept if no session yet)
    const currentSessionId = sessionIdRef.current;
    if (data.session_id && currentSessionId && data.session_id !== currentSessionId) return;

    // If we receive a message with session_id and we don't have one, capture it
    if (data.session_id && !currentSessionId) {
      setSessionId(data.session_id);
    }

    switch (data.type) {
      case 'console_user_message':
        // User message already added locally
        break;

      case 'console_assistant_thinking':
        // Streaming assistant response
        setMessages(prev => {
          const last = prev[prev.length - 1];
          if (last?.type === 'assistant' && !last.done) {
            // Update existing streaming message
            return [...prev.slice(0, -1), {
              ...last,
              content: last.content + data.content,
              done: data.done
            }];
          } else if (!data.done) {
            // Start new streaming message
            return [...prev, {
              type: 'assistant',
              content: data.content,
              timestamp: new Date().toISOString(),
              done: false
            }];
          }
          return prev;
        });
        break;

      case 'console_tool_executing':
        // Tool is executing
        setMessages(prev => [...prev, {
          type: 'tool_call',
          content: JSON.stringify(data.parameters, null, 2),
          timestamp: new Date().toISOString(),
          tool_name: data.tool_name,
          tool_call_id: data.tool_call_id,
          metadata: { status: 'executing' }
        }]);
        break;

      case 'console_tool_result':
        // Tool result received
        setMessages(prev => prev.map(msg =>
          msg.type === 'tool_call' && msg.tool_call_id === data.tool_call_id
            ? {
                ...msg,
                type: 'tool_result',
                metadata: { ...msg.metadata, status: data.success ? 'success' : 'error', result: data.content }
              }
            : msg
        ));
        break;

      case 'console_session_status':
        if (data.status === 'completed') {
          setIsRunning(false);
        }
        break;
    }
  };

  const handleSend = async () => {
    if (!inputValue.trim()) return;

    const userMessage: ConsoleMessage = {
      type: 'user',
      content: inputValue,
      timestamp: new Date().toISOString()
    };

    // Add user message immediately
    setMessages(prev => [...prev, userMessage]);
    setInputValue('');

    try {
      if (!sessionId) {
        // Start new session
        const response = await fetch('/api/console/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: inputValue,
            auto_approve: true
          })
        });

        if (!response.ok) {
          throw new Error('Failed to start console session');
        }

        const data = await response.json();
        setSessionId(data.session_id);
        setIsRunning(true);
        showToast('Console session started', 'success');
      } else {
        // Continue existing session
        const response = await fetch(`/api/console/${sessionId}/message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: inputValue })
        });

        if (!response.ok) {
          throw new Error('Failed to send message');
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      showToast('Failed to send message', 'error');
    }
  };

  const handleStop = async () => {
    if (!sessionId) return;

    try {
      const response = await fetch(`/api/console/${sessionId}/stop`, {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error('Failed to stop session');
      }

      setIsRunning(false);
      setSessionId(null); // Reset session ID after stop
      showToast('Session stopped', 'success');
    } catch (error) {
      console.error('Failed to stop session:', error);
      showToast('Failed to stop session', 'error');
    }
  };

  const handleNewSession = () => {
    setSessionId(null);
    setMessages([]);
    setIsRunning(false);
    setInputValue('');
  };

  return (
    <div className="flex flex-col h-full overflow-hidden gap-4 p-scaled-4">
      {/* Controls */}
      <div className="shrink-0">
        <ConsoleControls
          sessionId={sessionId}
          isRunning={isRunning}
          onNewSession={handleNewSession}
          onStop={handleStop}
        />
      </div>

      {/* Message area */}
      <div className="flex-1 min-h-0 card overflow-hidden flex flex-col">
        {!sessionId && messages.length === 0 && (
          <div className="p-scaled-4 flex flex-col gap-scaled-4">
            {/* Purpose tip */}
            <div className="flex gap-scaled-3 p-scaled-3 rounded-lg bg-[var(--bg-subtle)] border border-[var(--border-color)]">
              <Info className="icon-scaled-base text-[var(--accent-primary)] shrink-0 mt-0.5" />
              <div className="text-scaled-sm text-[var(--text-secondary)]">
                <p className="font-medium text-[var(--text-primary)] mb-1">{t('console.devConsoleTitle')}</p>
                <p>{t('console.devConsoleDesc')}</p>
              </div>
            </div>

            {/* Warning tip */}
            <div className="flex gap-scaled-3 p-scaled-3 rounded-lg bg-[color-mix(in_srgb,var(--accent-warning)_10%,transparent)] border border-[color-mix(in_srgb,var(--accent-warning)_30%,var(--border-color))]">
              <AlertTriangle className="icon-scaled-base text-[var(--accent-warning)] shrink-0 mt-0.5" />
              <div className="text-scaled-sm text-[var(--text-secondary)]">
                <p className="font-medium text-[var(--accent-warning)] mb-1">{t('console.autoApproveWarningTitle')}</p>
                <p className="mb-2">{t('console.autoApproveWarningDesc')}</p>
                <p>{t('console.interactiveMode')} <code className="inline px-scaled-2 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-primary)] font-mono text-scaled-xs">claude</code></p>
              </div>
            </div>
          </div>
        )}
        <MessageList messages={messages} messagesEndRef={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="shrink-0">
        <ConsoleInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          disabled={isRunning && messages[messages.length - 1]?.type === 'assistant' && !messages[messages.length - 1]?.done}
          placeholder={sessionId ? t('console.continueConversation') : t('console.startConversation')}
        />
      </div>
    </div>
  );
}
