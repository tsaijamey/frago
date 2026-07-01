import {
  Loader2,
  Plus,
  Pencil,
  Trash2,
  Power,
  RotateCcw,
} from 'lucide-react';
import type { TaskIngestionChannel, TaskIngestionGetResponse } from '../../api/client';

interface ChannelTableProps {
  state: TaskIngestionGetResponse;
  saving: boolean;
  restartPending: boolean;
  restarting: boolean;
  toggleEnabled: () => void;
  handleRestart: () => void;
  openAddDialog: () => void;
  openEditDialog: (ch: TaskIngestionChannel) => void;
  removeChannel: (name: string) => void;
}

export default function ChannelTable({
  state,
  saving,
  restartPending,
  restarting,
  toggleEnabled,
  handleRestart,
  openAddDialog,
  openEditDialog,
  removeChannel,
}: ChannelTableProps) {
  return (
    <>
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
    </>
  );
}
