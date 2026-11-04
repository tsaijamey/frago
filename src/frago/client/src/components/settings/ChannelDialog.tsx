import { Loader2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChannelDraft } from './useTaskIngestion';

export default function ChannelDialog({
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
  const { t } = useTranslation();
  const isEdit = draft.originalName !== null;
  const title = isEdit
    ? t('settings.channels.dialogEdit', { name: draft.originalName })
    : t('settings.channels.dialogAdd');

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
      <div className="bg-[var(--bg-primary)] border border-[var(--border-strong)] rounded-xl max-w-md w-full overflow-hidden shadow-xl">
        <div className="flex items-center justify-between px-4 h-11 border-b border-[var(--border-color)]">
          <h3 className="text-[13.5px] font-semibold text-[var(--text-primary)]">{title}</h3>
          <button
            type="button"
            onClick={onCancel}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            aria-label={t('settings.channels.cancel')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-3.5 space-y-2.5">
          <div className="fgrp">
            <label>{t('settings.channels.colName')}</label>
            <input
              type="text"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder={t('settings.channels.namePlaceholder')}
              className="sinput mono w-full"
              disabled={isEdit}
            />
            {isEdit && (
              <div className="hint">{t('settings.channels.nameImmutableHint')}</div>
            )}
            {nameCollides && (
              <div className="err">
                {t('settings.channels.nameTaken', { name: draft.name.trim() })}
              </div>
            )}
          </div>

          <div className="fgrp">
            <label>{t('settings.channels.colPoll')}</label>
            <select
              value={draft.poll_recipe}
              onChange={(e) => setDraft({ ...draft, poll_recipe: e.target.value })}
              className="sselect w-full"
              style={{ maxWidth: '100%' }}
            >
              {availableRecipes.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div className="fgrp">
            <label>{t('settings.channels.colNotify')}</label>
            <select
              value={draft.notify_recipe}
              onChange={(e) =>
                setDraft({ ...draft, notify_recipe: e.target.value })
              }
              className="sselect w-full"
              style={{ maxWidth: '100%' }}
            >
              {availableRecipes.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div className="fgrid2">
            <div className="fgrp">
              <label>{t('settings.channels.intervalSeconds')}</label>
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
                className="sinput mono w-full"
              />
            </div>
            <div className="fgrp">
              <label>{t('settings.channels.timeoutSeconds')}</label>
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
                className="sinput mono w-full"
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-1.5 px-3.5 py-2.5 border-t border-[var(--border-color)] bg-[var(--bg-secondary)]">
          <button type="button" onClick={onCancel} className="btn btn-sm">
            {t('settings.channels.cancel')}
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit || saving}
            className="btn btn-primary btn-sm flex items-center gap-1.5 disabled:opacity-50"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {isEdit ? t('settings.channels.save') : t('settings.channels.addShort')}
          </button>
        </div>
      </div>
    </div>
  );
}
