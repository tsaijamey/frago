/**
 * useCoreSelection - the one place the wizard's core choice is persisted.
 *
 * Both the full-page wizard and the modal wizard offer this step, so the
 * "remember what the user picked" logic lives here once. NEVER inline it into
 * either wizard: two copies drift, and a core that only sticks in one of them
 * is worse than a core that never sticks at all.
 *
 * The wizard speaks in UI names ('claude-code'), the backend in driver names
 * ('claude'). Translation happens here and nowhere else.
 */

import { useState } from 'react';
import { updateAgentCore } from '../../api/client';

export type CoreType = 'claude-code' | 'opencode' | null;

/** Wizard-facing core name → the cli-agent driver name the backend stores. */
export function toAgentCore(coreType: 'claude-code' | 'opencode'): string {
  return coreType === 'opencode' ? 'opencode' : 'claude';
}

export function useCoreSelection(onSelected: () => void) {
  const [coreType, setCoreType] = useState<CoreType>(null);
  const [coreError, setCoreError] = useState<string | null>(null);

  /**
   * Record the choice locally and persist it as the global core preference.
   *
   * A failed write does not block the wizard — the rest of setup is still
   * worth finishing — but the reason is surfaced so the user isn't left
   * believing a preference was saved when it wasn't.
   */
  const selectCore = async (selected: 'claude-code' | 'opencode') => {
    setCoreType(selected);
    setCoreError(null);
    try {
      await updateAgentCore(toAgentCore(selected));
    } catch (err) {
      setCoreError(err instanceof Error ? err.message : 'Failed to save core preference');
    }
    onSelected();
  };

  return { coreType, setCoreType, coreError, selectCore };
}
