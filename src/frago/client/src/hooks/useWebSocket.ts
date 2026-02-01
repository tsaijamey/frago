/**
 * WebSocket Hook
 *
 * React hook for WebSocket connection and real-time updates.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import {
  getWebSocketClient,
  connectWebSocket,
  MessageType,
  type WebSocketMessage,
  type MessageTypeValue,
} from '@/api/websocket';
import { getApiMode } from '@/api';

interface UseWebSocketOptions {
  /** Auto-connect on mount (default: true) */
  autoConnect?: boolean;
  /** Message types to subscribe to */
  messageTypes?: MessageTypeValue[];
  /** Callback when message received */
  onMessage?: (message: WebSocketMessage) => void;
}

interface UseWebSocketReturn {
  /** Whether connected to WebSocket */
  isConnected: boolean;
  /** Last received message */
  lastMessage: WebSocketMessage | null;
  /** Connect to WebSocket */
  connect: () => void;
  /** Disconnect from WebSocket */
  disconnect: () => void;
  /** Send a message */
  send: (message: Record<string, unknown>) => void;
}

/**
 * Hook for WebSocket connection and real-time updates
 */
export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const { autoConnect = true, messageTypes, onMessage } = options;
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const onMessageRef = useRef(onMessage);

  // Keep callback ref updated
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  // Connect on mount if in HTTP mode
  useEffect(() => {
    // Only use WebSocket in HTTP mode
    if (getApiMode() !== 'http') {
      return;
    }

    const client = getWebSocketClient();

    // Subscribe to connection status
    const unsubConnect = client.onConnect(() => {
      setIsConnected(true);
    });

    const unsubDisconnect = client.onDisconnect(() => {
      setIsConnected(false);
    });

    // Subscribe to messages
    const unsubscribers: (() => void)[] = [];

    if (messageTypes && messageTypes.length > 0) {
      // Subscribe to specific message types
      messageTypes.forEach((type) => {
        const unsub = client.on(type, (message) => {
          setLastMessage(message);
          onMessageRef.current?.(message);
        });
        unsubscribers.push(unsub);
      });
    } else {
      // Subscribe to all messages
      const unsub = client.on('*', (message) => {
        setLastMessage(message);
        onMessageRef.current?.(message);
      });
      unsubscribers.push(unsub);
    }

    // Auto-connect
    if (autoConnect) {
      connectWebSocket();
      setIsConnected(client.isConnected);
    }

    return () => {
      unsubConnect();
      unsubDisconnect();
      unsubscribers.forEach((unsub) => unsub());
    };
  }, [autoConnect, messageTypes]);

  const connect = useCallback(() => {
    if (getApiMode() === 'http') {
      connectWebSocket();
    }
  }, []);

  const disconnect = useCallback(() => {
    if (getApiMode() === 'http') {
      getWebSocketClient().disconnect();
    }
  }, []);

  const send = useCallback((message: Record<string, unknown>) => {
    if (getApiMode() === 'http') {
      getWebSocketClient().send(message);
    }
  }, []);

  return {
    isConnected,
    lastMessage,
    connect,
    disconnect,
    send,
  };
}

/**
 * Hook specifically for task updates
 */
export function useTaskUpdates(
  taskId?: string,
  onUpdate?: (message: WebSocketMessage) => void
) {
  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      // Filter by task ID if provided
      if (taskId && message.task_id !== taskId) {
        return;
      }
      onUpdate?.(message);
    },
    [taskId, onUpdate]
  );

  return useWebSocket({
    messageTypes: [
      MessageType.TASK_STARTED,
      MessageType.TASK_UPDATED,
      MessageType.TASK_COMPLETED,
      MessageType.TASK_ERROR,
    ],
    onMessage: handleMessage,
  });
}

/**
 * Hook for session sync updates
 */
export function useSessionSync(onSync?: (sessions: unknown[]) => void) {
  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      if (message.type === MessageType.SESSION_SYNC && message.data?.sessions) {
        onSync?.(message.data.sessions as unknown[]);
      }
    },
    [onSync]
  );

  return useWebSocket({
    messageTypes: [MessageType.SESSION_SYNC],
    onMessage: handleMessage,
  });
}
