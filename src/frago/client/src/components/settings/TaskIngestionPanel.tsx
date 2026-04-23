/**
 * TaskIngestionPanel — manages task ingestion channels via the server API.
 *
 * Spec: 20260422-channel-config-ui
 *
 * UX:
 *   - Shows the global enable toggle + a table of configured channels.
 *   - Add / Edit opens a modal form with dropdowns sourced from the server's
 *     `available_recipes` list so the user can't type an unknown recipe name.
 *   - After any save the "Restart Server" button appears (only when the
 *     backend reports `restart_supported = true`, i.e. daemon mode).
 */

import { useEffect, useState } from 'react';
import {
  Loader2,
  RefreshCw,
  Plus,
  Pencil,
  Trash2,
  Power,
  RotateCcw,
  XCircle,
} from 'lucide-react';
import {
  getTaskIngestion,
  putTaskIngestion,
  restartServer,
  type TaskIngestionChannel,
  type TaskIngestionGetResponse,
} from '../../api/client';

type ChannelDraft = {
  // Present only when editing an existing channel. Lets us detect rename collisions.
  originalName: string | null;
  name: string;
  poll_recipe: string;
  notify_recipe: string;
  poll_interval_seconds: number;
  poll_timeout_seconds: number;
};

const emptyDraft = (available: string[]): ChannelDraft => ({
  originalName: null,
  name: '',
  poll_recipe: available[0] ?? '',
  notify_recipe: available[0] ?? '',
  poll_interval_seconds: 120,
  poll_timeout_seconds: 20,
});

export default function TaskIngestionPanel() {
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

  if (loading) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading task ingestion…
        </div>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3 text-[var(--text-error)]">
          <XCircle className="w-5 h-5" />
          {error ?? 'No data'}
          <button type="button" onClick={load} className="ml-auto">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-[var(--accent-primary)]">
            Task Ingestion
          </h2>
          <p className="text-sm text-[var(--text-muted)]">
            Channels poll external sources (email, Slack, feishu…) and deliver
            messages to the Primary Agent.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
          aria-label="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-[var(--text-error)]">
          <XCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Enable / restart strip */}
      <div className="flex flex-wrap items-center justify-between gap-2 p-3 bg-[var(--bg-subtle)] rounded-lg">
        <div className="flex items-center gap-3">
          <Power
            className={
              state.enabled
                ? 'w-5 h-5 text-green-600 dark:text-green-400'
                : 'w-5 h-5 text-[var(--text-muted)]'
            }
          />
          <span className="text-sm font-medium">
            Task ingestion: {state.enabled ? 'enabled' : 'disabled'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleEnabled}
            disabled={saving}
            className="btn btn-sm"
          >
            {state.enabled ? 'Disable' : 'Enable'}
          </button>
          {restartPending && (
            <button
              type="button"
              onClick={handleRestart}
              disabled={restarting || !state.restart_supported}
              className="btn btn-primary btn-sm flex items-center gap-2"
              title={
                state.restart_supported
                  ? 'Restart server so scheduler picks up changes'
                  : 'Server is not in daemon mode — restart manually'
              }
            >
              {restarting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
              Restart Server
            </button>
          )}
        </div>
      </div>

      {/* Channels table */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">
            Channels ({state.channels.length})
          </span>
          <button
            type="button"
            onClick={openAddDialog}
            disabled={state.available_recipes.length === 0}
            className="btn btn-primary btn-sm flex items-center gap-2"
            title={
              state.available_recipes.length === 0
                ? 'Install at least one recipe to add channels'
                : 'Add a new channel'
            }
          >
            <Plus className="w-4 h-4" />
            Add Channel
          </button>
        </div>

        {state.channels.length === 0 ? (
          <div className="text-sm text-[var(--text-muted)] p-4 text-center border border-dashed border-[var(--border-color)] rounded-lg">
            No channels configured.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[var(--text-muted)]">
                <th className="py-2">Name</th>
                <th className="py-2">Poll Recipe</th>
                <th className="py-2">Notify Recipe</th>
                <th className="py-2">Interval</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {state.channels.map((ch) => (
                <tr
                  key={ch.name}
                  className="border-t border-[var(--border-color)]"
                >
                  <td className="py-2 font-medium">{ch.name}</td>
                  <td className="py-2 text-[var(--text-secondary)]">
                    {ch.poll_recipe}
                  </td>
                  <td className="py-2 text-[var(--text-secondary)]">
                    {ch.notify_recipe}
                  </td>
                  <td className="py-2 text-[var(--text-secondary)]">
                    {ch.poll_interval_seconds}s
                  </td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      onClick={() => openEditDialog(ch)}
                      className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-primary)]"
                      aria-label="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => void removeChannel(ch.name)}
                      className="p-1 text-[var(--text-muted)] hover:text-red-500"
                      aria-label="Remove"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {state.available_recipes.length === 0 && (
          <p className="text-xs text-[var(--text-muted)]">
            No recipes are installed yet. Put recipes under <code>~/.frago/recipes/</code>
            {' '}(poll + notify pair per channel) before adding a channel.
          </p>
        )}
      </div>

      {/* Draft dialog */}
      {draft && (
        <ChannelDialog
          draft={draft}
          setDraft={setDraft}
          availableRecipes={state.available_recipes}
          existingNames={state.channels.map((c) => c.name)}
          saving={saving}
          onCancel={() => setDraft(null)}
          onSubmit={submitDraft}
        />
      )}
    </div>
  );
}

function ChannelDialog({
  draft,
  setDraft,
  availableRecipes,
  existingNames,
  saving,
  onCancel,
  onSubmit,
}: {
  draft: ChannelDraft;
  setDraft: (d: ChannelDraft) => void;
  availableRecipes: string[];
  existingNames: string[];
  saving: boolean;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const isEdit = draft.originalName !== null;
  const title = isEdit ? `Edit channel: ${draft.originalName}` : 'Add channel';

  const nameCollides =
    existingNames.includes(draft.name.trim()) &&
    draft.name.trim() !== draft.originalName;

  const canSubmit =
    draft.name.trim().length > 0 &&
    draft.poll_recipe.length > 0 &&
    draft.notify_recipe.length > 0 &&
    draft.poll_interval_seconds > 0 &&
    draft.poll_timeout_seconds > 0 &&
    !nameCollides;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--bg-primary)] rounded-lg p-6 max-w-md w-full space-y-4">
        <h3 className="text-lg font-semibold">{title}</h3>

        <div className="space-y-3">
          <div>
            <label className="block text-sm mb-1">Name</label>
            <input
              type="text"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="e.g. feishu, email"
              className="input w-full"
              disabled={isEdit}
            />
            {nameCollides && (
              <p className="text-xs text-[var(--text-error)] mt-1">
                A channel named "{draft.name.trim()}" already exists.
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm mb-1">Poll recipe</label>
            <select
              value={draft.poll_recipe}
              onChange={(e) => setDraft({ ...draft, poll_recipe: e.target.value })}
              className="input w-full"
            >
              {availableRecipes.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm mb-1">Notify recipe</label>
            <select
              value={draft.notify_recipe}
              onChange={(e) =>
                setDraft({ ...draft, notify_recipe: e.target.value })
              }
              className="input w-full"
            >
              {availableRecipes.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm mb-1">Interval (s)</label>
              <input
                type="number"
                min={1}
                value={draft.poll_interval_seconds}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    poll_interval_seconds: Number(e.target.value),
                  })
                }
                className="input w-full"
              />
            </div>
            <div>
              <label className="block text-sm mb-1">Timeout (s)</label>
              <input
                type="number"
                min={1}
                value={draft.poll_timeout_seconds}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    poll_timeout_seconds: Number(e.target.value),
                  })
                }
                className="input w-full"
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-[var(--border-color)]">
          <button type="button" onClick={onCancel} className="btn btn-sm">
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit || saving}
            className="btn btn-primary btn-sm flex items-center gap-2"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {isEdit ? 'Save' : 'Add'}
          </button>
        </div>
      </div>
    </div>
  );
}
