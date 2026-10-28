import {
  Loader2,
  Plus,
  Pencil,
  Trash2,
  RotateCcw,
} from 'lucide-react';
import { Trans, useTranslation } from 'react-i18next';
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
  const { t } = useTranslation();
  const countHeading =
    state.channels.length === 1
      ? t('settings.channels.countOne')
      : t('settings.channels.count', { total: state.channels.length });

  return (
    <>
      {/* Enable / restart strip */}
      <div className={`sstrip ${restartPending ? 'warn' : ''}`}>
        <div className="l">
          <i className={`s-dot ${state.enabled ? 'd-run' : 'd-idle'}`} />
          <span>
            {state.enabled
              ? t('settings.channels.stateEnabled')
              : t('settings.channels.stateDisabled')}
          </span>
          {restartPending && (
            <span className="s-pill warn" style={{ marginLeft: 4 }}>
              {t('settings.channels.restartRequiredBadge')}
            </span>
          )}
        </div>
        <div className="r">
          <button
            type="button"
            onClick={toggleEnabled}
            disabled={saving}
            className="btn btn-sm"
          >
            {state.enabled
              ? t('settings.channels.disable')
              : t('settings.channels.enable')}
          </button>
          {restartPending && (
            <button
              type="button"
              onClick={handleRestart}
              disabled={restarting || !state.restart_supported}
              className="btn btn-primary btn-sm flex items-center gap-1.5"
              title={
                state.restart_supported
                  ? t('settings.channels.restartHint')
                  : t('settings.channels.restartManualHint')
              }
            >
              {restarting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RotateCcw className="w-3.5 h-3.5" />
              )}
              {t('settings.channels.restartServer')}
            </button>
          )}
        </div>
      </div>

      {/* Channels card */}
      <div className="s-card">
        <div className="ssec">
          <div className="ssec-h">
            <h3>{countHeading}</h3>
            <button
              type="button"
              onClick={openAddDialog}
              disabled={state.available_recipes.length === 0}
              className={`btn btn-sm flex items-center gap-1 ${
                state.available_recipes.length === 0 ? 'opacity-50' : 'btn-primary'
              }`}
              title={
                state.available_recipes.length === 0
                  ? t('settings.channels.addBlockedHint')
                  : t('settings.channels.addHint')
              }
            >
              <Plus className="w-3.5 h-3.5" />
              {t('settings.channels.add')}
            </button>
          </div>

          {state.channels.length === 0 ? (
            <div
              style={{
                padding: '22px 14px',
                textAlign: 'center',
                border: '1px dashed var(--border-color)',
                borderRadius: 8,
                color: 'var(--text-muted)',
                fontSize: 12.5,
              }}
            >
              {t('settings.channels.empty')}
            </div>
          ) : (
            <div className="stbl-wrap">
              <table className="stbl">
                <thead>
                  <tr>
                    <th style={{ width: '16%' }}>{t('settings.channels.colName')}</th>
                    <th style={{ width: '29%' }}>{t('settings.channels.colPoll')}</th>
                    <th style={{ width: '29%' }}>{t('settings.channels.colNotify')}</th>
                    <th style={{ width: '12%' }}>{t('settings.channels.colInterval')}</th>
                    <th style={{ width: '14%' }} />
                  </tr>
                </thead>
                <tbody>
                  {state.channels.map((ch) => (
                    <tr key={ch.name}>
                      <td className="nm truncate">{ch.name}</td>
                      <td className="mono truncate">{ch.poll_recipe}</td>
                      <td className="mono truncate">{ch.notify_recipe}</td>
                      <td className="mono">{ch.poll_interval_seconds}s</td>
                      <td className="acts">
                        <button
                          type="button"
                          onClick={() => openEditDialog(ch)}
                          className="btn-icon-sm"
                          title={t('settings.channels.editChannel')}
                          aria-label={t('settings.channels.editChannel')}
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void removeChannel(ch.name)}
                          className="btn-icon-sm"
                          title={t('settings.channels.removeChannel')}
                          aria-label={t('settings.channels.removeChannel')}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {state.available_recipes.length === 0 && (
            <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-muted)' }}>
              <Trans i18nKey="settings.channels.noRecipes" components={{ c: <code /> }} />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
