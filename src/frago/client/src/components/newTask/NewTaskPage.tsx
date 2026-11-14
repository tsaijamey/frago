import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Compass, Bot, FileCode, Play } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { getWebSocketClient } from '@/api/websocket';
import { recordDirectoriesFromText } from '@/utils/recentDirectories';
import type { ConsoleMessage } from '@/types/console';
import { toUnifiedMessage } from '@/types/message';
import NewTaskControls from './NewTaskControls';
import { MessageList } from '@/components/shared';
import NewTaskInput from './NewTaskInput';
import * as httpApi from '@/api/client';
import { localISOString } from '@/utils/time';
import { scrollBehavior } from '@/utils/reducedMotion';

export default function NewTaskPage() {
  const { t } = useTranslation();
  const {
    showToast,
    // Console state from global store (used for in-page streaming before redirect)
    consoleInternalId,
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
    clearConsole,
    // Agent attached session
    setAgentAttachedId,
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
      // eslint-disable-next-line react-hooks/exhaustive-deps
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
        if (!storedInternalId) return;

        // Validate session still exists on backend (attached session)
        const response = await fetch(`/api/agent/attached/${storedInternalId}/info`);
        if (response.ok) {
          const info = await response.json();
          setConsoleInternalId(storedInternalId);
          if (info.session_id) {
            setConsoleSessionId(info.session_id);
          }
          setConsoleIsRunning(info.running === true);
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

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    // 走 `scrollBehavior()`：开着减弱动效时这一步直接落位，不滑过去。
    messagesEndRef.current?.scrollIntoView({ behavior: scrollBehavior() });
  }, [consoleMessages]);

  // Use ref to track internalId for WebSocket handler (avoids stale closure)
  const internalIdRef = useRef<string | null>(null);
  useEffect(() => {
    internalIdRef.current = consoleInternalId;
  }, [consoleInternalId]);

  // Memoize the WebSocket message handler to use latest store actions
  const handleWebSocketMessage = useCallback((data: Record<string, unknown>) => {
    // Filter messages by internal_id
    const currentInternalId = internalIdRef.current;
    const msgInternalId = data.internal_id as string | undefined;

    // Skip if message has internal_id that doesn't match ours
    if (msgInternalId && currentInternalId && msgInternalId !== currentInternalId) return;

    const messages = useAppStore.getState().consoleMessages;

    switch (data.type) {
      case 'agent_user_message':
        // User message already added locally
        break;

      case 'agent_text_delta': {
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
            timestamp: localISOString(),
            done: false,
          });
        }
        break;
      }

      case 'agent_tool_executing':
        // Tool is executing
        addConsoleMessage({
          type: 'tool_call',
          content: JSON.stringify(data.parameters, null, 2),
          timestamp: localISOString(),
          tool_name: data.tool_name as string,
          tool_call_id: data.tool_call_id as string,
          metadata: { status: 'executing' },
        });
        break;

      case 'agent_tool_result':
        // Tool result received
        updateConsoleMessageByToolCallId(data.tool_call_id as string, {
          type: 'tool_result',
          metadata: {
            status: data.success ? 'success' : 'error',
            result: data.content,
          },
        });
        break;

      case 'agent_session_status':
        if (data.status === 'completed') {
          setConsoleIsRunning(false);
          // Ensure last message is marked as done
          const lastMsg = useAppStore.getState().consoleMessages.slice(-1)[0];
          if (lastMsg && lastMsg.type === 'assistant' && !lastMsg.done) {
            updateLastConsoleMessage({ done: true });
          }
        }
        break;

      case 'agent_session_resolved': {
        // Backend resolved the real Claude session ID
        const internalId = data.internal_id as string;
        const realSessionId = data.session_id as string;
        if (internalId === currentInternalId && realSessionId) {
          setConsoleSessionId(realSessionId);
          localStorage.setItem('frago_console_session_id', realSessionId);
        }
        break;
      }
    }
  }, [setConsoleSessionId, addConsoleMessage, updateLastConsoleMessage, updateConsoleMessageByToolCallId, setConsoleIsRunning]);

  // Subscribe to WebSocket messages using global client
  useEffect(() => {
    const client = getWebSocketClient();

    // Subscribe to all messages and filter agent-related ones
    const unsubscribe = client.on('*', (message) => {
      handleWebSocketMessage(message as unknown as Record<string, unknown>);
    });

    return () => {
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
      timestamp: localISOString(),
    };

    // Add user message immediately
    addConsoleMessage(userMessage);
    setInputValue('');

    try {
      if (!consoleInternalId) {
        // Start new attached session
        const data = await httpApi.startAgentAttached(inputValue);
        // Store internal_id for API calls; real session_id comes via WebSocket
        setConsoleInternalId(data.internal_id);
        setConsoleIsRunning(true);
        // Store the attached ID for TaskDetail to use
        setAgentAttachedId(data.internal_id);
        localStorage.setItem('frago_console_internal_id', data.internal_id);
        showToast('Session started', 'success');
      } else {
        // Continue existing session using internal_id
        await httpApi.sendAgentAttachedMessage(consoleInternalId, inputValue);
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      showToast('Failed to send message', 'error');
    }
  };

  const handleStop = async () => {
    if (!consoleInternalId) return;

    try {
      await httpApi.stopAgentAttached(consoleInternalId);

      setConsoleIsRunning(false);
      setConsoleInternalId(null);
      setConsoleSessionId(null);
      setAgentAttachedId(null);
      showToast('Session stopped', 'success');
    } catch (error) {
      console.error('Failed to stop session:', error);
      showToast('Failed to stop session', 'error');
    }
  };

  const handleNewSession = () => {
    clearConsole();
    setAgentAttachedId(null);
    setInputValue('');
  };

  // Convert ConsoleMessage[] to UnifiedMessage[]
  const unifiedMessages = useMemo(
    () => consoleMessages.map((msg, index) => toUnifiedMessage(msg, index)),
    [consoleMessages]
  );

  // Quick action handlers - prefill input with prompt template
  // 四枚入口共用一个图标规格（16px、线宽 1.75），此前是描边圆、方框、文档、
  // 播放三角四种画风混在一起，人一眼看不出它们是同一层级的四件事。
  const quickActions = [
    { icon: Compass, label: t('console.quickActions.explore'), prompt: t('console.quickActions.explorePrompt') },
    { icon: Bot, label: t('console.quickActions.automate'), prompt: t('console.quickActions.automatePrompt') },
    { icon: FileCode, label: t('console.quickActions.createRecipe'), prompt: t('console.quickActions.createRecipePrompt') },
    { icon: Play, label: t('console.quickActions.testRecipe'), prompt: t('console.quickActions.testRecipePrompt') },
  ];

  const handleQuickAction = (prompt: string) => {
    setInputValue(prompt);
  };

  // 运行模式切换。这一枚在两种状态下都渲染：它是这次会话「怎么跑」的设定，
  // 会话进行中也得看得见当前是什么模式，而不是开跑之后就消失。
  const approvalToggle = (
    <div className="nt-approval" role="group" aria-label={t('console.autoApprove')}>
      <button type="button" className="nt-approval-option is-active">
        {t('console.autoApprove')}
      </button>
      <button
        type="button"
        className="nt-approval-option"
        title={t('console.manualApproveDisabledHint')}
        disabled
      >
        {t('console.manualApprove')}
      </button>
    </div>
  );

  // 空会话时的起始屏：一句主张 + 一个焦点框 + 四枚起步入口，全部居中成一列。
  const welcomeScreen = (
    <div className="nt-welcome">
      <div className="nt-welcome-head">
        <img src="/icons/logo-128.png" alt="frago" className="nt-welcome-logo" />
        <h2 className="nt-welcome-headline">{t('console.welcomeHeadline')}</h2>
        <p className="nt-welcome-sub">{t('console.welcomeSubheadline')}</p>
      </div>

      <div className="nt-welcome-input">
        <NewTaskInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          disabled={consoleIsRunning}
          placeholder={t('console.startConversation')}
          controls={approvalToggle}
        />
      </div>

      <div className="nt-quick">
        {quickActions.map((action) => (
          <button
            key={action.label}
            type="button"
            className="nt-quick-card ui-bezel-card ui-bezel-card--interactive"
            onClick={() => handleQuickAction(action.prompt)}
            title={action.prompt}
          >
            <span className="nt-quick-icon">
              <action.icon size={16} strokeWidth={1.75} />
            </span>
            <span className="nt-quick-label">{action.label}</span>
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="nt-page">
      <header className="ui-page-header">
        <div className="ui-page-header-titles">
          <h1 className="ui-page-header-title">{t('console.newSession')}</h1>
          <span className="ui-page-header-meta">
            {consoleMessages.length > 0 ? t('console.continueConversation') : t('console.startConversation')}
          </span>
        </div>
        <div className="ui-page-header-actions">
          <NewTaskControls
            isRunning={consoleIsRunning}
            hasContent={consoleMessages.length > 0}
            onNewSession={handleNewSession}
            onStop={handleStop}
          />
        </div>
      </header>

      {/* 会话进行中：记录占满中间，输入框贴底。空会话：整块区域是起始屏。 */}
      {consoleMessages.length === 0 ? (
        <div className="nt-body nt-body--welcome">{welcomeScreen}</div>
      ) : (
        <>
          <div ref={scrollContainerRef} className="nt-stream">
            <MessageList
              messages={unifiedMessages}
              messagesEndRef={messagesEndRef}
              gap="space-y-4"
            />
          </div>

          <div className="nt-composer">
            <NewTaskInput
              value={inputValue}
              onChange={setInputValue}
              onSend={handleSend}
              disabled={consoleIsRunning && consoleMessages[consoleMessages.length - 1]?.type === 'assistant' && !consoleMessages[consoleMessages.length - 1]?.done}
              placeholder={t('console.continueConversation')}
              controls={approvalToggle}
            />
          </div>
        </>
      )}
    </div>
  );
}
