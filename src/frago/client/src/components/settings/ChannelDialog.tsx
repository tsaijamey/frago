import { Loader2 } from 'lucide-react';
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
      <div className="bg-[var(--bg-primary)] rounded-lg p-6 max-w-md w-full space-y-4">
        <h3 className="text-lg font-semibold">{title}</h3>

        <div className="space-y-3">
          <div>
            <label className="block text-sm mb-1">{t('settings.channels.colName')}</label>
            <input
              type="text"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder={t('settings.channels.namePlaceholder')}
              className="input w-full"
              disabled={isEdit}
            />
            {nameCollides && (
              <p className="text-xs text-[var(--text-error)] mt-1">
                {t('settings.channels.nameTaken', { name: draft.name.trim() })}
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm mb-1">{t('settings.channels.colPoll')}</label>
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
            <label className="block text-sm mb-1">{t('settings.channels.colNotify')}</label>
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
              <label className="block text-sm mb-1">{t('settings.channels.intervalSeconds')}</label>
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
              <label className="block text-sm mb-1">{t('settings.channels.timeoutSeconds')}</label>
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
            {t('settings.channels.cancel')}
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit || saving}
            className="btn btn-primary btn-sm flex items-center gap-2"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {isEdit ? t('settings.channels.save') : t('settings.channels.addShort')}
          </button>
        </div>
      </div>
    </div>
  );
}
