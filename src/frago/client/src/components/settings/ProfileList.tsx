import { X, Plus, Check, Pencil, Trash2, Save, Zap, Ban } from 'lucide-react';
import type { ProfilesController } from './useProfiles';

interface ProfileListProps {
  pm: ProfilesController;
  hasCustomConfig?: boolean;
}

export default function ProfileList({ pm, hasCustomConfig }: ProfileListProps) {
  const {
    t,
    profiles,
    presets,
    activeProfileId,
    activeTargets,
    targets,
    selectableTargets,
    pickingTargetsFor,
    pickedTargets,
    activatingId,
    deletingId,
    savingCurrent,
    showSaveCurrentInput,
    setShowSaveCurrentInput,
    saveCurrentName,
    setSaveCurrentName,
    handleAddClick,
    handleEditClick,
    handleActivateClick,
    handleCancelTargetPick,
    toggleTarget,
    handleActivate,
    handleDeactivate,
    handleDelete,
    handleSaveCurrent,
  } = pm;

  const targetName = (agentType: string) =>
    targets.find((target) => target.agent_type === agentType)?.display_name ?? agentType;

  /** Provider name and the model this profile will actually run — the two
   *  things you need to tell one saved profile from another. The model is the
   *  profile's own override when it has one, otherwise the preset's default;
   *  the row used to show neither, only the provider id and a masked key. */
  const describe = (endpointType: string, override?: string | null) => {
    const preset = presets.find((p) => p.id === endpointType);
    return {
      provider: preset?.display_name ?? (endpointType === 'custom' ? t('settings.profiles.customEndpoint') : endpointType),
      model: override || preset?.default_model || null,
    };
  };

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
          {profiles.map((profile) => {
            const { provider, model } = describe(profile.endpoint_type, profile.default_model);
            return (
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
                  <button
                    type="button"
                    onClick={() => handleActivateClick(profile.id)}
                    disabled={activatingId === profile.id}
                    className="btn btn-ghost btn-sm text-xs flex items-center gap-1 text-[var(--accent-primary)] disabled:opacity-50"
                  >
                    <Zap size={14} />
                    {activatingId === profile.id
                      ? t('settings.profiles.activating')
                      : profile.is_active
                        ? t('settings.profiles.changeTargets')
                        : t('settings.profiles.activate')}
                  </button>
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
              <div className="mt-1 flex items-center gap-2 text-xs text-[var(--text-muted)] flex-wrap">
                <span>{provider}</span>
                {model && (
                  <>
                    <span>·</span>
                    <span className="font-mono">{model}</span>
                  </>
                )}
                <span>·</span>
                <span className="font-mono">{profile.api_key_masked}</span>
              </div>

              {/* Where this profile is actually in force. "Active" on its own
                  never said who it affected, which was the whole problem. */}
              {profile.is_active && activeTargets.length > 0 && (
                <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs text-[var(--text-muted)]">
                    {t('settings.profiles.activeOn')}
                  </span>
                  {activeTargets.map((agentType) => (
                    <span
                      key={agentType}
                      className="inline-flex items-center px-2 py-0.5 text-xs rounded-md bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]"
                    >
                      {targetName(agentType)}
                    </span>
                  ))}
                </div>
              )}

              {pickingTargetsFor === profile.id && (
                <div className="mt-3 pt-3 border-t border-[var(--border-color)] space-y-2">
                  <p className="text-xs font-medium text-[var(--text-secondary)]">
                    {t('settings.profiles.targetsTitle')}
                  </p>
                  {targets.length === 0 ? (
                    <p className="text-xs text-[var(--text-muted)]">
                      {t('settings.profiles.targetsUnavailable')}
                    </p>
                  ) : (
                    <div className="space-y-1.5">
                      {targets.map((target) => (
                        <label
                          key={target.agent_type}
                          className={`flex items-start gap-2 text-xs ${
                            target.selectable
                              ? 'text-[var(--text-primary)] cursor-pointer'
                              : 'text-[var(--text-muted)] cursor-not-allowed'
                          }`}
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5"
                            checked={pickedTargets.includes(target.agent_type)}
                            disabled={!target.selectable}
                            onChange={() => toggleTarget(target.agent_type)}
                          />
                          <span className="min-w-0">
                            <span className="font-medium">{target.display_name}</span>
                            {/* An option that is merely greyed out reads as a
                                bug; the reason is what makes it a decision. */}
                            {!target.supported && (
                              <span className="flex items-start gap-1 mt-0.5 text-[var(--text-muted)]">
                                <Ban size={11} className="mt-0.5 shrink-0" />
                                <span>{target.unsupported_reason}</span>
                              </span>
                            )}
                            {target.supported && !target.installed && (
                              <span className="block mt-0.5 text-[var(--text-muted)]">
                                {t('settings.profiles.targetNotInstalled')}
                              </span>
                            )}
                          </span>
                        </label>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => handleActivate(profile.id)}
                      disabled={
                        activatingId === profile.id ||
                        (selectableTargets.length > 0 && pickedTargets.length === 0)
                      }
                      className="btn btn-primary btn-sm text-xs disabled:opacity-50"
                    >
                      {activatingId === profile.id
                        ? t('settings.profiles.activating')
                        : t('settings.profiles.activate')}
                    </button>
                    <button
                      type="button"
                      onClick={handleCancelTargetPick}
                      className="btn btn-ghost btn-sm text-xs"
                    >
                      {t('settings.profiles.cancel')}
                    </button>
                  </div>
                </div>
              )}
            </div>
            );
          })}

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
