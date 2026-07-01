/**
 * Page navigation state (Zustand)
 *
 * Owns: current page + the contextual ids that the active page needs
 * (task / recipe / project). Split out of the former monolithic appStore.
 */

import { create } from 'zustand';

// Page type - Updated for new admin panel layout
export type PageType =
  | 'live'
  | 'claude_sessions'
  | 'dashboard'
  | 'tasks'
  | 'task_detail'
  | 'recipes'
  | 'recipe_detail'
  | 'skills'
  | 'guide'
  | 'settings'
  | 'newTask'
  | 'workspace'
  | 'project_detail';

export interface PageSlice {
  currentPage: PageType;
  currentTaskId: string | null;
  currentRecipeName: string | null;
  currentProjectId: string | null;

  switchPage: (page: PageType, id?: string) => void;
}

export const usePageStore = create<PageSlice>((set) => ({
  // Initial state - default to Claude session management homepage
  currentPage: 'claude_sessions',
  currentTaskId: null,
  currentRecipeName: null,
  currentProjectId: null,

  switchPage: (page, id) => {
    set({
      currentPage: page,
      currentTaskId: page === 'task_detail' ? id ?? null : null,
      currentRecipeName: page === 'recipe_detail' ? id ?? null : null,
      currentProjectId: page === 'project_detail' ? id ?? null : null,
    });
  },
}));
