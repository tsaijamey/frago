import { X, Plus, Check, Pencil, Trash2, Save, Zap } from 'lucide-react';
import type { ProfilesController } from './useProfiles';

const ENDPOINT_LABELS: Record<string, string> = {
  deepseek: 'DeepSeek',
  aliyun: 'Aliyun',
  kimi: 'Kimi',
  minimax: 'MiniMax',
  custom: 'Custom URL',
};

interface ProfileListProps {
  pm: ProfilesController;
  hasCustomConfig?: boolean;
}

export default function ProfileList({ pm, hasCustomConfig }: ProfileListProps) {
  const {
    t,
    profiles,
    activeProfileId,
    activatingId,
    deletingId,
    savingCurrent,
    showSaveCurrentInput,
    setShowSaveCurrentInput,
    saveCurrentName,
    setSaveCurrentName,
    handleAddClick,
    handleEditClick,
    handleActivate,
    handleDeactivate,
    handleDelete,
    handleSaveCurrent,
  } = pm;

  return (
    <div className="space-y-3">
      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          onClick={handleAddClick}
          className="btn btn-primary btn-sm flex items-center gap-1"
        >
          <Plus size={14} />
          {t('settings.profiles.addProfile')}
        </button>
        {hasCustomConfig && (
          <>
            {showSaveCurrentInput ? (
              <div className="flex gap-1 items-center">
                <input
                  type="text"
                  value={saveCurrentName}
                  onChange={(e) => setSaveCurrentName(e.target.value)}
                  placeholder={t('settings.profiles.profileNamePlaceholder')}
                  className="px-2 py-1 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveCurrent();
                    if (e.key === 'Escape') {
                      setShowSaveCurrentInput(false);
                      setSaveCurrentName('');
                    }
                  }}
                  autoFocus
                />
                <button
                  type="button"
                  onClick={handleSaveCurrent}
                  disabled={savingCurrent || !saveCurrentName.trim()}
                  className="btn btn-ghost btn-sm p-1 disabled:opacity-50"
                  aria-label={t('settings.profiles.save')}
                >
                  {savingCurrent ? '...' : <Check size={14} />}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowSaveCurrentInput(false);
                    setSaveCurrentName('');
                  }}
                  className="btn btn-ghost btn-sm p-1"
                  aria-label={t('settings.profiles.cancel')}
                >
                  <X size={14} />
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setShowSaveCurrentInput(true)}
                className="btn btn-ghost btn-sm flex items-center gap-1"
              >
                <Save size={14} />
                {t('settings.profiles.saveCurrentConfig')}
              </button>
            )}
          </>
        )}
      </div>

      {/* Profile list */}
      {profiles.length === 0 ? (
        <div className="text-center py-8">
          <p className="text-[var(--text-muted)] text-sm">{t('settings.profiles.noProfiles')}</p>
          <p className="text-[var(--text-muted)] text-xs mt-1">{t('settings.profiles.noProfilesDesc')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {profiles.map((profile) => (
            <div
              key={profile.id}
              className={`border rounded-lg p-3 transition-colors ${
                profile.is_active
                  ? 'border-[var(--accent-primary)] bg-[var(--accent-primary)]/5'
                  : 'border-[var(--border-color)] hover:border-[var(--text-muted)]'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="font-medium text-sm text-[var(--text-primary)] truncate">
                    {profile.name}
                  </span>
                  {profile.is_active && (
                    <span className="shrink-0 inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]">
                      <Check size={12} />
                      {t('settings.profiles.active')}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {!profile.is_active && (
                    <button
                      type="button"
                      onClick={() => handleActivate(profile.id)}
                      disabled={activatingId === profile.id}
                      className="btn btn-ghost btn-sm text-xs flex items-center gap-1 text-[var(--accent-primary)] disabled:opacity-50"
                    >
                      <Zap size={14} />
                      {activatingId === profile.id ? t('settings.profiles.activating') : t('settings.profiles.activate')}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => handleEditClick(profile)}
                    className="btn btn-ghost btn-sm p-1.5"
                    title={t('settings.profiles.edit')}
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(profile.id)}
                    disabled={deletingId === profile.id}
                    className="btn btn-ghost btn-sm p-1.5 text-[var(--accent-error)] disabled:opacity-50"
                    title={t('settings.profiles.delete')}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              <div className="mt-1 flex items-center gap-2 text-xs text-[var(--text-muted)]">
                <span>{ENDPOINT_LABELS[profile.endpoint_type] || profile.endpoint_type}</span>
                <span>·</span>
                <span className="font-mono">{profile.api_key_masked}</span>
              </div>
            </div>
          ))}

          {/* Deactivate button (switch to official) */}
          {activeProfileId && (
            <button
              type="button"
              onClick={handleDeactivate}
              disabled={activatingId === '__deactivate__'}
              className="w-full text-center text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] py-2 disabled:opacity-50"
            >
              {activatingId === '__deactivate__' ? t('settings.profiles.activating') : t('settings.profiles.deactivate')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
