import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
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

export type ViewMode = 'list' | 'add' | 'edit';

interface UseProfilesArgs {
  isOpen: boolean;
  onClose: () => void;
  onProfileActivated?: () => void;
}

/**
 * useProfiles — owns all ProfileManager state and CRUD behavior:
 * list loading, the add/edit form, activate/deactivate/delete actions,
 * and the "save current config" inline flow. The modal just renders.
 */
export function useProfiles({ isOpen, onClose, onProfileActivated }: UseProfilesArgs) {
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  return {
    t,
    profiles,
    activeProfileId,
    loading,
    viewMode,
    setViewMode,
    formName,
    setFormName,
    formEndpointType,
    setFormEndpointType,
    formApiKey,
    setFormApiKey,
    formUrl,
    setFormUrl,
    formDefaultModel,
    setFormDefaultModel,
    formSonnetModel,
    setFormSonnetModel,
    formHaikuModel,
    setFormHaikuModel,
    showFormApiKey,
    setShowFormApiKey,
    formSubmitting,
    activatingId,
    deletingId,
    savingCurrent,
    showSaveCurrentInput,
    setShowSaveCurrentInput,
    saveCurrentName,
    setSaveCurrentName,
    resetForm,
    handleAddClick,
    handleEditClick,
    handleFormSubmit,
    handleActivate,
    handleDeactivate,
    handleDelete,
    handleSaveCurrent,
  };
}

export type ProfilesController = ReturnType<typeof useProfiles>;
