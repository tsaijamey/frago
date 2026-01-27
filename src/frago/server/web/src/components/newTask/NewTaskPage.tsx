import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { getConsoleHistory } from '@/api';
import { getWebSocketClient } from '@/api/websocket';
import { recordDirectoriesFromText } from '@/utils/recentDirectories';
import type { ConsoleMessage } from '@/types/console';
import { toUnifiedMessage } from '@/types/message';
import NewTaskControls from './NewTaskControls';
import { MessageList } from '@/components/shared';
import NewTaskInput from './NewTaskInput';

export default function NewTaskPage() {
  const { t } = useTranslation();
  const {
    showToast,
    // Console state from global store
    consoleInternalId,
    consoleSessionId,
    consoleMessages,
    consoleIsRunning,
    consoleScrollPosition,
    // Console actions
    setConsoleInternalId,
    setConsoleSessionId,
    addConsoleMessage,
    updateLastConsoleMessage,
    updateConsoleMessageByToolCallId,
    setConsoleIsRunning,
    setConsoleScrollPosition,
    setConsoleMessages,
    clearConsole,
  } = useAppStore();

  // Local state for input (no need to persist draft)
  const [inputValue, setInputValue] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);

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

  // Restore session from localStorage on initial load (after page refresh)
  useEffect(() => {
    const restoreSession = async () => {
      // Skip if we already have a session in memory
      if (useAppStore.getState().consoleInternalId) return;

      try {
        const storedInternalId = localStorage.getItem('frago_console_internal_id');
        const storedSessionId = localStorage.getItem('frago_console_session_id');
        if (!storedInternalId) return;

        // Validate session still exists on backend using internal_id
        const response = await fetch(`/api/console/${storedInternalId}/info`);
        if (response.ok) {
          const info = await response.json();
          // Restore both IDs
          setConsoleInternalId(storedInternalId);
          if (storedSessionId) {
            setConsoleSessionId(storedSessionId);
          }
          setConsoleIsRunning(info.running === true);
          // Fetch history using internal_id
          const history = await getConsoleHistory(storedInternalId);
          if (history.messages) {
            const messagesWithDone = history.messages.map(msg => ({
              ...msg,
              done: true, // Messages from history are always complete
            })) as ConsoleMessage[];
            setConsoleMessages(messagesWithDone);
          }
        } else {
          // Session not found, clear localStorage
          localStorage.removeItem('frago_console_internal_id');
          localStorage.removeItem('frago_console_session_id');
        }
      } catch {
        localStorage.removeItem('frago_console_internal_id');
        localStorage.removeItem('frago_console_session_id');
      }
    };
    restoreSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on initial mount

  // Recover messages when returning to console with existing session (after tab switch)
  // Always fetch from backend since it's the source of truth for messages received while away
  useEffect(() => {
    const recoverMessages = async () => {
      const internalId = useAppStore.getState().consoleInternalId;
      if (internalId) {
        try {
          const history = await getConsoleHistory(internalId);
          if (history.messages && history.messages.length > 0) {
            // Replace with backend data - it has messages received while page was unmounted
            // Messages from history are always complete
            const messagesWithDone = history.messages.map(msg => ({
              ...msg,
              done: true,
            })) as ConsoleMessage[];
            setConsoleMessages(messagesWithDone);
          }
        } catch (error) {
          console.error('Failed to recover console history:', error);
        }
      }
    };
    recoverMessages();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on mount

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [consoleMessages]);

  // Use ref to track internalId for WebSocket handler (avoids stale closure)
  const internalIdRef = useRef<string | null>(null);
  useEffect(() => {
    internalIdRef.current = consoleInternalId;
  }, [consoleInternalId]);

  // Memoize the WebSocket message handler to use latest store actions
  const handleWebSocketMessage = useCallback((data: Record<string, unknown>) => {
    // Filter messages by internal_id (for console events)
    const currentInternalId = internalIdRef.current;
    const msgInternalId = data.internal_id as string | undefined;

    // Skip if message has internal_id that doesn't match ours
    if (msgInternalId && currentInternalId && msgInternalId !== currentInternalId) return;

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
          // Ensure last message is marked as done
          const lastMsg = useAppStore.getState().consoleMessages.slice(-1)[0];
          if (lastMsg && lastMsg.type === 'assistant' && !lastMsg.done) {
            updateLastConsoleMessage({ done: true });
          }
        }
        break;

      case 'console_session_id_resolved': {
        // Backend resolved the real Claude session ID
        // Match by internal_id and set the real session_id for display
        const internalId = data.internal_id as string;
        const realSessionId = data.session_id as string;
        if (internalId === currentInternalId && realSessionId) {
          setConsoleSessionId(realSessionId);
          // Also update localStorage for session recovery
          localStorage.setItem('frago_console_session_id', realSessionId);
        }
        break;
      }
    }
  }, [setConsoleSessionId, addConsoleMessage, updateLastConsoleMessage, updateConsoleMessageByToolCallId, setConsoleIsRunning]);

  // Subscribe to WebSocket messages using global client
  useEffect(() => {
    const client = getWebSocketClient();

    // Subscribe to all messages and filter console-related ones
    const unsubscribe = client.on('*', (message) => {
      handleWebSocketMessage(message as unknown as Record<string, unknown>);
    });

    return () => {
      // Only unsubscribe, don't close the connection
      unsubscribe();
    };
  }, [handleWebSocketMessage]);

  const handleSend = async () => {
    if (!inputValue.trim()) return;

    // Record directories from the input
    recordDirectoriesFromText(inputValue);

    const userMessage: ConsoleMessage = {
      type: 'user',
      content: inputValue,
      timestamp: new Date().toISOString(),
    };

    // Add user message immediately
    addConsoleMessage(userMessage);
    setInputValue('');

    try {
      if (!consoleInternalId) {
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
        // Store internal_id for API calls; real session_id comes via WebSocket
        setConsoleInternalId(data.internal_id);
        setConsoleIsRunning(true);
        showToast('Console session started', 'success');
      } else {
        // Continue existing session using internal_id
        const response = await fetch(`/api/console/${consoleInternalId}/message`, {
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
    if (!consoleInternalId) return;

    try {
      const response = await fetch(`/api/console/${consoleInternalId}/stop`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to stop session');
      }

      setConsoleIsRunning(false);
      setConsoleInternalId(null);
      setConsoleSessionId(null);
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

  // Convert ConsoleMessage[] to UnifiedMessage[]
  const unifiedMessages = useMemo(
    () => consoleMessages.map((msg, index) => toUnifiedMessage(msg, index)),
    [consoleMessages]
  );

  // Welcome screen for empty state
  const welcomeScreen = (
    <div className="welcome-screen">
      <div className="welcome-header">
        <div className="welcome-icon">
          <Sparkles size={32} />
        </div>
        <h1 className="welcome-headline">{t('console.welcomeHeadline')}</h1>
        <p className="welcome-subheadline">{t('console.welcomeSubheadline')}</p>
      </div>

      {/* Capsule toggle button */}
      <div className="approval-toggle mt-scaled-6">
        <button type="button" className="approval-toggle-option active">
          {t('console.autoApprove')}
        </button>
        <button
          type="button"
          className="approval-toggle-option disabled"
          title={t('console.manualApproveDisabledHint')}
          disabled
        >
          {t('console.manualApprove')}
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col h-full overflow-hidden gap-4 p-scaled-4">
      {/* Controls */}
      <div className="shrink-0">
        <NewTaskControls
          sessionId={consoleSessionId}
          isRunning={consoleIsRunning}
          onNewSession={handleNewSession}
          onStop={handleStop}
        />
      </div>

      {/* Message area */}
      <div ref={scrollContainerRef} className="flex-1 min-h-0 card overflow-hidden flex flex-col overflow-y-auto">
        <MessageList
          messages={unifiedMessages}
          messagesEndRef={messagesEndRef}
          emptyState={welcomeScreen}
          gap="space-y-4"
        />
      </div>

      {/* Input area */}
      <div className="shrink-0">
        <NewTaskInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          disabled={consoleIsRunning && consoleMessages[consoleMessages.length - 1]?.type === 'assistant' && !consoleMessages[consoleMessages.length - 1]?.done}
          placeholder={consoleInternalId ? t('console.continueConversation') : t('console.startConversation')}
        />
      </div>
    </div>
  );
}
