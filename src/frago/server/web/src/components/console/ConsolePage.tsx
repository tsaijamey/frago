import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Info } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import type { ConsoleMessage } from '@/types/console';
import ConsoleControls from './ConsoleControls';
import MessageList from './MessageList';
import ConsoleInput from './ConsoleInput';

export default function ConsolePage() {
  const { t } = useTranslation();
  const {
    showToast,
    // Console state from global store
    consoleSessionId,
    consoleMessages,
    consoleIsRunning,
    consoleScrollPosition,
    // Console actions
    setConsoleSessionId,
    addConsoleMessage,
    updateLastConsoleMessage,
    updateConsoleMessageByToolCallId,
    setConsoleIsRunning,
    setConsoleScrollPosition,
    clearConsole,
  } = useAppStore();

  // Local state for input (no need to persist draft)
  const [inputValue, setInputValue] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Restore scroll position on mount
  useEffect(() => {
    if (consoleScrollPosition > 0 && scrollContainerRef.current) {
      scrollContainerRef.current.scrollTop = consoleScrollPosition;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on mount

  // Save scroll position on unmount
  useEffect(() => {
    return () => {
      const container = scrollContainerRef.current;
      if (container) {
        setConsoleScrollPosition(container.scrollTop);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on unmount

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [consoleMessages]);

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
    sessionIdRef.current = consoleSessionId;
  }, [consoleSessionId]);

  // Memoize the WebSocket message handler to use latest store actions
  const handleWebSocketMessage = useCallback((data: Record<string, unknown>) => {
    // Only handle messages for current session (or accept if no session yet)
    const currentSessionId = sessionIdRef.current;
    const sessionId = data.session_id as string | undefined;
    if (sessionId && currentSessionId && sessionId !== currentSessionId) return;

    // If we receive a message with session_id and we don't have one, capture it
    if (sessionId && !currentSessionId) {
      setConsoleSessionId(sessionId);
    }

    const messages = useAppStore.getState().consoleMessages;

    switch (data.type) {
      case 'console_user_message':
        // User message already added locally
        break;

      case 'console_assistant_thinking': {
        // Streaming assistant response
        const last = messages[messages.length - 1];
        if (last?.type === 'assistant' && !last.done) {
          // Update existing streaming message
          updateLastConsoleMessage({
            content: last.content + (data.content as string),
            done: data.done as boolean,
          });
        } else if (!data.done) {
          // Start new streaming message
          addConsoleMessage({
            type: 'assistant',
            content: data.content as string,
            timestamp: new Date().toISOString(),
            done: false,
          });
        }
        break;
      }

      case 'console_tool_executing':
        // Tool is executing
        addConsoleMessage({
          type: 'tool_call',
          content: JSON.stringify(data.parameters, null, 2),
          timestamp: new Date().toISOString(),
          tool_name: data.tool_name as string,
          tool_call_id: data.tool_call_id as string,
          metadata: { status: 'executing' },
        });
        break;

      case 'console_tool_result':
        // Tool result received
        updateConsoleMessageByToolCallId(data.tool_call_id as string, {
          type: 'tool_result',
          metadata: {
            status: data.success ? 'success' : 'error',
            result: data.content,
          },
        });
        break;

      case 'console_session_status':
        if (data.status === 'completed') {
          setConsoleIsRunning(false);
        }
        break;
    }
  }, [setConsoleSessionId, addConsoleMessage, updateLastConsoleMessage, updateConsoleMessageByToolCallId, setConsoleIsRunning]);

  const handleSend = async () => {
    if (!inputValue.trim()) return;

    const userMessage: ConsoleMessage = {
      type: 'user',
      content: inputValue,
      timestamp: new Date().toISOString(),
    };

    // Add user message immediately
    addConsoleMessage(userMessage);
    setInputValue('');

    try {
      if (!consoleSessionId) {
        // Start new session
        const response = await fetch('/api/console/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: inputValue,
            auto_approve: true,
          }),
        });

        if (!response.ok) {
          throw new Error('Failed to start console session');
        }

        const data = await response.json();
        setConsoleSessionId(data.session_id);
        setConsoleIsRunning(true);
        showToast('Console session started', 'success');
      } else {
        // Continue existing session
        const response = await fetch(`/api/console/${consoleSessionId}/message`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: inputValue }),
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
    if (!consoleSessionId) return;

    try {
      const response = await fetch(`/api/console/${consoleSessionId}/stop`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to stop session');
      }

      setConsoleIsRunning(false);
      setConsoleSessionId(null); // Reset session ID after stop
      showToast('Session stopped', 'success');
    } catch (error) {
      console.error('Failed to stop session:', error);
      showToast('Failed to stop session', 'error');
    }
  };

  const handleNewSession = () => {
    clearConsole();
    setInputValue('');
  };

  return (
    <div className="flex flex-col h-full overflow-hidden gap-4 p-scaled-4">
      {/* Controls */}
      <div className="shrink-0">
        <ConsoleControls
          sessionId={consoleSessionId}
          isRunning={consoleIsRunning}
          onNewSession={handleNewSession}
          onStop={handleStop}
        />
      </div>

      {/* Message area */}
      <div ref={scrollContainerRef} className="flex-1 min-h-0 card overflow-hidden flex flex-col overflow-y-auto">
        {!consoleSessionId && consoleMessages.length === 0 && (
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
        <MessageList messages={consoleMessages} messagesEndRef={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="shrink-0">
        <ConsoleInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          disabled={consoleIsRunning && consoleMessages[consoleMessages.length - 1]?.type === 'assistant' && !consoleMessages[consoleMessages.length - 1]?.done}
          placeholder={consoleSessionId ? t('console.continueConversation') : t('console.startConversation')}
        />
      </div>
    </div>
  );
}
