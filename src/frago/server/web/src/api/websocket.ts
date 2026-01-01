/**
 * WebSocket Client for Frago Web Service
 *
 * Provides real-time updates via WebSocket connection.
 * Features:
 * - Auto-reconnect with exponential backoff
 * - Ping/pong keepalive
 * - Event-based message handling
 */

// Message types matching server
export const MessageType = {
  // Connection events
  CONNECTED: 'connected',
  PING: 'ping',
  PONG: 'pong',

  // Task events
  TASK_STARTED: 'task_started',
  TASK_UPDATED: 'task_updated',
  TASK_COMPLETED: 'task_completed',
  TASK_ERROR: 'task_error',

  // Session events
  SESSION_SYNC: 'session_sync',
  SESSION_CREATED: 'session_created',
  SESSION_UPDATED: 'session_updated',

  // Recipe events
  RECIPE_STARTED: 'recipe_started',
  RECIPE_COMPLETED: 'recipe_completed',

  // Data push events (for cache updates)
  DATA_INITIAL: 'data_initial',
  DATA_TASKS: 'data_tasks',
  DATA_DASHBOARD: 'data_dashboard',
  DATA_RECIPES: 'data_recipes',
  DATA_SKILLS: 'data_skills',
  DATA_COMMUNITY_RECIPES: 'data_community_recipes',
} as const;

export type MessageTypeValue = (typeof MessageType)[keyof typeof MessageType];

export interface WebSocketMessage {
  type: MessageTypeValue;
  timestamp: string;
  task_id?: string;
  status?: string;
  data?: Record<string, unknown>;
}

type MessageHandler = (message: WebSocketMessage) => void;
type ConnectionHandler = () => void;

interface WebSocketClientOptions {
  /** Auto-reconnect on disconnect (default: true) */
  autoReconnect?: boolean;
  /** Initial reconnect delay in ms (default: 1000) */
  reconnectDelay?: number;
  /** Max reconnect delay in ms (default: 30000) */
  maxReconnectDelay?: number;
  /** Ping interval in ms (default: 30000) */
  pingInterval?: number;
}

export class FragoWebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private options: Required<WebSocketClientOptions>;
  private messageHandlers: Map<string, Set<MessageHandler>> = new Map();
  private onConnectHandlers: Set<ConnectionHandler> = new Set();
  private onDisconnectHandlers: Set<ConnectionHandler> = new Set();
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private isConnecting = false;

  constructor(options: WebSocketClientOptions = {}) {
    // Build WebSocket URL from current location
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    this.url = `${protocol}//${host}/ws`;

    this.options = {
      autoReconnect: options.autoReconnect ?? true,
      reconnectDelay: options.reconnectDelay ?? 1000,
      maxReconnectDelay: options.maxReconnectDelay ?? 30000,
      pingInterval: options.pingInterval ?? 30000,
    };
  }

  /**
   * Connect to the WebSocket server
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return;
    }

    this.isConnecting = true;
    console.log('[WebSocket] Connecting to', this.url);

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[WebSocket] Connected');
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this.startPingTimer();
        this.onConnectHandlers.forEach((handler) => handler());
      };

      this.ws.onclose = (event) => {
        console.log('[WebSocket] Disconnected', event.code, event.reason);
        this.isConnecting = false;
        this.stopPingTimer();
        this.onDisconnectHandlers.forEach((handler) => handler());

        if (this.options.autoReconnect) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
        this.isConnecting = false;
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.handleMessage(message);
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error);
        }
      };
    } catch (error) {
      console.error('[WebSocket] Failed to create connection:', error);
      this.isConnecting = false;
      if (this.options.autoReconnect) {
        this.scheduleReconnect();
      }
    }
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    this.options.autoReconnect = false;
    this.stopPingTimer();
    this.clearReconnectTimer();

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Check if connected
   */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Subscribe to messages of a specific type
   */
  on(type: MessageTypeValue | '*', handler: MessageHandler): () => void {
    const key = type as string;
    if (!this.messageHandlers.has(key)) {
      this.messageHandlers.set(key, new Set());
    }
    this.messageHandlers.get(key)!.add(handler);

    // Return unsubscribe function
    return () => {
      this.messageHandlers.get(key)?.delete(handler);
    };
  }

  /**
   * Subscribe to connection events
   */
  onConnect(handler: ConnectionHandler): () => void {
    this.onConnectHandlers.add(handler);
    return () => this.onConnectHandlers.delete(handler);
  }

  /**
   * Subscribe to disconnection events
   */
  onDisconnect(handler: ConnectionHandler): () => void {
    this.onDisconnectHandlers.add(handler);
    return () => this.onDisconnectHandlers.delete(handler);
  }

  /**
   * Send a message to the server
   */
  send(message: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  private handleMessage(message: WebSocketMessage): void {
    // Call type-specific handlers
    const handlers = this.messageHandlers.get(message.type);
    handlers?.forEach((handler) => {
      try {
        handler(message);
      } catch (error) {
        console.error('[WebSocket] Handler error:', error);
      }
    });

    // Call wildcard handlers
    const wildcardHandlers = this.messageHandlers.get('*');
    wildcardHandlers?.forEach((handler) => {
      try {
        handler(message);
      } catch (error) {
        console.error('[WebSocket] Wildcard handler error:', error);
      }
    });
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();

    // Calculate delay with exponential backoff
    const delay = Math.min(
      this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts),
      this.options.maxReconnectDelay
    );

    console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private startPingTimer(): void {
    this.stopPingTimer();
    this.pingTimer = setInterval(() => {
      this.send({ type: MessageType.PING });
    }, this.options.pingInterval);
  }

  private stopPingTimer(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }
}

// Global WebSocket client instance
let globalClient: FragoWebSocketClient | null = null;

/**
 * Get the global WebSocket client
 */
export function getWebSocketClient(): FragoWebSocketClient {
  if (!globalClient) {
    globalClient = new FragoWebSocketClient();
  }
  return globalClient;
}

/**
 * Connect to WebSocket if in HTTP mode
 */
export function connectWebSocket(): void {
  // Only connect in HTTP mode (not pywebview)
  if (!window.pywebview?.api) {
    getWebSocketClient().connect();
  }
}

/**
 * Disconnect from WebSocket
 */
export function disconnectWebSocket(): void {
  globalClient?.disconnect();
  globalClient = null;
}
