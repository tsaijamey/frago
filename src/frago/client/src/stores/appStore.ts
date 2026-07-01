/**
 * Application Global State — facade over the split stores.
 *
 * The former 624-line monolith was split by responsibility into:
 *   - pageStore.ts  → navigation (currentPage / currentTaskId / ...)
 *   - dataStore.ts  → business data cache (config / recipes / skills / ...)
 *   - uiStore.ts    → toast / sidebar / loading + legacy console* slice
 *
 * This module keeps the historical `useAppStore` surface working unchanged so
 * the ~23 existing call sites are zero-touch: `useAppStore()` returns the
 * merged state, `useAppStore(selector)` selects from it, and
 * `useAppStore.getState()` reads the merged snapshot. New code should prefer
 * the scoped hooks (usePageStore / useDataStore / useUIStore) for narrower
 * subscriptions.
 */

import { usePageStore, type PageSlice } from './pageStore';
import { useDataStore, type DataSlice } from './dataStore';
import { useUIStore, type UISlice } from './uiStore';

// Re-export types so existing `import { PageType, Toast, ToastType } from '@/stores/appStore'` keeps working.
export type { PageType } from './pageStore';
export type { Toast, ToastType } from './uiStore';
export { usePageStore } from './pageStore';
export { useDataStore } from './dataStore';
export { useUIStore } from './uiStore';

// The unified shape, identical to the former monolithic AppState.
export type AppState = PageSlice & DataSlice & UISlice;

function getMergedState(): AppState {
  return {
    ...usePageStore.getState(),
    ...useDataStore.getState(),
    ...useUIStore.getState(),
  };
}

interface UseAppStore {
  (): AppState;
  <T>(selector: (state: AppState) => T): T;
  getState: () => AppState;
}

const useAppStoreImpl = (<T>(selector?: (state: AppState) => T) => {
  // Subscribe to all three stores so the facade re-renders on any change,
  // matching the former single-store behavior.
  const page = usePageStore();
  const data = useDataStore();
  const ui = useUIStore();
  const merged = { ...page, ...data, ...ui } as AppState;
  return selector ? selector(merged) : merged;
}) as UseAppStore;

useAppStoreImpl.getState = getMergedState;

export const useAppStore = useAppStoreImpl;
