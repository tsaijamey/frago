import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  getProfiles,
  getEndpointPresets,
  getActivationTargets,
  getConnections,
  createProfile,
  updateProfile,
  deleteProfile,
  activateProfile,
  deactivateProfile,
  saveCurrentAsProfile,
} from '@/api';
import type {
  ActivationTarget,
  ConnectionKind,
  EndpointPreset,
  ProfileItem,
  VendorCore,
  CreateProfileRequest,
  UpdateProfileRequest,
} from '@/api';
import { useAppStore } from '@/stores/appStore';

export type ViewMode = 'list' | 'add' | 'edit';

interface UseProfilesArgs {
  isOpen: boolean;
  onClose: () => void;
  /** Fires after anything is created, edited, deleted, activated or
   *  deactivated — the surrounding page shows profile data too, and used to
   *  keep showing the old version until it was navigated away from. */
  onProfilesChanged?: () => void;
}

/**
 * useProfiles — owns all ProfileManager state and CRUD behavior:
 * list loading, the add/edit form, activate/deactivate/delete actions,
 * and the "save current config" inline flow. The modal just renders.
 */
export function useProfiles({ isOpen, onClose, onProfilesChanged }: UseProfilesArgs) {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  // Profile list state
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [activeTargets, setActiveTargets] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  // The agent CLIs a profile can be activated on. Activation used to mean
  // Claude Code and nothing else, silently — the picker exists so that the
  // person choosing can see who they are actually changing.
  const [targets, setTargets] = useState<ActivationTarget[]>([]);
  // Which profile's activate button was pressed; its picker is open.
  const [pickingTargetsFor, setPickingTargetsFor] = useState<string | null>(null);
  const [pickedTargets, setPickedTargets] = useState<string[]>([]);

  // The endpoints this build of frago knows how to talk to, straight from the
  // backend. The form used to hard-code this list and it fell behind.
  const [presets, setPresets] = useState<EndpointPreset[]>([]);

  // The cores that come with their own account (CodeBuddy). These are what a
  // vendor CLI connection names; frago holds no key for them, so the form
  // asks for a core and a model instead of an endpoint and a key.
  const [vendorCores, setVendorCores] = useState<VendorCore[]>([]);

  // View mode
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);

  // Form state
  const [formName, setFormName] = useState('');
  // Which shape of connection is being described. It decides which half of the
  // form is even meaningful: an endpoint and a key, or a core and a model.
  const [formKind, setFormKind] = useState<ConnectionKind>('endpoint');
  const [formAgentType, setFormAgentType] = useState('');
  const [formEndpointType, setFormEndpointType] = useState<string>('deepseek');
  const [formApiKey, setFormApiKey] = useState('');
  const [formUrl, setFormUrl] = useState('');
  const [formDefaultModel, setFormDefaultModel] = useState('');
  const [formSonnetModel, setFormSonnetModel] = useState('');
  const [formHaikuModel, setFormHaikuModel] = useState('');
  // The vendor's OpenAI Responses door — what Codex speaks. Blank on a preset
  // that knows one means "use the preset's"; blank anywhere else means none.
  const [formResponsesUrl, setFormResponsesUrl] = useState('');
  const [formResponsesModel, setFormResponsesModel] = useState('');
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
      loadPresets();
      loadTargets();
      loadVendorCores();
      setViewMode('list');
      setPickingTargetsFor(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // Escape key handler
  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Escape backs out one layer at a time; closing the whole dialog while
        // a target picker is open would read as the activation having happened.
        if (pickingTargetsFor) {
          setPickingTargetsFor(null);
        } else if (viewMode !== 'list') {
          setViewMode('list');
        } else {
          onClose();
        }
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, viewMode, pickingTargetsFor, onClose]);

  const loadProfiles = async () => {
    try {
      setLoading(true);
      const data = await getProfiles();
      setProfiles(data.profiles);
      setActiveProfileId(data.active_profile_id);
      setActiveTargets(data.active_targets ?? []);
    } catch {
      showToast('Failed to load profiles', 'error');
    } finally {
      setLoading(false);
    }
  };

  const loadTargets = async () => {
    try {
      const data = await getActivationTargets();
      setTargets(data.targets);
    } catch {
      // Without the roster there is nothing to pick from, so activation falls
      // back to what it has always done: Claude Code alone.
      setTargets([]);
    }
  };

  const loadVendorCores = async () => {
    try {
      const data = await getConnections();
      setVendorCores(data.vendor_cores);
    } catch {
      // Without the roster the vendor CLI option has nothing to offer, so the
      // form stays on endpoints — which is what it could always do.
      setVendorCores([]);
    }
  };

  const loadPresets = async () => {
    try {
      const data = await getEndpointPresets();
      setPresets(data.presets);
    } catch {
      // A missing preset list still leaves "Custom URL" workable, which is
      // more useful than blocking the whole dialog on it.
      setPresets([]);
    }
  };

  /** Reload the list here and tell the surrounding page to reload too. */
  const refreshAll = async () => {
    await loadProfiles();
    onProfilesChanged?.();
  };

  const resetForm = () => {
    setFormName('');
    setFormKind('endpoint');
    setFormAgentType('');
    setFormEndpointType(presets[0]?.id ?? 'custom');
    setFormApiKey('');
    setFormUrl('');
    setFormDefaultModel('');
    setFormSonnetModel('');
    setFormHaikuModel('');
    setFormResponsesUrl('');
    setFormResponsesModel('');
    setShowFormApiKey(false);
    setEditingProfileId(null);
  };

  const handleAddClick = () => {
    resetForm();
    setViewMode('add');
  };

  const handleEditClick = (profile: ProfileItem) => {
    setFormName(profile.name);
    setFormKind(profile.kind);
    setFormAgentType(profile.agent_type || '');
    setFormEndpointType(profile.endpoint_type);
    setFormApiKey(''); // Don't prefill API key
    setFormUrl(profile.url || '');
    setFormDefaultModel(profile.default_model || '');
    setFormSonnetModel(profile.sonnet_model || '');
    setFormHaikuModel(profile.haiku_model || '');
    // Only what was saved on this profile goes into the fields. A door filled in
    // from the vendor table shows as the placeholder, so saving the form without
    // touching it does not pin today's preset address onto the profile.
    const saved = profile.channels?.find((c) => c.protocol === 'responses' && c.source === 'profile');
    setFormResponsesUrl(saved?.url || '');
    setFormResponsesModel(saved?.models[0] || '');
    setShowFormApiKey(false);
    setEditingProfileId(profile.id);
    setViewMode('edit');
  };

  /**
   * What the form is currently describing, in the shape the API takes.
   *
   * Every optional field is sent on every save, empty ones included — that is
   * what makes clearing a model override possible. The old version dropped
   * blanks, so deleting an override looked like it saved and then came back.
   * A preset endpoint carries no URL of its own, so switching away from
   * "Custom URL" clears the stale one rather than leaving it on the card.
   */
  const formFields = () => {
    if (formKind === 'workbuddy') {
      // Retired 2026-10-09. The kind cannot be picked in the form any more, so
      // this branch is only reached by an old record opened for editing — it
      // still describes that record faithfully, and the backend refuses the
      // save with the reason. Turning it into an endpoint shape here would save
      // a connection that reaches somewhere nobody asked for.
      return {
        name: formName.trim(),
        kind: 'workbuddy' as ConnectionKind,
        endpoint_type: 'workbuddy',
        agent_type: null,
        url: null,
        default_model: formDefaultModel.trim() || null,
        sonnet_model: null,
        haiku_model: null,
      };
    }
    if (formKind === 'vendor_cli') {
      // A vendor CLI has no endpoint, no key and no per-tier model overrides —
      // its models come from its own service. Sending the endpoint fields
      // anyway would save a connection that looks half-configured on the card.
      return {
        name: formName.trim(),
        kind: 'vendor_cli' as ConnectionKind,
        endpoint_type: 'vendor_cli',
        agent_type: formAgentType,
        url: null,
        default_model: formDefaultModel.trim() || null,
        sonnet_model: null,
        haiku_model: null,
      };
    }
    const responsesUrl = formResponsesUrl.trim();
    const responsesModel = formResponsesModel.trim();
    return {
      name: formName.trim(),
      kind: 'endpoint' as ConnectionKind,
      endpoint_type: formEndpointType,
      agent_type: null,
      url: formEndpointType === 'custom' ? formUrl.trim() : null,
      default_model: formDefaultModel.trim() || null,
      sonnet_model: formSonnetModel.trim() || null,
      haiku_model: formHaikuModel.trim() || null,
      // Always sent, so emptying both fields removes a saved door. A preset that
      // knows a Responses door keeps offering it from the vendor table regardless.
      channels:
        responsesUrl || responsesModel
          ? [
              {
                protocol: 'responses',
                url: responsesUrl || null,
                models: responsesModel ? [responsesModel] : [],
              },
            ]
          : [],
    };
  };

  const handleFormSubmit = async () => {
    if (!formName.trim()) return;

    setFormSubmitting(true);
    try {
      if (viewMode === 'add') {
        // Only an endpoint connection has a key to demand; a vendor CLI runs on
        // its own login, and asking for a key there would be asking for
        // something that does not exist.
        if (formKind === 'endpoint' && !formApiKey.trim()) {
          showToast(t('errors.apiKeyEmpty'), 'error');
          setFormSubmitting(false);
          return;
        }
        const data: CreateProfileRequest = {
          ...formFields(),
          api_key: formKind === 'endpoint' ? formApiKey.trim() : '',
        };
        const result = await createProfile(data);
        if (result.status === 'ok') {
          showToast(t('settings.profiles.savedProfile'), 'success');
          await refreshAll();
          setViewMode('list');
          resetForm();
        } else {
          showToast(result.error || 'Failed to create profile', 'error');
        }
      } else if (viewMode === 'edit' && editingProfileId) {
        const data: UpdateProfileRequest = {
          ...formFields(),
          // Never prefilled, so a blank key means "keep the saved one".
          ...(formApiKey.trim() && { api_key: formApiKey.trim() }),
        };
        const result = await updateProfile(editingProfileId, data);
        if (result.status === 'ok') {
          showToast(t('settings.profiles.savedProfile'), 'success');
          await refreshAll();
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

  /** The agent CLIs that can actually be written to right now. */
  const selectableTargets = targets.filter((target) => target.selectable);

  /**
   * Whether this profile has the channel a CLI speaks. Codex speaks OpenAI
   * Responses only, so a profile with nothing but an Anthropic address has
   * nothing to give it — the picker says that instead of greying the box out.
   */
  const hasChannelFor = (profile: ProfileItem | undefined, target: ActivationTarget) => {
    const protocol = target.protocol ?? 'anthropic';
    // A backend too old to send channels only ever had the Anthropic door.
    if (!profile?.channels) return protocol === 'anthropic';
    return profile.channels.some((c) => c.protocol === protocol && !!c.url);
  };

  /** The CLIs this particular profile can be activated on. */
  const selectableTargetsFor = (profileId: string) => {
    const profile = profiles.find((p) => p.id === profileId);
    return selectableTargets.filter((target) => hasChannelFor(profile, target));
  };

  /**
   * Open the target picker for a profile.
   *
   * The boxes start on whatever is already in force, so re-activating the
   * active profile does not silently narrow it, and a first activation
   * pre-picks every usable CLI rather than making the person hunt for them.
   */
  const handleActivateClick = (profileId: string) => {
    const alreadyActive = profileId === activeProfileId ? activeTargets : [];
    const preselected = alreadyActive.length
      ? alreadyActive
      : selectableTargetsFor(profileId).map((target) => target.agent_type);
    setPickedTargets(preselected);
    setPickingTargetsFor(profileId);
  };

  const handleCancelTargetPick = () => setPickingTargetsFor(null);

  const toggleTarget = (agentType: string) => {
    setPickedTargets((current) =>
      current.includes(agentType)
        ? current.filter((t) => t !== agentType)
        : [...current, agentType],
    );
  };

  /**
   * Activate on the picked CLIs.
   *
   * `targets` is only left off when the backend never told us the roster —
   * then the request means "whatever activation has always meant", which the
   * backend resolves to Claude Code.
   */
  const handleActivate = async (profileId: string, chosen?: string[]) => {
    setActivatingId(profileId);
    try {
      // A box this profile cannot fill (no Responses door for Codex) never goes
      // out, even if it was ticked when a different profile held the picker.
      const allowed = selectableTargetsFor(profileId).map((target) => target.agent_type);
      const result = await activateProfile(
        profileId,
        chosen ??
          (selectableTargets.length
            ? pickedTargets.filter((agentType) => allowed.includes(agentType))
            : undefined),
      );
      if (result.status === 'ok') {
        const profile = profiles.find((p) => p.id === profileId);
        showToast(`${t('settings.profiles.switchedTo')} ${profile?.name || ''}`, 'success');
        setPickingTargetsFor(null);
        await refreshAll();
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
        await refreshAll();
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
        await refreshAll();
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
        await refreshAll();
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
    activeTargets,
    targets,
    selectableTargets,
    hasChannelFor,
    selectableTargetsFor,
    pickingTargetsFor,
    pickedTargets,
    presets,
    vendorCores,
    loading,
    viewMode,
    setViewMode,
    formName,
    setFormName,
    formKind,
    setFormKind,
    formAgentType,
    setFormAgentType,
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
    formResponsesUrl,
    setFormResponsesUrl,
    formResponsesModel,
    setFormResponsesModel,
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
    handleActivateClick,
    handleCancelTargetPick,
    toggleTarget,
    handleActivate,
    handleDeactivate,
    handleDelete,
    handleSaveCurrent,
  };
}

export type ProfilesController = ReturnType<typeof useProfiles>;
