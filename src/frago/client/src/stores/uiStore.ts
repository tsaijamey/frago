/**
 * UI state (Zustand)
 *
 * Owns: toast queue, sidebar collapse, global loading flag, the agent
 * attached-session id, plus the legacy console* slice.
 *
 * NOTE: the console* fields are flagged legacy but are still actively used by
 * NewTaskPage.tsx (reads + getState + length-based rendering). They are kept
 * here intact until NewTaskPage is migrated; do NOT delete them.
 */

import { create } from 'zustand';
import type { ConsoleMessage } from '@/types/console';

// Sidebar storage key for localStorage
const SIDEBAR_COLLAPSED_KEY = 'frago-sidebar-collapsed';

// Console session storage keys for localStorage
const CONSOLE_INTERNAL_ID_KEY = 'frago_console_internal_id';
const CONSOLE_SESSION_KEY = 'frago_console_session_id';

// Toast type
export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

export interface UISlice {
  // Sidebar state
  sidebarCollapsed: boolean;

  // UI state
  isLoading: boolean;
  toasts: Toast[];

  // Agent attached session state (for real-time streaming in TaskDetail)
  agentAttachedId: string | null; // Internal ID of attached session (null = detached/polling mode)

  // Console state (legacy, to be removed once NewTaskPage is migrated)
  consoleInternalId: string | null;
  consoleSessionId: string | null;
  consoleMessages: ConsoleMessage[];
  consoleIsRunning: boolean;
  consoleScrollPosition: number;

  // Actions
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  showToast: (message: string, type: ToastType) => void;
  dismissToast: (id: string) => void;

  // Agent attached session actions
  setAgentAttachedId: (id: string | null) => void;

  // Console actions (legacy)
  setConsoleInternalId: (id: string | null) => void;
  setConsoleSessionId: (id: string | null) => void;
  addConsoleMessage: (message: ConsoleMessage) => void;
  updateLastConsoleMessage: (update: Partial<ConsoleMessage>) => void;
  updateConsoleMessageByToolCallId: (toolCallId: string, update: Partial<ConsoleMessage>) => void;
  setConsoleMessages: (messages: ConsoleMessage[]) => void;
  setConsoleIsRunning: (running: boolean) => void;
  setConsoleScrollPosition: (position: number) => void;
  clearConsole: () => void;
}

// Generate unique ID
function generateId(): string {
  return Math.random().toString(36).substring(2, 9);
}

// Helper to get initial sidebar state from localStorage
function getInitialSidebarCollapsed(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    return stored === 'true';
  } catch {
    return false;
  }
}

export const useUIStore = create<UISlice>((set, get) => ({
  sidebarCollapsed: getInitialSidebarCollapsed(),
  isLoading: false,
  toasts: [],
  agentAttachedId: null,

  // Console initial state (legacy)
  consoleInternalId: null,
  consoleSessionId: null,
  consoleMessages: [],
  consoleIsRunning: false,
  consoleScrollPosition: 0,

  // Toggle sidebar collapsed state
  toggleSidebar: () => {
    const newCollapsed = !get().sidebarCollapsed;
    set({ sidebarCollapsed: newCollapsed });
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(newCollapsed));
    } catch {
      // localStorage not available
    }
  },

  // Set sidebar collapsed state directly
  setSidebarCollapsed: (collapsed) => {
    set({ sidebarCollapsed: collapsed });
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
    } catch {
      // localStorage not available
    }
  },

  // Show toast
  showToast: (message, type) => {
    const id = generateId();
    set((state) => ({
      toasts: [...state.toasts, { id, message, type }],
    }));

    // Auto dismiss
    setTimeout(() => {
      get().dismissToast(id);
    }, 3000);
  },

  // Dismiss toast
  dismissToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },

  // Agent attached session actions
  setAgentAttachedId: (id) => {
    set({ agentAttachedId: id });
  },

  // Console actions (legacy)
  setConsoleInternalId: (id) => {
    set({ consoleInternalId: id });
    try {
      if (id) {
        localStorage.setItem(CONSOLE_INTERNAL_ID_KEY, id);
      } else {
        localStorage.removeItem(CONSOLE_INTERNAL_ID_KEY);
      }
    } catch {
      // localStorage not available
    }
  },
  setConsoleSessionId: (id) => {
    set({ consoleSessionId: id });
    try {
      if (id) {
        localStorage.setItem(CONSOLE_SESSION_KEY, id);
      } else {
        localStorage.removeItem(CONSOLE_SESSION_KEY);
      }
    } catch {
      // localStorage not available
    }
  },

  addConsoleMessage: (message) => {
    set((state) => ({
      consoleMessages: [...state.consoleMessages, message],
    }));
  },

  updateLastConsoleMessage: (update) => {
    set((state) => {
      const messages = state.consoleMessages;
      if (messages.length === 0) return state;
      const last = messages[messages.length - 1];
      return {
        consoleMessages: [...messages.slice(0, -1), { ...last, ...update }],
      };
    });
  },

  updateConsoleMessageByToolCallId: (toolCallId, update) => {
    set((state) => ({
      consoleMessages: state.consoleMessages.map((msg) =>
        msg.tool_call_id === toolCallId ? { ...msg, ...update } : msg
      ),
    }));
  },

  setConsoleMessages: (messages) => {
    set({ consoleMessages: messages });
  },

  setConsoleIsRunning: (running) => {
    set({ consoleIsRunning: running });
  },

  setConsoleScrollPosition: (position) => {
    set({ consoleScrollPosition: position });
  },

  clearConsole: () => {
    set({
      consoleInternalId: null,
      consoleSessionId: null,
      consoleMessages: [],
      consoleIsRunning: false,
      consoleScrollPosition: 0,
    });
    try {
      localStorage.removeItem(CONSOLE_INTERNAL_ID_KEY);
      localStorage.removeItem(CONSOLE_SESSION_KEY);
    } catch {
      // localStorage not available
    }
  },
}));
