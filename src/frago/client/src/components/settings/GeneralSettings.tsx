/**
 * General Settings Component (Settings ▸ General)
 *
 * Implements the 3-segment tabbed layout (harnesses / sidecar / profiles):
 * 1. Harness 工具 — Built-in CoreAgent + 4 external CLI coding tools with independent Daily Session & Worker bindings + single-line Danger Zone
 * 2. 旁路与轻量 AI — LightAgent, Session Observer, Desktop Speech Recognition (ASR), and inline Decision Model configuration
 * 3. AI 服务商 — 5-column provider & protocol routing table with live reverse-reference chips
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  getMainConfig,
  getProfiles,
  getConnections,
  bindHarness,
  bindRole,
  deleteProfile,
  getHookReviewStatus,
  setHookReviewEnabled,
  getDecisionModelSettings,
  updateDecisionModelSettings,
  resetDecisionModelSettings,
  openConfigInVSCode,
} from '@/api';
import type {
  ConnectionRole,
  DecisionModelSettings,
  DecisionWireMode,
  HarnessBinding,
  HookReviewStatus,
  ProfileItem,
  RoleBinding,
} from '@/api';
import type { MainConfig } from '@/types/pywebview';
import {
  AlertTriangle,
  Check,
  Code,
  Eye,
  EyeOff,
  Gauge,
  KeyRound,
  Mic,
  Pencil,
  Plus,
  Sparkles,
  Terminal,
  Trash2,
  X,
} from 'lucide-react';
import ProfileManager from '@/components/settings/ProfileManager';
import type { InitialProfileModalMode } from '@/components/settings/useProfiles';
import Modal from '@/components/ui/Modal';

export type GeneralSubTab = 'harnesses' | 'sidecar' | 'profiles';

interface GeneralSettingsProps {
  /**
   * Incremented by the capability panel when the user clicks through to
   * configure a model provider. Switches to the `profiles` tab and opens
   * the provider modal.
   */
  openProfilesSignal?: number;
}

const DEFAULT_HARNESSES: HarnessBinding[] = [
  {
    agent_type: 'coreagent',
    display_name: 'CoreAgent',
    protocol: 'anthropic',
    protocol_label: '内置内核 · Anthropic',
    config_path: '~/.frago/profiles.json',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'follow',
  },
  {
    agent_type: 'claude',
    display_name: 'Claude Code',
    protocol: 'anthropic',
    protocol_label: 'Anthropic',
    config_path: '~/.claude/settings.json',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'follow',
  },
  {
    agent_type: 'codex',
    display_name: 'Codex CLI',
    protocol: 'responses',
    protocol_label: 'OpenAI Responses',
    config_path: '~/.codex/config.toml',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'follow',
  },
  {
    agent_type: 'opencode',
    display_name: 'opencode',
    protocol: 'anthropic',
    protocol_label: 'Anthropic',
    config_path: '~/.config/opencode/opencode.json',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'follow',
  },
  {
    agent_type: 'agy',
    display_name: 'Antigravity CLI',
    protocol: 'gemini',
    protocol_label: 'Gemini / 厂商 CLI',
    config_path: '~/.gemini/antigravity-cli/settings.json',
    installed: true,
    main_profile_id: 'official',
    worker_profile_id: 'follow',
  },
];

function hasProtocolChannel(profile: ProfileItem, protocol: string): boolean {
  if (profile.kind !== 'endpoint') return false;
  if (!profile.channels || profile.channels.length === 0) {
    return protocol === 'anthropic';
  }
  return profile.channels.some((c) => c.protocol === protocol && Boolean(c.url));
}

function modelForHarness(profile: ProfileItem | undefined | null, agentType: string): string {
  if (!profile) return '';
  if (agentType === 'codex') {
    const ch = profile.channels?.find((c) => c.protocol === 'responses');
    if (ch?.models && ch.models.length > 0) return ch.models[0];
  }
  if (agentType === 'agy') {
    const ch = profile.channels?.find((c) => c.protocol === 'gemini');
    if (ch?.models && ch.models.length > 0) return ch.models[0];
  }
  return profile.default_model || '';
}

function getProfileProtocolTags(profile: ProfileItem): Array<{ label: string; url?: string | null }> {
  if (profile.kind === 'vendor_cli') {
    const core = profile.agent_type || 'agy';
    return [{ label: core === 'agy' ? 'Gemini (agy)' : `CLI (${core})`, url: null }];
  }
  if (profile.kind !== 'endpoint') {
    return [];
  }
  const tags: Array<{ label: string; url?: string | null }> = [];
  if (profile.channels && profile.channels.length > 0) {
    for (const ch of profile.channels) {
      if (!ch.url) continue;
      if (ch.protocol === 'anthropic') {
        tags.push({ label: 'Anthropic', url: ch.url });
      } else if (ch.protocol === 'responses') {
        tags.push({ label: 'OpenAI Responses', url: ch.url });
      } else if (ch.protocol === 'gemini') {
        tags.push({ label: 'Gemini', url: ch.url });
      } else {
        tags.push({ label: ch.protocol, url: ch.url });
      }
    }
  } else if (profile.url || profile.endpoint_type !== 'custom') {
    tags.push({ label: 'Anthropic', url: profile.url });
  }
  return tags;
}

export default function GeneralSettings({ openProfilesSignal = 0 }: GeneralSettingsProps = {}) {
  const { t } = useTranslation();
  const [subTab, setSubTab] = useState<GeneralSubTab>('harnesses');
  const [config, setConfig] = useState<MainConfig | null>(null);
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [bindings, setBindings] = useState<RoleBinding[]>([]);
  const [harnesses, setHarnesses] = useState<HarnessBinding[]>(DEFAULT_HARNESSES);
  const [hookReview, setHookReview] = useState<HookReviewStatus | null>(null);
  const [decisionSettings, setDecisionSettings] = useState<DecisionModelSettings | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [vscodeNotice, setVscodeNotice] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  // Danger Zone state
  const [selectedDangerAgent, setSelectedDangerAgent] = useState<string>('claude');

  // Decision Model inline form state
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionSaving, setDecisionSaving] = useState(false);
  const [decisionEnabled, setDecisionEnabled] = useState(true);
  const [decisionWire, setDecisionWire] = useState<DecisionWireMode>('decisions');
  const [decisionUrl, setDecisionUrl] = useState('');
  const [decisionModel, setDecisionModel] = useState('');
  const [decisionApiKey, setDecisionApiKey] = useState('');
  const [decisionClearKey, setDecisionClearKey] = useState(false);
  const [decisionShowKey, setDecisionShowKey] = useState(false);
  const [decisionTemperature, setDecisionTemperature] = useState('');

  // Profile Manager Modal state
  const [showProfileManager, setShowProfileManager] = useState(false);
  const [modalMode, setModalMode] = useState<InitialProfileModalMode>('list');
  const [editingProfile, setEditingProfile] = useState<ProfileItem | null>(null);
  const [deletingProfile, setDeletingProfile] = useState<ProfileItem | null>(null);

  useEffect(() => {
    void loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (openProfilesSignal > 0) {
      setSubTab('profiles');
      setModalMode('add-endpoint');
      setEditingProfile(null);
      setShowProfileManager(true);
    }
  }, [openProfilesSignal]);

  const populateDecisionForm = (data: DecisionModelSettings) => {
    setDecisionEnabled(data.configured ? data.enabled : true);
    setDecisionWire(data.wire);
    setDecisionUrl(data.url ?? '');
    setDecisionModel(data.model ?? '');
    setDecisionApiKey('');
    setDecisionClearKey(false);
    setDecisionShowKey(false);
    setDecisionTemperature(data.temperature != null ? String(data.temperature) : '');
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const [configData, profileData, connectionData, hookData, decisionData] = await Promise.all([
        getMainConfig(),
        getProfiles(),
        getConnections().catch(() => ({
          connections: [],
          bindings: [],
          vendor_cores: [],
          harnesses: [],
        })),
        getHookReviewStatus().catch(() => null),
        getDecisionModelSettings().catch(() => null),
      ]);

      setConfig(configData);
      setProfiles(profileData.profiles);
      setBindings(connectionData.bindings);
      if (connectionData.harnesses && connectionData.harnesses.length > 0) {
        setHarnesses(connectionData.harnesses);
      } else {
        const coreRoleBinding = connectionData.bindings?.find((b) => b.role === 'coreagent');
        setHarnesses(
          DEFAULT_HARNESSES.map((h) => ({
            ...h,
            main_profile_id:
              h.agent_type === 'coreagent'
                ? coreRoleBinding?.profile_id || 'official'
                : profileData.active_profile_id &&
                    (profileData.active_targets ?? ['claude']).includes(h.agent_type)
                  ? profileData.active_profile_id
                  : 'official',
            worker_profile_id:
              h.agent_type === 'coreagent'
                ? 'follow'
                : profileData.worker_profile_id || 'follow',
          })),
        );
      }
      if (hookData) {
        setHookReview(hookData);
      }
      if (decisionData) {
        setDecisionSettings(decisionData);
        populateDecisionForm(decisionData);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToLoadConfig'));
    } finally {
      setLoading(false);
    }
  };

  const findProfile = (pid: string | null | undefined): ProfileItem | null => {
    if (!pid || pid === 'official' || pid === 'follow') return null;
    return profiles.find((p) => p.id === pid) ?? null;
  };

  const handleBindHarness = async (
    agentType: string,
    role: 'main' | 'worker',
    profileId: string,
  ) => {
    setBusyKey(`${agentType}:${role}`);
    setError(null);
    try {
      const result = await bindHarness(agentType, role, profileId);
      if (result.status === 'ok') {
        await loadData();
      } else {
        setError(result.error || t('settings.connections.bindFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.connections.bindFailed'));
    } finally {
      setBusyKey(null);
    }
  };

  const handleRevertAllHarnesses = async () => {
    setBusyKey('revert-all');
    setError(null);
    try {
      const activeHarnesses = harnesses.filter((h) => h.main_profile_id !== 'official');
      for (const h of activeHarnesses) {
        const res = await bindHarness(h.agent_type, 'main', 'official');
        if (res.status !== 'ok') {
          setError(res.error || t('errors.deactivateFailed'));
          break;
        }
      }
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('errors.deactivateFailed'));
    } finally {
      setBusyKey(null);
    }
  };

  const handleBindSidecar = async (role: ConnectionRole, profileId: string) => {
    setBusyKey(`sidecar:${role}`);
    setError(null);
    try {
      const result = await bindRole(role, profileId);
      if (result.status === 'ok') {
        await loadData();
      } else {
        setError(result.error || t('settings.connections.bindFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.connections.bindFailed'));
    } finally {
      setBusyKey(null);
    }
  };

  const handleToggleHookReview = async () => {
    const current = hookReview ? hookReview.enabled : true;
    setBusyKey('hook-review');
    setError(null);
    try {
      const updated = await setHookReviewEnabled(!current);
      setHookReview(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.capability.saveFailed'));
    } finally {
      setBusyKey(null);
    }
  };

  const handleSaveDecisionModel = async () => {
    try {
      setDecisionSaving(true);
      setError(null);
      const parsedTemp =
        decisionTemperature.trim() !== '' ? Number(decisionTemperature.trim()) : null;
      if (parsedTemp !== null && (Number.isNaN(parsedTemp) || parsedTemp <= 0)) {
        setError(t('settings.decisionModel.saveFailed'));
        setDecisionSaving(false);
        return;
      }
      const updated = await updateDecisionModelSettings({
        enabled: decisionEnabled,
        wire: decisionWire,
        url: decisionUrl.trim() || null,
        model: decisionModel.trim(),
        api_key: decisionApiKey.trim() || null,
        clear_api_key: decisionClearKey,
        temperature: parsedTemp,
      });
      setDecisionSettings(updated);
      populateDecisionForm(updated);
      setDecisionOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.decisionModel.saveFailed'));
    } finally {
      setDecisionSaving(false);
    }
  };

  const handleResetDecisionModel = async () => {
    try {
      setDecisionSaving(true);
      setError(null);
      const resetData = await resetDecisionModelSettings();
      setDecisionSettings(resetData);
      populateDecisionForm(resetData);
      setDecisionOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.decisionModel.saveFailed'));
    } finally {
      setDecisionSaving(false);
    }
  };

  const handleOpenInVSCode = async () => {
    setError(null);
    setVscodeNotice(null);
    try {
      const targetHarness =
        harnesses.find((h) => h.agent_type === selectedDangerAgent) ?? harnesses[0];
      const result = await openConfigInVSCode(selectedDangerAgent);
      if (result.status === 'error') {
        setError(result.error || t('settings.general.failedToOpenVSCode'));
      } else {
        setVscodeNotice(
          t('settings.general.danger.openedNotice', {
            name: targetHarness?.display_name ?? selectedDangerAgent,
            path: targetHarness?.config_path ?? '',
          }),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToOpenVSCode'));
    }
  };

  const openProfileModal = (
    mode: InitialProfileModalMode,
    profile: ProfileItem | null = null,
  ) => {
    setModalMode(mode);
    setEditingProfile(profile);
    setShowProfileManager(true);
  };

  const confirmDeleteProfile = async () => {
    if (!deletingProfile) return;
    setBusyKey(`delete:${deletingProfile.id}`);
    setError(null);
    try {
      const res = await deleteProfile(deletingProfile.id);
      if (res.status === 'ok') {
        setDeletingProfile(null);
        await loadData();
      } else {
        setError(res.error || t('settings.general.providers.deleteFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.providers.deleteFailed'));
    } finally {
      setBusyKey(null);
    }
  };

  /** Compute live reverse-reference chips for each saved AI provider. */
  const computeProfileRefs = (): Record<string, string[]> => {
    const map: Record<string, string[]> = {};
    for (const p of profiles) {
      map[p.id] = [];
    }
    for (const h of harnesses) {
      if (h.main_profile_id && h.main_profile_id !== 'official' && map[h.main_profile_id]) {
        map[h.main_profile_id].push(
          t('settings.general.providers.refDaily', { name: h.display_name }),
        );
      }
      if (
        h.worker_profile_id &&
        h.worker_profile_id !== 'follow' &&
        h.worker_profile_id !== 'official' &&
        map[h.worker_profile_id]
      ) {
        map[h.worker_profile_id].push(
          t('settings.general.providers.refWorker', { name: h.display_name }),
        );
      }
    }
    const lightBinding = bindings.find((b) => b.role === 'lightagent');
    const obsBinding = bindings.find((b) => b.role === 'observer');
    const asrBinding = bindings.find((b) => b.role === 'asr');

    const lightPid = lightBinding?.profile_id || lightBinding?.connection?.id;
    if (lightPid && map[lightPid]) {
      map[lightPid].push(t('settings.general.providers.refLight'));
    }
    const obsPid = obsBinding?.profile_id;
    if (obsPid && map[obsPid]) {
      map[obsPid].push(t('settings.general.providers.refObserver'));
    }
    const asrPid = asrBinding?.profile_id || asrBinding?.connection?.id;
    if (asrPid && map[asrPid]) {
      map[asrPid].push(t('settings.general.providers.refAsr'));
    }
    return map;
  };

  if (loading) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        {t('common.loadingConfiguration')}
      </div>
    );
  }

  if (!config) {
    return (
      <div className="text-[var(--text-error)] text-center py-8">
        {t('settings.general.failedToLoadConfig')}
      </div>
    );
  }

  const refsByProfile = computeProfileRefs();
  const hasAnyNonOfficialHarness = harnesses.some((h) => h.main_profile_id !== 'official');

  const lightBinding = bindings.find((b) => b.role === 'lightagent');
  const obsBinding = bindings.find((b) => b.role === 'observer');
  const asrBinding = bindings.find((b) => b.role === 'asr');

  const lightConnection = lightBinding?.connection ?? profiles[0] ?? null;
  const obsConnection = obsBinding?.profile_id ? (obsBinding.connection ?? findProfile(obsBinding.profile_id)) : null;
  const asrConnection =
    asrBinding?.connection ?? (asrBinding?.profile_id ? findProfile(asrBinding.profile_id) : null);

  const lightModelLabel =
    lightConnection?.haiku_model ||
    lightConnection?.default_model ||
    hookReview?.lightagent?.model ||
    t('settings.general.sidecar.unconfigured');
  const obsModelLabel =
    obsConnection?.haiku_model || obsConnection?.default_model || null;
  const asrModelLabel =
    asrConnection?.default_model || asrConnection?.haiku_model || 'whisper-large-v3-turbo';
  const hookReviewEnabled = hookReview ? hookReview.enabled : true;

  const renderSidecarOptions = (useDefaultModel = false) =>
    profiles.map((p) => {
      if (p.kind === 'workbuddy') {
        return (
          <option key={p.id} value={p.id} disabled>
            {t('settings.general.harnesses.optDisabledWorkbuddy', { name: p.name })}
          </option>
        );
      }
      if (p.kind === 'vendor_cli') {
        return (
          <option key={p.id} value={p.id} disabled>
            {t('settings.general.harnesses.optDisabledVendorNoKey', { name: p.name })}
          </option>
        );
      }
      const modelHint = useDefaultModel
        ? p.default_model || p.haiku_model
        : p.haiku_model || p.default_model;
      return (
        <option key={p.id} value={p.id}>
          {p.name}
          {modelHint ? ` (${modelHint})` : ''}
        </option>
      );
    });

  return (
    <div className="space-y-3">
      {error && (
        <div className="salert err" data-testid="general-bind-err">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {vscodeNotice && (
        <div
          className="salert ok"
          style={{ justifyContent: 'space-between', alignItems: 'center' }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <Check size={14} />
            <span>{vscodeNotice}</span>
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setVscodeNotice(null)}
          >
            {t('settings.general.danger.gotIt')}
          </button>
        </div>
      )}

      {/* 顶部三段子视图切换器 */}
      <div className="g-topbar">
        <div className="g-seg" role="tablist" aria-label={t('settings.general.tabs.ariaLabel')}>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'harnesses'}
            className={subTab === 'harnesses' ? 'on' : ''}
            onClick={() => setSubTab('harnesses')}
            data-testid="general-tab-harnesses"
          >
            <Terminal size={13} />
            <span>{t('settings.general.tabs.harnesses')}</span>
            <span className="cnt">{harnesses.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'sidecar'}
            className={subTab === 'sidecar' ? 'on' : ''}
            onClick={() => setSubTab('sidecar')}
            data-testid="general-tab-sidecar"
          >
            <Sparkles size={13} />
            <span>{t('settings.general.tabs.sidecar')}</span>
            <span className="cnt">4</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'profiles'}
            className={subTab === 'profiles' ? 'on' : ''}
            onClick={() => setSubTab('profiles')}
            data-testid="general-tab-profiles"
          >
            <KeyRound size={13} />
            <span>{t('settings.general.tabs.profiles')}</span>
            <span className="cnt">{profiles.length}</span>
          </button>
        </div>
      </div>

      {/* 子视图 1：Harness 工具 */}
      {subTab === 'harnesses' && (
        <>
          <div className="s-card" data-testid="zone-harnesses">
            <div className="ssec">
              <div className="ssec-h">
                <div>
                  <h3>{t('settings.general.harnesses.title')}</h3>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                    {t('settings.general.harnesses.subtitle')}
                  </div>
                </div>
                {hasAnyNonOfficialHarness && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={busyKey !== null}
                    onClick={handleRevertAllHarnesses}
                    data-testid="revert-all-harnesses-btn"
                  >
                    {t('settings.general.harnesses.revertAll')}
                  </button>
                )}
              </div>

              <div className="stbl-wrap">
                <table className="htbl">
                  <thead>
                    <tr>
                      <th style={{ width: '29%' }}>
                        {t('settings.general.harnesses.colTool')}
                        <span className="sub">{t('settings.general.harnesses.colToolSub')}</span>
                      </th>
                      <th style={{ width: '35.5%' }}>
                        {t('settings.general.harnesses.colDaily')}
                        <span className="sub">{t('settings.general.harnesses.colDailySub')}</span>
                      </th>
                      <th style={{ width: '35.5%' }}>
                        {t('settings.general.harnesses.colWorker')}
                        <span className="sub">{t('settings.general.harnesses.colWorkerSub')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {harnesses.map((h) => {
                      const isBuiltin = h.agent_type === 'coreagent';
                      const curMain = h.main_profile_id || 'official';
                      const curWorker = h.worker_profile_id || 'follow';
                      const mainP = findProfile(curMain);
                      const workerP = findProfile(curWorker);
                      const mainModel = modelForHarness(mainP, h.agent_type);
                      const workerModel = modelForHarness(workerP, h.agent_type);

                      return (
                        <tr key={h.agent_type} data-testid={`harness-row-${h.agent_type}`}>
                          <td>
                            <div className="h-nm">
                              <span>{h.display_name}</span>
                              <span className="proto-tag">
                                {t(`settings.general.harnesses.protocolLabel.${h.agent_type}`, {
                                  defaultValue: h.protocol_label,
                                })}
                              </span>
                              {!h.installed && (
                                <span className="s-kind">
                                  {t('settings.general.harnesses.notInstalled')}
                                </span>
                              )}
                            </div>
                            <div className="h-meta">
                              {isBuiltin ? (
                                <span>{t('settings.general.harnesses.coreagentMeta')}</span>
                              ) : (
                                h.config_path
                              )}
                            </div>
                          </td>
                          <td>
                            <select
                              className="sselect"
                              aria-label={t('settings.general.harnesses.dailySelectAria', {
                                name: h.display_name,
                              })}
                              value={curMain}
                              disabled={busyKey !== null}
                              onChange={(e) =>
                                handleBindHarness(h.agent_type, 'main', e.target.value)
                              }
                            >
                              <option value="official">
                                {isBuiltin
                                  ? t('settings.general.harnesses.optAutoFallback')
                                  : t('settings.general.harnesses.optNativeLogin')}
                              </option>
                              {profiles.map((p) => {
                                if (p.kind === 'workbuddy') {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optDisabledWorkbuddy', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                if (p.kind === 'vendor_cli') {
                                  if (isBuiltin) {
                                    return (
                                      <option key={p.id} value={p.id} disabled>
                                        {t('settings.general.harnesses.optDisabledVendorNoKey', {
                                          name: p.name,
                                        })}
                                      </option>
                                    );
                                  }
                                  if (
                                    h.agent_type === 'agy' &&
                                    (!p.agent_type || p.agent_type === 'agy')
                                  ) {
                                    return (
                                      <option key={p.id} value={p.id}>
                                        {p.name}
                                        {p.default_model ? ` · ${p.default_model}` : ''}
                                      </option>
                                    );
                                  }
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optDisabledWorkerOnly', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                if (
                                  h.agent_type === 'codex' &&
                                  !hasProtocolChannel(p, 'responses')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optMissingResponses', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                if (
                                  (h.agent_type === 'coreagent' ||
                                    h.agent_type === 'claude' ||
                                    h.agent_type === 'opencode') &&
                                  !hasProtocolChannel(p, 'anthropic')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optMissingAnthropic', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                const m = modelForHarness(p, h.agent_type);
                                return (
                                  <option key={p.id} value={p.id}>
                                    {p.name}
                                    {m ? ` · ${m}` : ''}
                                  </option>
                                );
                              })}
                            </select>
                            <div className="cell-sub">
                              {curMain !== 'official' && mainP ? (
                                <>
                                  <span style={{ color: 'var(--accent-primary)' }}>●</span>{' '}
                                  {t('settings.general.harnesses.subWrittenTo')}{' '}
                                  <code>{h.config_path}</code>
                                  {mainModel ? ` · ${mainModel}` : ` · ${mainP.name}`}
                                </>
                              ) : isBuiltin ? (
                                t('settings.general.harnesses.subCoreAutoFallback')
                              ) : (
                                t('settings.general.harnesses.subKeepNative')
                              )}
                            </div>
                          </td>
                          <td>
                            <select
                              className="sselect"
                              aria-label={t('settings.general.harnesses.workerSelectAria', {
                                name: h.display_name,
                              })}
                              value={curWorker}
                              disabled={busyKey !== null}
                              onChange={(e) =>
                                handleBindHarness(h.agent_type, 'worker', e.target.value)
                              }
                            >
                              <option value="follow">
                                {t('settings.general.harnesses.optFollowDaily')}
                              </option>
                              {!isBuiltin && (
                                <option value="official">
                                  {t('settings.general.harnesses.optForceNative')}
                                </option>
                              )}
                              {profiles.map((p) => {
                                if (p.kind === 'workbuddy') {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optDisabledWorkbuddy', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                if (p.kind === 'vendor_cli') {
                                  if (isBuiltin) {
                                    return (
                                      <option key={p.id} value={p.id} disabled>
                                        {t('settings.general.harnesses.optDisabledVendorNoKey', {
                                          name: p.name,
                                        })}
                                      </option>
                                    );
                                  }
                                  return (
                                    <option key={p.id} value={p.id}>
                                      {p.name}
                                      {p.default_model
                                        ? ` · ${p.default_model}`
                                        : ` · ${t('settings.general.harnesses.optVendorLoginSuffix')}`}
                                    </option>
                                  );
                                }
                                if (
                                  h.agent_type === 'codex' &&
                                  !hasProtocolChannel(p, 'responses')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optMissingResponses', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                if (
                                  (h.agent_type === 'coreagent' ||
                                    h.agent_type === 'claude' ||
                                    h.agent_type === 'opencode') &&
                                  !hasProtocolChannel(p, 'anthropic')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {t('settings.general.harnesses.optMissingAnthropic', {
                                        name: p.name,
                                      })}
                                    </option>
                                  );
                                }
                                const m = modelForHarness(p, h.agent_type);
                                return (
                                  <option key={p.id} value={p.id}>
                                    {p.name}
                                    {m ? ` · ${m}` : ''}
                                  </option>
                                );
                              })}
                            </select>
                            <div className="cell-sub">
                              {curWorker === 'follow'
                                ? t('settings.general.harnesses.subFollowsDaily', {
                                    target: mainP
                                      ? `${mainP.name}${mainModel ? ` (${mainModel})` : ''}`
                                      : isBuiltin
                                        ? t('settings.general.harnesses.subTargetAutoFallback')
                                        : t('settings.general.harnesses.subTargetNative'),
                                  })
                                : curWorker === 'official'
                                  ? t('settings.general.harnesses.subWorkerNative')
                                  : t('settings.general.harnesses.subWorkerInjected', {
                                      target: workerModel || workerP?.name || curWorker,
                                    })}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* 单行多工具 Danger Zone */}
          <div className="dzone-bar" data-testid="zone-danger">
            <div className="dzone-bar-l">
              <b>
                <AlertTriangle size={13} />
                {t('settings.general.danger.title')}
              </b>
              <span>{t('settings.general.danger.desc')}</span>
            </div>
            <div className="dzone-bar-r">
              <select
                className="sselect"
                style={{ width: 248, height: 28, fontSize: 12 }}
                aria-label={t('settings.general.danger.selectAria')}
                value={selectedDangerAgent}
                onChange={(e) => setSelectedDangerAgent(e.target.value)}
              >
                {harnesses
                  .filter((h) => h.agent_type !== 'coreagent')
                  .map((h) => (
                    <option key={h.agent_type} value={h.agent_type}>
                      {h.display_name} · {h.config_path}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                className="btn btn-sm danger-out"
                style={{ height: 28, fontSize: 12 }}
                onClick={handleOpenInVSCode}
                data-testid="open-in-vscode-btn"
              >
                <Code size={13} />
                {t('settings.general.danger.openBtn')}
              </button>
            </div>
          </div>
        </>
      )}

      {/* 子视图 2：旁路与轻量 AI */}
      {subTab === 'sidecar' && (
        <div className="s-card sc-compact" data-testid="zone-sidecar-ai">
          <div className="ssec">
            <div className="ssec-h">
              <div>
                <h3>{t('settings.general.sidecar.title')}</h3>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  {t('settings.general.sidecar.subtitle')}
                </div>
              </div>
            </div>

            {/* 第 1 行：轻量 AI · LightAgent */}
            <div className="srow" data-testid="sidecar-lightagent">
              <div className="l">
                <div className="t">
                  <Sparkles size={14} />
                  <span>
                    {t('settings.general.sidecar.lightagent.name')} · <code>LightAgent</code>
                  </span>
                  <span className="s-kind">
                    {t('settings.general.sidecar.tierLight', { model: lightModelLabel })}
                  </span>
                </div>
                <div className="d">
                  <b>{t('settings.general.sidecar.roleLabel')}</b>
                  {t('settings.general.sidecar.lightagent.role')}
                  <br />
                  <b>{t('settings.general.sidecar.whyLabel')}</b>
                  {t('settings.general.sidecar.lightagent.why')}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <select
                  className="sselect"
                  style={{ width: 210, height: 28, fontSize: 12 }}
                  aria-label={t('settings.general.sidecar.lightagent.selectAria')}
                  value={lightBinding?.profile_id ?? ''}
                  disabled={busyKey !== null}
                  onChange={(e) => handleBindSidecar('lightagent', e.target.value)}
                >
                  <option value="">
                    {t('settings.general.sidecar.lightagent.optAutoFallback')}
                  </option>
                  {renderSidecarOptions()}
                </select>
                <button
                  type="button"
                  className={`tog ${hookReviewEnabled ? '' : 'off'}`}
                  role="switch"
                  aria-checked={hookReviewEnabled}
                  disabled={busyKey !== null}
                  title={t('settings.general.sidecar.lightagent.toggleTitle')}
                  onClick={handleToggleHookReview}
                  data-testid="lightagent-hook-toggle"
                />
                <span style={{ fontSize: 11.5, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {hookReviewEnabled
                    ? t('settings.general.sidecar.lightagent.reviewOn')
                    : t('settings.general.sidecar.lightagent.reviewOff')}
                </span>
              </div>
            </div>

            {/* 第 2 行：旁路 AI · Session Observer */}
            <div className="srow" data-testid="sidecar-observer">
              <div className="l">
                <div className="t">
                  <Eye size={14} />
                  <span>
                    {t('settings.general.sidecar.observer.name')} · <code>Session Observer</code>
                  </span>
                  {obsConnection ? (
                    <span className="s-kind">
                      {t('settings.general.sidecar.tierLight', { model: obsModelLabel })}
                    </span>
                  ) : (
                    <span className="s-pill off" style={{ marginLeft: 0 }}>
                      {t('settings.general.sidecar.observer.offBadge')}
                    </span>
                  )}
                </div>
                <div className="d">
                  <b>{t('settings.general.sidecar.roleLabel')}</b>
                  {t('settings.general.sidecar.observer.role')}
                  <br />
                  <b>{t('settings.general.sidecar.whyLabel')}</b>
                  {t('settings.general.sidecar.observer.why')}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <select
                  className="sselect"
                  style={{ width: 222, height: 28, fontSize: 12 }}
                  aria-label={t('settings.general.sidecar.observer.selectAria')}
                  value={obsBinding?.profile_id ?? ''}
                  disabled={busyKey !== null}
                  onChange={(e) => handleBindSidecar('observer', e.target.value)}
                >
                  <option value="">{t('settings.general.sidecar.observer.optOff')}</option>
                  {renderSidecarOptions()}
                </select>
              </div>
            </div>

            {/* 第 3 行：桌面语音识别 · asr */}
            <div className="srow" data-testid="sidecar-asr">
              <div className="l">
                <div className="t">
                  <Mic size={14} />
                  <span>
                    {t('settings.general.sidecar.asr.name')} · <code>asr</code>
                  </span>
                  {asrConnection ? (
                    <span className="s-kind">
                      {t('settings.general.sidecar.asr.activeBadge', {
                        name: asrConnection.name,
                        model: asrModelLabel,
                      })}
                    </span>
                  ) : (
                    <span className="s-pill off" style={{ marginLeft: 0 }}>
                      {t('settings.general.sidecar.unconfigured')}
                    </span>
                  )}
                </div>
                <div className="d">
                  <b>{t('settings.general.sidecar.roleLabel')}</b>
                  {t('settings.general.sidecar.asr.role')}
                  <br />
                  <b>{t('settings.general.sidecar.whyLabel')}</b>
                  {t('settings.general.sidecar.asr.why')}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <select
                  className="sselect"
                  style={{ width: 222, height: 28, fontSize: 12 }}
                  aria-label={t('settings.general.sidecar.asr.selectAria')}
                  value={asrBinding?.profile_id ?? ''}
                  disabled={busyKey !== null}
                  onChange={(e) => handleBindSidecar('asr', e.target.value)}
                  data-testid="sidecar-asr-select"
                >
                  <option value="">{t('settings.general.sidecar.asr.optAutoMatch')}</option>
                  {renderSidecarOptions(true)}
                </select>
              </div>
            </div>

            {/* 第 4 行：决策模型 · Decision Model */}
            <div
              className="srow"
              data-testid="sidecar-decision"
              style={{ flexDirection: 'column', alignItems: 'stretch', gap: 8 }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'space-between',
                  gap: 14,
                }}
              >
                <div className="l">
                  <div className="t">
                    <Gauge size={14} />
                    <span>
                      {t('settings.general.sidecar.decision.name')} · <code>Decision Model</code>
                    </span>
                    {decisionSettings?.configured && decisionSettings.enabled ? (
                      <span className="s-kind">
                        {t('settings.general.sidecar.decision.activeBadge', {
                          wire: decisionSettings.wire,
                          model: decisionSettings.model,
                        })}
                      </span>
                    ) : (
                      <span className="s-pill off" style={{ marginLeft: 0 }}>
                        {decisionSettings?.configured
                          ? t('settings.general.sidecar.decision.disabledBadge')
                          : t('settings.general.sidecar.unconfigured')}
                      </span>
                    )}
                  </div>
                  <div className="d">
                    <b>{t('settings.general.sidecar.roleAndWhyLabel')}</b>
                    {t('settings.general.sidecar.decision.roleAndWhy')}
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ height: 26, fontSize: 12, flexShrink: 0 }}
                  onClick={() => setDecisionOpen(!decisionOpen)}
                  data-testid="decision-model-toggle-btn"
                >
                  {decisionOpen
                    ? t('settings.general.sidecar.decision.hideBtn')
                    : t('settings.general.sidecar.decision.configBtn')}
                </button>
              </div>

              {decisionOpen && (
                <div className="fbox" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="fgrid2">
                    <div className="fgrp">
                      <label htmlFor="decision-wire-select">
                        {t('settings.general.sidecar.decision.wireLabel')}
                      </label>
                      <select
                        id="decision-wire-select"
                        className="sselect"
                        style={{ maxWidth: '100%' }}
                        value={decisionWire}
                        onChange={(e) => setDecisionWire(e.target.value as DecisionWireMode)}
                        data-testid="decision-model-wire-select"
                      >
                        <option value="decisions">
                          {t('settings.general.sidecar.decision.wireDecisions')}
                        </option>
                        <option value="ollama">
                          {t('settings.general.sidecar.decision.wireOllama')}
                        </option>
                      </select>
                    </div>
                    <div className="fgrp">
                      <label htmlFor="decision-model-input">
                        {t('settings.general.sidecar.decision.modelLabel')}
                      </label>
                      <input
                        id="decision-model-input"
                        type="text"
                        className="sinput mono"
                        value={decisionModel}
                        onChange={(e) => setDecisionModel(e.target.value)}
                        placeholder={t(`settings.decisionModel.modelPlaceholder.${decisionWire}`)}
                        data-testid="decision-model-model-input"
                      />
                    </div>
                  </div>
                  <div className="fgrid2">
                    <div className="fgrp">
                      <label htmlFor="decision-url-input">
                        {t('settings.general.sidecar.decision.urlLabel')}
                      </label>
                      <input
                        id="decision-url-input"
                        type="text"
                        className="sinput mono"
                        value={decisionUrl}
                        onChange={(e) => setDecisionUrl(e.target.value)}
                        placeholder={t(`settings.decisionModel.urlPlaceholder.${decisionWire}`)}
                        data-testid="decision-model-url-input"
                      />
                    </div>
                    <div className="fgrp">
                      <label htmlFor="decision-apikey-input">
                        {t('settings.general.sidecar.decision.apiKeyLabel')}
                      </label>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <input
                          id="decision-apikey-input"
                          type={decisionShowKey ? 'text' : 'password'}
                          className="sinput mono"
                          style={{ flex: 1 }}
                          value={decisionApiKey}
                          disabled={decisionClearKey}
                          onChange={(e) => setDecisionApiKey(e.target.value)}
                          placeholder={
                            decisionSettings?.has_api_key && !decisionClearKey
                              ? decisionSettings.api_key_masked
                              : t('settings.decisionModel.apiKeyPlaceholder')
                          }
                          data-testid="decision-model-apikey-input"
                        />
                        <button
                          type="button"
                          className="btn btn-sm btn-ghost"
                          onClick={() => setDecisionShowKey(!decisionShowKey)}
                          title={
                            decisionShowKey
                              ? t('settings.general.hideApiKey')
                              : t('settings.general.showApiKey')
                          }
                        >
                          {decisionShowKey ? <EyeOff size={13} /> : <Eye size={13} />}
                        </button>
                      </div>
                    </div>
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 10,
                      paddingTop: 4,
                    }}
                  >
                    <label
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 8,
                        fontSize: 12,
                        color: 'var(--text-secondary)',
                        cursor: 'pointer',
                      }}
                    >
                      <button
                        type="button"
                        role="switch"
                        aria-checked={decisionEnabled}
                        className={`tog ${decisionEnabled ? '' : 'off'}`}
                        style={{ marginLeft: 0 }}
                        onClick={() => setDecisionEnabled(!decisionEnabled)}
                      />
                      <span>{t('settings.general.sidecar.decision.enableSwitch')}</span>
                    </label>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {decisionSettings?.configured && (
                        <button
                          type="button"
                          className="btn btn-sm danger-out"
                          disabled={decisionSaving}
                          onClick={handleResetDecisionModel}
                          data-testid="decision-model-reset-btn"
                        >
                          <Trash2 size={12} />
                          {t('settings.general.sidecar.decision.resetBtn')}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        disabled={decisionSaving}
                        onClick={() => setDecisionOpen(false)}
                      >
                        <X size={12} />
                        {t('settings.general.sidecar.decision.cancelBtn')}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        disabled={decisionSaving}
                        onClick={handleSaveDecisionModel}
                        data-testid="decision-model-save-btn"
                      >
                        <Check size={12} />
                        {decisionSaving
                          ? t('settings.general.sidecar.decision.savingBtn')
                          : t('settings.general.sidecar.decision.saveBtn')}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 子视图 3：AI 服务商 */}
      {subTab === 'profiles' && (
        <div className="s-card" data-testid="zone-profiles">
          <div className="ssec">
            <div className="ssec-h">
              <div>
                <h3>
                  {t('settings.general.providers.title', { count: profiles.length })}
                </h3>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  {t('settings.general.providers.subtitle')}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ height: 26, fontSize: 12 }}
                  onClick={() => openProfileModal('add-vendor')}
                  data-testid="add-vendor-cli-btn"
                >
                  <Terminal size={13} />
                  {t('settings.general.providers.addVendorBtn')}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  style={{ height: 26, fontSize: 12 }}
                  onClick={() => openProfileModal('add-endpoint')}
                  data-testid="add-endpoint-provider-btn"
                >
                  <Plus size={13} />
                  {t('settings.general.providers.addProviderBtn')}
                </button>
              </div>
            </div>

            <div className="stbl-wrap">
              <table className="stbl">
                <thead>
                  <tr>
                    <th style={{ width: '22%' }}>
                      {t('settings.general.providers.colProvider')}
                    </th>
                    <th style={{ width: '21%' }}>
                      {t('settings.general.providers.colProtocols')}
                    </th>
                    <th style={{ width: '24%' }}>
                      {t('settings.general.providers.colModels')}
                    </th>
                    <th style={{ width: '23%' }}>
                      {t('settings.general.providers.colUsedBy')}
                    </th>
                    <th style={{ width: '10%' }}>
                      {t('settings.general.providers.colActions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        style={{ textAlign: 'center', padding: '20px 10px', color: 'var(--text-muted)' }}
                      >
                        {t('settings.general.providers.empty')}
                      </td>
                    </tr>
                  ) : (
                    profiles.map((p) => {
                      const isRet = p.kind === 'workbuddy';
                      const isVendor = p.kind === 'vendor_cli';
                      const refs = refsByProfile[p.id] || [];
                      const protoTags = getProfileProtocolTags(p);
                      const ctxParts: string[] = [];
                      if (p.haiku_model) {
                        ctxParts.push(
                          t('settings.general.providers.lightPrefix', { model: p.haiku_model }),
                        );
                      }
                      if (p.context_window) {
                        ctxParts.push(`${Math.round(p.context_window / 1000)}k ctx`);
                      }
                      if (p.agy_context_window) {
                        ctxParts.push(`agy ${p.agy_context_window}`);
                      }

                      return (
                        <tr key={p.id} data-testid={`profile-row-${p.id}`}>
                          <td className="nm">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
                              <span>{p.name}</span>
                              {isRet ? (
                                <span className="s-pill warn" style={{ height: 17, padding: '0 5px', fontSize: 10, marginLeft: 0 }}>
                                  {t('settings.general.providers.badgeRetired')}
                                </span>
                              ) : isVendor ? (
                                <span className="s-kind">
                                  {t('settings.general.providers.badgeVendor')}
                                </span>
                              ) : (
                                <span className="s-kind">
                                  {t('settings.general.providers.badgeApiKey')}
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                              {isRet
                                ? t('settings.general.providers.metaRetired')
                                : isVendor
                                  ? t('settings.general.providers.metaVendor', {
                                      core: p.agent_type || 'agy',
                                    })
                                  : `${p.endpoint_type}${p.api_key_masked ? ` · ${p.api_key_masked}` : ''}`}
                            </div>
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                              {isRet ? (
                                <span style={{ fontSize: 11, color: 'var(--accent-warning)' }}>
                                  {t('settings.general.providers.protoEncrypted')}
                                </span>
                              ) : (
                                protoTags.map((pt) => (
                                  <span
                                    key={pt.label}
                                    className="proto-tag"
                                    title={pt.url || undefined}
                                  >
                                    {pt.label}
                                  </span>
                                ))
                              )}
                            </div>
                          </td>
                          <td className="mono" style={{ fontSize: 11.5 }}>
                            {isRet ? (
                              <span style={{ color: 'var(--text-muted)' }}>—</span>
                            ) : (
                              <>
                                <div>
                                  {p.default_model || t('settings.general.providers.modelDefault')}
                                </div>
                                {ctxParts.length > 0 && (
                                  <div style={{ fontSize: 10.5, color: 'var(--text-muted)', marginTop: 2 }}>
                                    {ctxParts.join(' · ')}
                                  </div>
                                )}
                              </>
                            )}
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                              {refs.length > 0 ? (
                                refs.map((r) => (
                                  <span key={r} className="ref-chip">
                                    {r}
                                  </span>
                                ))
                              ) : (
                                <span className="ref-chip idle">
                                  {t('settings.general.providers.refUnused')}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="acts">
                            <button
                              type="button"
                              className="btn-icon-sm"
                              title={t('settings.general.providers.editTitle')}
                              onClick={() => openProfileModal('edit', p)}
                              data-testid={`edit-profile-${p.id}`}
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              type="button"
                              className="btn-icon-sm"
                              title={t('settings.general.providers.deleteTitle')}
                              onClick={() => setDeletingProfile(p)}
                              data-testid={`delete-profile-${p.id}`}
                            >
                              <Trash2 size={13} />
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 删除 AI 服务商确认弹窗 */}
      <Modal
        isOpen={deletingProfile !== null}
        onClose={() => setDeletingProfile(null)}
        title={t('settings.profiles.confirmDelete')}
        footer={
          <>
            <button
              type="button"
              onClick={() => setDeletingProfile(null)}
              className="btn btn-ghost"
            >
              {t('settings.general.cancel')}
            </button>
            <button
              type="button"
              onClick={confirmDeleteProfile}
              className="btn btn-primary"
              data-testid="confirm-delete-profile-btn"
            >
              {t('settings.profiles.delete')}
            </button>
          </>
        }
      >
        <p className="text-sm text-[var(--text-secondary)]">
          {t('settings.profiles.confirmDeleteDesc')}
        </p>
      </Modal>

      {/* 新建/编辑 AI 服务商弹窗 */}
      <ProfileManager
        isOpen={showProfileManager}
        onClose={() => {
          setShowProfileManager(false);
          setEditingProfile(null);
          setModalMode('list');
        }}
        onProfilesChanged={() => loadData()}
        hasCustomConfig={config.auth_method === 'custom'}
        initialMode={modalMode}
        initialEditProfile={editingProfile}
      />
    </div>
  );
}
