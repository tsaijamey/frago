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
 *
 * State and behavior live in useTaskIngestion; this file composes the
 * config strip + table (ChannelTable) and the add/edit modal (ChannelDialog).
 */

import { Loader2, RefreshCw, XCircle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTaskIngestion } from './useTaskIngestion';
import ChannelTable from './ChannelTable';
import ChannelDialog from './ChannelDialog';

export default function TaskIngestionPanel() {
  const { t } = useTranslation();
  const {
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
  } = useTaskIngestion();

  if (loading) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="w-5 h-5 animate-spin" />
          {t('settings.channels.loading')}
        </div>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="card p-6">
        <div className="flex items-center gap-3 text-[var(--text-error)]">
          <XCircle className="w-5 h-5" />
          {error ?? t('settings.channels.noData')}
          <button
            type="button"
            onClick={load}
            className="ml-auto"
            aria-label={t('settings.channels.refresh')}
          >
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
            {t('settings.channels.title')}
          </h2>
          <p className="text-sm text-[var(--text-muted)]">
            {t('settings.channels.description')}
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
          aria-label={t('settings.channels.refresh')}
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

      <ChannelTable
        state={state}
        saving={saving}
        restartPending={restartPending}
        restarting={restarting}
        toggleEnabled={toggleEnabled}
        handleRestart={handleRestart}
        openAddDialog={openAddDialog}
        openEditDialog={openEditDialog}
        removeChannel={removeChannel}
      />

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
