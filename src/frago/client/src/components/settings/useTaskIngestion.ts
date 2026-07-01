import { useEffect, useState } from 'react';
import {
  getTaskIngestion,
  putTaskIngestion,
  restartServer,
  type TaskIngestionChannel,
  type TaskIngestionGetResponse,
} from '../../api/client';

export type ChannelDraft = {
  // Present only when editing an existing channel. Lets us detect rename collisions.
  originalName: string | null;
  name: string;
  poll_recipe: string;
  notify_recipe: string;
  poll_interval_seconds: number;
  poll_timeout_seconds: number;
};

export const emptyDraft = (available: string[]): ChannelDraft => ({
  originalName: null,
  name: '',
  poll_recipe: available[0] ?? '',
  notify_recipe: available[0] ?? '',
  poll_interval_seconds: 120,
  poll_timeout_seconds: 20,
});

/**
 * useTaskIngestion — owns channel config state and persistence:
 * load/save round-trips, the global enable toggle, server restart,
 * and the add/edit draft lifecycle.
 */
export function useTaskIngestion() {
  const [state, setState] = useState<TaskIngestionGetResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [restartPending, setRestartPending] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [draft, setDraft] = useState<ChannelDraft | null>(null);

  useEffect(() => {
    void load();
  }, []);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTaskIngestion();
      setState(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  };

  const persist = async (next: {
    enabled: boolean;
    channels: TaskIngestionChannel[];
  }) => {
    setSaving(true);
    setError(null);
    try {
      const result = await putTaskIngestion(next);
      setRestartPending(result.requires_restart);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async () => {
    if (!state) return;
    await persist({ enabled: !state.enabled, channels: state.channels });
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      await restartServer();
      // The server exits mid-request; the UI polls for it to come back.
      setTimeout(() => void load(), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Restart failed');
    } finally {
      setRestarting(false);
      setRestartPending(false);
    }
  };

  const openAddDialog = () => {
    if (!state) return;
    setDraft(emptyDraft(state.available_recipes));
  };

  const openEditDialog = (ch: TaskIngestionChannel) => {
    setDraft({
      originalName: ch.name,
      name: ch.name,
      poll_recipe: ch.poll_recipe,
      notify_recipe: ch.notify_recipe,
      poll_interval_seconds: ch.poll_interval_seconds,
      poll_timeout_seconds: ch.poll_timeout_seconds,
    });
  };

  const submitDraft = async () => {
    if (!state || !draft) return;
    const { originalName, ...fields } = draft;
    const replacement: TaskIngestionChannel = {
      name: fields.name.trim(),
      poll_recipe: fields.poll_recipe,
      notify_recipe: fields.notify_recipe,
      poll_interval_seconds: fields.poll_interval_seconds,
      poll_timeout_seconds: fields.poll_timeout_seconds,
    };

    // Rebuild the channels list: replace the matching name (on edit) or append (on add).
    const channels = originalName
      ? state.channels.map((c) => (c.name === originalName ? replacement : c))
      : [...state.channels, replacement];

    await persist({ enabled: state.enabled, channels });
    setDraft(null);
  };

  const removeChannel = async (name: string) => {
    if (!state) return;
    if (!window.confirm(`Remove channel "${name}"?`)) return;
    const channels = state.channels.filter((c) => c.name !== name);
    await persist({ enabled: state.enabled, channels });
  };

  return {
    state,
    loading,
    error,
    saving,
    restartPending,
    restarting,
    draft,
    setDraft,
    load,
    toggleEnabled,
    handleRestart,
    openAddDialog,
    openEditDialog,
    submitDraft,
    removeChannel,
  };
}
