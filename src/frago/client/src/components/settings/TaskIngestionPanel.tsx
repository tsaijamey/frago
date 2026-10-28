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
      <div className="s-card">
        <div className="ssec flex items-center gap-3 text-[var(--text-muted)]">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-xs">{t('settings.channels.loading')}</span>
        </div>
      </div>
    );
  }

  if (!state) {
    return (
      <div className="salert err items-center">
        <XCircle className="w-4 h-4 shrink-0" />
        <span>{error ?? t('settings.channels.noData')}</span>
        <button
          type="button"
          onClick={load}
          className="ml-auto btn btn-ghost btn-sm p-1"
          aria-label={t('settings.channels.refresh')}
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div>
      {error && (
        <div className="salert err">
          <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
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
