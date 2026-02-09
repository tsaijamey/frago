/**
 * ProfileManager - Modal for managing API endpoint profiles
 *
 * Provides CRUD operations and quick-switch for saved API configurations.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createPortal } from 'react-dom';
import { X, Plus, Check, Pencil, Trash2, Eye, EyeOff, Save, Zap } from 'lucide-react';
import {
  getProfiles,
  createProfile,
  updateProfile,
  deleteProfile,
  activateProfile,
  deactivateProfile,
  saveCurrentAsProfile,
} from '@/api';
import type { ProfileItem, CreateProfileRequest, UpdateProfileRequest } from '@/api';
import { useAppStore } from '@/stores/appStore';

interface ProfileManagerProps {
  isOpen: boolean;
  onClose: () => void;
  onProfileActivated?: () => void;
  hasCustomConfig?: boolean; // Whether a custom API config is currently active
}

type ViewMode = 'list' | 'add' | 'edit';

const ENDPOINT_LABELS: Record<string, string> = {
  deepseek: 'DeepSeek',
  aliyun: 'Aliyun',
  kimi: 'Kimi',
  minimax: 'MiniMax',
  custom: 'Custom URL',
};

export default function ProfileManager({
  isOpen,
  onClose,
  onProfileActivated,
  hasCustomConfig,
}: ProfileManagerProps) {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  // Profile list state
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // View mode
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);

  // Form state
  const [formName, setFormName] = useState('');
  const [formEndpointType, setFormEndpointType] = useState<string>('deepseek');
  const [formApiKey, setFormApiKey] = useState('');
  const [formUrl, setFormUrl] = useState('');
  const [formDefaultModel, setFormDefaultModel] = useState('');
  const [formSonnetModel, setFormSonnetModel] = useState('');
  const [formHaikuModel, setFormHaikuModel] = useState('');
  const [showFormApiKey, setShowFormApiKey] = useState(false);
  const [formSubmitting, setFormSubmitting] = useState(false);

  // Action loading states
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [savingCurrent, setSavingCurrent] = useState(false);

  // Save current config modal
  const [showSaveCurrentInput, setShowSaveCurrentInput] = useState(false);
  const [saveCurrentName, setSaveCurrentName] = useState('');

  useEffect(() => {
    if (isOpen) {
      loadProfiles();
      setViewMode('list');
    }
  }, [isOpen]);

  // Escape key handler
  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (viewMode !== 'list') {
          setViewMode('list');
        } else {
          onClose();
        }
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, viewMode, onClose]);

  const loadProfiles = async () => {
    try {
      setLoading(true);
      const data = await getProfiles();
      setProfiles(data.profiles);
      setActiveProfileId(data.active_profile_id);
    } catch {
      showToast('Failed to load profiles', 'error');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setFormName('');
    setFormEndpointType('deepseek');
    setFormApiKey('');
    setFormUrl('');
    setFormDefaultModel('');
    setFormSonnetModel('');
    setFormHaikuModel('');
    setShowFormApiKey(false);
    setEditingProfileId(null);
  };

  const handleAddClick = () => {
    resetForm();
    setViewMode('add');
  };

  const handleEditClick = (profile: ProfileItem) => {
    setFormName(profile.name);
    setFormEndpointType(profile.endpoint_type);
    setFormApiKey(''); // Don't prefill API key
    setFormUrl(profile.url || '');
    setFormDefaultModel(profile.default_model || '');
    setFormSonnetModel(profile.sonnet_model || '');
    setFormHaikuModel(profile.haiku_model || '');
    setShowFormApiKey(false);
    setEditingProfileId(profile.id);
    setViewMode('edit');
  };

  const handleFormSubmit = async () => {
    if (!formName.trim()) return;

    setFormSubmitting(true);
    try {
      if (viewMode === 'add') {
        if (!formApiKey.trim()) {
          showToast(t('errors.apiKeyEmpty'), 'error');
          setFormSubmitting(false);
          return;
        }
        const data: CreateProfileRequest = {
          name: formName.trim(),
          endpoint_type: formEndpointType,
          api_key: formApiKey.trim(),
          ...(formEndpointType === 'custom' && formUrl.trim() && { url: formUrl.trim() }),
          ...(formDefaultModel.trim() && { default_model: formDefaultModel.trim() }),
          ...(formSonnetModel.trim() && { sonnet_model: formSonnetModel.trim() }),
          ...(formHaikuModel.trim() && { haiku_model: formHaikuModel.trim() }),
        };
        const result = await createProfile(data);
        if (result.status === 'ok') {
          showToast(t('settings.profiles.savedProfile'), 'success');
          await loadProfiles();
          setViewMode('list');
          resetForm();
        } else {
          showToast(result.error || 'Failed to create profile', 'error');
        }
      } else if (viewMode === 'edit' && editingProfileId) {
        const data: UpdateProfileRequest = {
          name: formName.trim(),
          endpoint_type: formEndpointType,
          ...(formApiKey.trim() && { api_key: formApiKey.trim() }),
          ...(formEndpointType === 'custom' && { url: formUrl.trim() }),
          ...(formDefaultModel.trim() && { default_model: formDefaultModel.trim() }),
          ...(formSonnetModel.trim() && { sonnet_model: formSonnetModel.trim() }),
          ...(formHaikuModel.trim() && { haiku_model: formHaikuModel.trim() }),
        };
        const result = await updateProfile(editingProfileId, data);
        if (result.status === 'ok') {
          showToast(t('settings.profiles.savedProfile'), 'success');
          await loadProfiles();
          setViewMode('list');
          resetForm();
        } else {
          showToast(result.error || 'Failed to update profile', 'error');
        }
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save profile', 'error');
    } finally {
      setFormSubmitting(false);
    }
  };

  const handleActivate = async (profileId: string) => {
    setActivatingId(profileId);
    try {
      const result = await activateProfile(profileId);
      if (result.status === 'ok') {
        const profile = profiles.find((p) => p.id === profileId);
        showToast(`${t('settings.profiles.switchedTo')} ${profile?.name || ''}`, 'success');
        await loadProfiles();
        onProfileActivated?.();
      } else {
        showToast(result.error || 'Failed to activate profile', 'error');
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to activate', 'error');
    } finally {
      setActivatingId(null);
    }
  };

  const handleDeactivate = async () => {
    setActivatingId('__deactivate__');
    try {
      const result = await deactivateProfile();
      if (result.status === 'ok') {
        showToast(t('settings.profiles.deactivate'), 'success');
        await loadProfiles();
        onProfileActivated?.();
      } else {
        showToast(result.error || 'Failed to deactivate', 'error');
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to deactivate', 'error');
    } finally {
      setActivatingId(null);
    }
  };

  const handleDelete = async (profileId: string) => {
    if (!confirm(t('settings.profiles.confirmDelete'))) return;

    setDeletingId(profileId);
    try {
      const result = await deleteProfile(profileId);
      if (result.status === 'ok') {
        showToast(t('settings.profiles.deletedProfile'), 'success');
        await loadProfiles();
      } else {
        showToast(result.error || 'Failed to delete profile', 'error');
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to delete', 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const handleSaveCurrent = async () => {
    if (!saveCurrentName.trim()) return;
    setSavingCurrent(true);
    try {
      const result = await saveCurrentAsProfile(saveCurrentName.trim());
      if (result.status === 'ok') {
        showToast(t('settings.profiles.currentConfigSaved'), 'success');
        await loadProfiles();
        setShowSaveCurrentInput(false);
        setSaveCurrentName('');
      } else {
        showToast(result.error || 'Failed to save current config', 'error');
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to save', 'error');
    } finally {
      setSavingCurrent(false);
    }
  };

  if (!isOpen) return null;

  const renderForm = () => (
    <div className="space-y-3">
      {/* Profile name */}
      <div>
        <label htmlFor="profile-name" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.profileName')}
        </label>
        <input
          id="profile-name"
          type="text"
          value={formName}
          onChange={(e) => setFormName(e.target.value)}
          placeholder={t('settings.profiles.profileNamePlaceholder')}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
          autoFocus
        />
      </div>

      {/* Endpoint type */}
      <div>
        <label htmlFor="profile-endpoint-type" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.endpointType')}
        </label>
        <select
          id="profile-endpoint-type"
          value={formEndpointType}
          onChange={(e) => setFormEndpointType(e.target.value)}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
        >
          <option value="deepseek">DeepSeek API</option>
          <option value="aliyun">Aliyun API</option>
          <option value="kimi">Kimi API</option>
          <option value="minimax">MiniMax API</option>
          <option value="custom">Custom URL</option>
        </select>
      </div>

      {/* Custom URL */}
      {formEndpointType === 'custom' && (
        <div>
          <label htmlFor="profile-url" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.apiUrl')}
          </label>
          <input
            id="profile-url"
            type="text"
            value={formUrl}
            onChange={(e) => setFormUrl(e.target.value)}
            placeholder="https://api.example.com/anthropic"
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
      )}

      {/* API Key */}
      <div>
        <label htmlFor="profile-api-key" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.apiKey')}
          {viewMode === 'edit' && (
            <span className="ml-2 text-[var(--text-muted)]">({t('settings.general.leaveEmptyToKeep')})</span>
          )}
        </label>
        <div className="flex gap-2">
          <input
            id="profile-api-key"
            type={showFormApiKey ? 'text' : 'password'}
            value={formApiKey}
            onChange={(e) => setFormApiKey(e.target.value)}
            placeholder={viewMode === 'edit' ? t('settings.general.leaveEmptyToKeep') : t('settings.general.enterApiKey')}
            className="flex-1 px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
          <button
            type="button"
            onClick={() => setShowFormApiKey(!showFormApiKey)}
            className="btn btn-ghost btn-sm p-2"
            aria-label={showFormApiKey ? t('settings.general.hideApiKey') : t('settings.general.showApiKey')}
          >
            {showFormApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </div>

      {/* Model overrides */}
      <div>
        <label htmlFor="profile-default-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
          {t('settings.profiles.defaultModel')}
          {formEndpointType !== 'custom' && <span className="ml-1 text-[var(--text-muted)]">- {t('settings.general.optionalOverride')}</span>}
        </label>
        <input
          id="profile-default-model"
          type="text"
          value={formDefaultModel}
          onChange={(e) => setFormDefaultModel(e.target.value)}
          placeholder={formEndpointType === 'custom' ? 'e.g., gpt-4' : t('settings.general.leaveEmptyDefault')}
          className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="profile-sonnet-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.sonnetModel')}
          </label>
          <input
            id="profile-sonnet-model"
            type="text"
            value={formSonnetModel}
            onChange={(e) => setFormSonnetModel(e.target.value)}
            placeholder={t('settings.general.optionalOverride')}
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
        <div>
          <label htmlFor="profile-haiku-model" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">
            {t('settings.profiles.haikuModel')}
          </label>
          <input
            id="profile-haiku-model"
            type="text"
            value={formHaikuModel}
            onChange={(e) => setFormHaikuModel(e.target.value)}
            placeholder={t('settings.general.optionalOverride')}
            className="w-full px-3 py-2 text-sm bg-[var(--bg-base)] border border-[var(--border-color)] rounded-md text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)] font-mono"
          />
        </div>
      </div>

      {/* Form actions */}
      <div className="flex gap-2 pt-2">
        <button
          type="button"
          onClick={handleFormSubmit}
          disabled={formSubmitting || !formName.trim()}
          className="btn btn-primary btn-sm disabled:opacity-50"
        >
          {formSubmitting
            ? viewMode === 'add'
              ? t('settings.profiles.creating')
              : t('settings.profiles.updating')
            : t('settings.profiles.save')}
        </button>
        <button
          type="button"
          onClick={() => {
            setViewMode('list');
            resetForm();
          }}
          className="btn btn-ghost btn-sm"
        >
          {t('settings.profiles.cancel')}
        </button>
      </div>
    </div>
  );

  const renderProfileList = () => (
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

  return createPortal(
    <div
      className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-[1100]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="bg-[var(--bg-base)] rounded-lg shadow-xl max-w-lg w-full mx-4 border border-[var(--border-color)] max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-[var(--border-color)] shrink-0">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">
            {viewMode === 'add'
              ? t('settings.profiles.addProfile')
              : viewMode === 'edit'
                ? t('settings.profiles.edit')
                : t('settings.profiles.title')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
            aria-label="Close modal"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-4 overflow-y-auto">
          {loading ? (
            <div className="text-[var(--text-muted)] text-center py-8 text-sm">
              Loading...
            </div>
          ) : viewMode === 'list' ? (
            renderProfileList()
          ) : (
            renderForm()
          )}
        </div>

        {/* Footer */}
        {viewMode === 'list' && (
          <div className="flex justify-end p-4 border-t border-[var(--border-color)] shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-ghost btn-sm"
            >
              {t('settings.profiles.close')}
            </button>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
