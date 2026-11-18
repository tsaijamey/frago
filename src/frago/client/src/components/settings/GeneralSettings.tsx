/**
 * General Settings Component (Settings ▸ General)
 *
 * Implements the 3-segment tabbed layout (harnesses / sidecar / profiles):
 * 1. Harness 工具 — Built-in CoreAgent + 4 external CLI coding tools with independent Daily Session & Worker bindings + single-line Danger Zone
 * 2. 旁路与轻量 AI — LightAgent, Session Observer, Desktop Speech Recognition (ASR), and inline Decision Model configuration
 * 3. AI 服务商 — 5-column provider & protocol routing table with live reverse-reference chips
 */

import { useEffect, useMemo, useState } from 'react';
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
  ArrowDownAZ,
  ArrowUpZA,
  Check,
  ChevronDown,
  ChevronUp,
  Code,
  Eye,
  EyeOff,
  Gauge,
  Info,
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
import {
  formatProviderMetaEndpoint,
  readProfileSortOrder,
  sortProfilesByName,
  writeProfileSortOrder,
  type ProfileSortOrder,
} from '@/components/settings/profileSort';
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

const SIDECAR_ROLE_IDS = ['lightagent', 'observer', 'asr', 'decision'] as const;
type SidecarRoleKey = (typeof SIDECAR_ROLE_IDS)[number];

interface ProfileRefItem {
  key: string;
  label: string;
  isAuto?: boolean;
}

function shortConfigFilename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

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
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');
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

  // Sidecar inline Why tooltip/card toggle
  const [openWhyKey, setOpenWhyKey] = useState<SidecarRoleKey | null>(null);

  // AI Providers expanded Used By rows
  const [expandedRefIds, setExpandedRefIds] = useState<Record<string, boolean>>({});

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
  const [profileSortOrder, setProfileSortOrder] = useState<ProfileSortOrder>(() =>
    readProfileSortOrder(),
  );

  const handleChangeProfileSortOrder = (nextOrder: ProfileSortOrder) => {
    setProfileSortOrder(nextOrder);
    writeProfileSortOrder(nextOrder);
  };

  const sortedProfiles = useMemo(
    () => sortProfilesByName(profiles, profileSortOrder),
    [profiles, profileSortOrder],
  );

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
      for (const h of harnesses) {
        if (h.main_profile_id !== 'official') {
          const res = await bindHarness(h.agent_type, 'main', 'official');
          if (res.status !== 'ok') {
            setError(res.error || t('errors.deactivateFailed'));
            break;
          }
        }
        if (h.worker_profile_id && h.worker_profile_id !== 'follow') {
          const res = await bindHarness(h.agent_type, 'worker', 'follow');
          if (res.status !== 'ok') {
            setError(res.error || t('errors.deactivateFailed'));
            break;
          }
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

  const handleToggleDecisionEnabled = async () => {
    if (!decisionSettings || !decisionSettings.configured) return;
    try {
      setDecisionSaving(true);
      setError(null);
      const updated = await updateDecisionModelSettings({
        enabled: !decisionSettings.enabled,
        wire: decisionSettings.wire,
        url: decisionSettings.url,
        model: decisionSettings.model,
        temperature: decisionSettings.temperature,
      });
      setDecisionSettings(updated);
      populateDecisionForm(updated);
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
  const computeProfileRefs = (): Record<string, ProfileRefItem[]> => {
    const map: Record<string, ProfileRefItem[]> = {};
    for (const p of profiles) {
      map[p.id] = [];
    }
    for (const h of harnesses) {
      if (h.main_profile_id && h.main_profile_id !== 'official' && map[h.main_profile_id]) {
        map[h.main_profile_id].push({
          key: `main:${h.agent_type}`,
          label: t('settings.general.providers.refDaily', { name: h.display_name }),
        });
      }
      if (
        h.worker_profile_id &&
        h.worker_profile_id !== 'follow' &&
        h.worker_profile_id !== 'official' &&
        map[h.worker_profile_id]
      ) {
        map[h.worker_profile_id].push({
          key: `worker:${h.agent_type}`,
          label: t('settings.general.providers.refWorker', { name: h.display_name }),
        });
      }
    }
    const lightBinding = bindings.find((b) => b.role === 'lightagent');
    const obsBinding = bindings.find((b) => b.role === 'observer');
    const asrBinding = bindings.find((b) => b.role === 'asr');

    const lightPid = lightBinding?.profile_id || lightBinding?.connection?.id;
    if (lightPid && map[lightPid]) {
      const baseLabel = t('settings.general.providers.refLight');
      map[lightPid].push({
        key: 'role:lightagent',
        label: lightBinding?.profile_id
          ? baseLabel
          : t('settings.general.providers.refAutoSuffix', { name: baseLabel }),
        isAuto: !lightBinding?.profile_id,
      });
    }
    const obsPid = obsBinding?.profile_id;
    if (obsPid && map[obsPid]) {
      map[obsPid].push({
        key: 'role:observer',
        label: t('settings.general.providers.refObserver'),
      });
    }
    const asrPid = asrBinding?.profile_id || asrBinding?.connection?.id;
    if (asrPid && map[asrPid]) {
      const baseLabel = t('settings.general.providers.refAsr');
      map[asrPid].push({
        key: 'role:asr',
        label: asrBinding?.profile_id
          ? baseLabel
          : t('settings.general.providers.refAutoSuffix', { name: baseLabel }),
        isAuto: !asrBinding?.profile_id,
      });
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
  const hasAnyNonOfficialHarness = harnesses.some(
    (h) =>
      h.main_profile_id !== 'official' ||
      (Boolean(h.worker_profile_id) && h.worker_profile_id !== 'follow'),
  );

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
    sortedProfiles.map((p) => {
      if (p.kind === 'workbuddy') {
        return (
          <option
            key={p.id}
            value={p.id}
            disabled
            title={t('settings.general.harnesses.optDisabledWorkbuddy', { name: p.name })}
          >
            {t('settings.general.harnesses.optDisabledWorkbuddy', { name: p.name })}
          </option>
        );
      }
      if (p.kind === 'vendor_cli') {
        return (
          <option
            key={p.id}
            value={p.id}
            disabled
            title={t('settings.general.harnesses.optDisabledVendorNoKey', { name: p.name })}
          >
            {t('settings.general.harnesses.optDisabledVendorNoKey', { name: p.name })}
          </option>
        );
      }
      const modelHint = useDefaultModel
        ? p.default_model || p.haiku_model
        : p.haiku_model || p.default_model;
      return (
        <option
          key={p.id}
          value={p.id}
          title={modelHint ? `${p.name} (${modelHint})` : p.name}
        >
          {p.name}
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

      {/* 顶部三段子视图切换器：走全站统一的 C6 分段胶囊，计数内嵌在胶囊里。 */}
      <div className="g-topbar">
        <div
          className="ui-seg-group"
          role="tablist"
          aria-label={t('settings.general.tabs.ariaLabel')}
        >
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'harnesses'}
            className={`ui-seg-pill ${subTab === 'harnesses' ? 'ui-seg-pill--active' : ''}`}
            onClick={() => setSubTab('harnesses')}
            data-testid="general-tab-harnesses"
          >
            <Terminal size={13} />
            <span>{t('settings.general.tabs.harnesses')}</span>
            <span className="ui-seg-count">{harnesses.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'sidecar'}
            className={`ui-seg-pill ${subTab === 'sidecar' ? 'ui-seg-pill--active' : ''}`}
            onClick={() => setSubTab('sidecar')}
            data-testid="general-tab-sidecar"
          >
            <Sparkles size={13} />
            <span>{t('settings.general.tabs.sidecar')}</span>
            <span className="ui-seg-count">{SIDECAR_ROLE_IDS.length}</span>
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'profiles'}
            className={`ui-seg-pill ${subTab === 'profiles' ? 'ui-seg-pill--active' : ''}`}
            onClick={() => setSubTab('profiles')}
            data-testid="general-tab-profiles"
          >
            <KeyRound size={13} />
            <span>{t('settings.general.tabs.profiles')}</span>
            <span className="ui-seg-count">{profiles.length}</span>
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
                  <div className="ssec-sub">{t('settings.general.harnesses.subtitle')}</div>
                </div>
                {/* 「全部切回原生登录」是丢弃所有自定义服务商路由的批量动作，所以走统一的
                    危险胶囊（红色描边、单行不换行）。从前它是一枚普通描边小按钮，文案在
                    窄列里被折成两行，读起来像一句说明而不是一个按钮。 */}
                {hasAnyNonOfficialHarness && (
                  <button
                    type="button"
                    className="ui-danger-pill"
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
                      <th style={{ width: '22%' }}>
                        {t('settings.general.harnesses.colTool')}
                        <span className="sub">{t('settings.general.harnesses.colToolSub')}</span>
                      </th>
                      <th style={{ width: '39%' }}>
                        {t('settings.general.harnesses.colDaily')}
                        <span className="sub">{t('settings.general.harnesses.colDailySub')}</span>
                      </th>
                      <th style={{ width: '39%' }}>
                        {t('settings.general.harnesses.colWorker')}
                        <span className="sub">{t('settings.general.harnesses.colWorkerSub')}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {harnesses.map((h) => {
                      const isBuiltin = h.agent_type === 'coreagent';
                      const isAgy = h.agent_type === 'agy';
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
                              <span title={h.display_name}>{h.display_name}</span>
                              <span className="s-kind shrink-0">
                                {t(`settings.general.harnesses.protocolShort.${h.agent_type}`, {
                                  defaultValue: h.protocol_label,
                                })}
                              </span>
                              {!h.installed && (
                                <span className="s-pill off" style={{ marginLeft: 0 }}>
                                  {t('settings.general.harnesses.notInstalled')}
                                </span>
                              )}
                            </div>
                            <div
                              className="h-meta"
                              title={
                                isBuiltin
                                  ? t('settings.general.harnesses.coreagentMeta')
                                  : h.config_path
                              }
                            >
                              {h.config_path}
                            </div>
                          </td>
                          <td>
                            <select
                              className="sselect"
                              aria-label={t('settings.general.harnesses.dailySelectAria', {
                                name: h.display_name,
                              })}
                              title={
                                curMain === 'official'
                                  ? isBuiltin
                                    ? t('settings.general.harnesses.optAutoFallback')
                                    : t('settings.general.harnesses.optNativeLogin')
                                  : mainP
                                    ? `${mainP.name}${mainModel ? ` · ${mainModel}` : ''}`
                                    : curMain
                              }
                              value={curMain}
                              disabled={busyKey !== null}
                              onChange={(e) =>
                                handleBindHarness(h.agent_type, 'main', e.target.value)
                              }
                            >
                              <option
                                value="official"
                                title={
                                  isBuiltin
                                    ? t('settings.general.harnesses.optAutoFallback')
                                    : t('settings.general.harnesses.optNativeLogin')
                                }
                              >
                                {isBuiltin
                                  ? t('settings.general.harnesses.optAutoFallbackShort')
                                  : t('settings.general.harnesses.optNativeLoginShort')}
                              </option>
                              {sortedProfiles.map((p) => {
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
                                      <option
                                        key={p.id}
                                        value={p.id}
                                        title={p.default_model ? `${p.name} · ${p.default_model}` : p.name}
                                      >
                                        {p.name}
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
                                  <option
                                    key={p.id}
                                    value={p.id}
                                    title={m ? `${p.name} · ${m}` : p.name}
                                  >
                                    {p.name}
                                  </option>
                                );
                              })}
                            </select>
                            <div className="cell-sub">
                              <span
                                className="cell-sub-main"
                                title={
                                  curMain !== 'official' && mainP
                                    ? `${t('settings.general.harnesses.subWrittenTo')} ${h.config_path} · ${mainModel || mainP.name}`
                                    : isBuiltin
                                      ? t('settings.general.harnesses.subCoreAutoFallback')
                                      : t('settings.general.harnesses.subKeepNative')
                                }
                              >
                                <span
                                  className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                                  style={{
                                    background:
                                      curMain !== 'official' && mainP
                                        ? 'var(--accent-primary)'
                                        : 'var(--text-dim)',
                                  }}
                                />
                                <span className="truncate font-mono">
                                  {curMain !== 'official' && mainP
                                    ? mainModel || mainP.name
                                    : isBuiltin
                                      ? t('settings.general.harnesses.subTargetAutoFallback')
                                      : t('settings.general.harnesses.subTargetNative')}
                                </span>
                              </span>
                              <span
                                className="cell-sub-meta"
                                data-testid={`harness-window-${h.agent_type}`}
                                title={
                                  h.context_window
                                    ? t('settings.general.harnesses.contextWindowOnConnection', {
                                        window: h.context_window.toLocaleString(),
                                      })
                                    : isAgy
                                      ? t('settings.general.harnesses.agyWindowHint')
                                      : t('settings.general.harnesses.contextWindowUnknown')
                                }
                              >
                                {h.context_window
                                  ? `${Math.round(h.context_window / 1000)}k ctx`
                                  : isAgy
                                    ? mainP?.agy_context_window
                                      ? `agy ${mainP.agy_context_window}`
                                      : t('settings.general.harnesses.agyWindowManaged')
                                    : t('settings.general.harnesses.contextWindowShortUnknown')}
                                <Info size={11} className="shrink-0 opacity-70" />
                              </span>
                            </div>
                          </td>
                          <td>
                            <select
                              className="sselect"
                              aria-label={t('settings.general.harnesses.workerSelectAria', {
                                name: h.display_name,
                              })}
                              title={
                                curWorker === 'follow'
                                  ? t('settings.general.harnesses.optFollowDaily')
                                  : curWorker === 'official'
                                    ? t('settings.general.harnesses.optForceNative')
                                    : workerP
                                      ? `${workerP.name}${workerModel ? ` · ${workerModel}` : ''}`
                                      : curWorker
                              }
                              value={curWorker}
                              disabled={busyKey !== null}
                              onChange={(e) =>
                                handleBindHarness(h.agent_type, 'worker', e.target.value)
                              }
                            >
                              <option
                                value="follow"
                                title={t('settings.general.harnesses.optFollowDaily')}
                              >
                                {t('settings.general.harnesses.optFollowDailyShort')}
                              </option>
                              {!isBuiltin && (
                                <option
                                  value="official"
                                  title={t('settings.general.harnesses.optForceNative')}
                                >
                                  {t('settings.general.harnesses.optForceNativeShort')}
                                </option>
                              )}
                              {sortedProfiles.map((p) => {
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
                                    <option
                                      key={p.id}
                                      value={p.id}
                                      title={`${p.name} · ${p.default_model || t('settings.general.harnesses.optVendorLoginSuffix')}`}
                                    >
                                      {p.name}
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
                                  <option
                                    key={p.id}
                                    value={p.id}
                                    title={m ? `${p.name} · ${m}` : p.name}
                                  >
                                    {p.name}
                                  </option>
                                );
                              })}
                            </select>
                            <div className="cell-sub">
                              <span
                                className="cell-sub-main"
                                title={
                                  curWorker === 'follow'
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
                                        })
                                }
                              >
                                <span
                                  className="inline-block h-1.5 w-1.5 shrink-0 rounded-full"
                                  style={{
                                    background:
                                      curWorker !== 'follow' && curWorker !== 'official' && workerP
                                        ? 'var(--accent-primary)'
                                        : 'var(--text-dim)',
                                  }}
                                />
                                <span className="truncate font-mono">
                                  {curWorker === 'follow'
                                    ? t('settings.general.harnesses.subFollowsShort', {
                                        target:
                                          mainModel ||
                                          mainP?.name ||
                                          (isBuiltin
                                            ? t('settings.general.harnesses.subTargetAutoFallback')
                                            : t('settings.general.harnesses.subTargetNative')),
                                      })
                                    : curWorker === 'official'
                                      ? t('settings.general.harnesses.subTargetNative')
                                      : workerModel || workerP?.name || curWorker}
                                </span>
                              </span>
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
                aria-label={t('settings.general.danger.selectAria')}
                title={
                  (() => {
                    const target = harnesses.find((x) => x.agent_type === selectedDangerAgent);
                    return target ? `${target.display_name} · ${target.config_path}` : undefined;
                  })()
                }
                value={selectedDangerAgent}
                onChange={(e) => setSelectedDangerAgent(e.target.value)}
              >
                {harnesses
                  .filter((h) => h.agent_type !== 'coreagent')
                  .map((h) => (
                    <option
                      key={h.agent_type}
                      value={h.agent_type}
                      title={`${h.display_name} · ${h.config_path}`}
                    >
                      {h.display_name} · {shortConfigFilename(h.config_path)}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                className="ui-danger-pill"
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
        <div className="s-card" data-testid="zone-sidecar-ai">
          <div className="ssec">
            <div className="ssec-h">
              <div>
                <h3>{t('settings.general.sidecar.title')}</h3>
                <div className="ssec-sub">{t('settings.general.sidecar.subtitle')}</div>
              </div>
            </div>

            <div className="sidecar-list">
              {/* 第 1 行：轻量 AI */}
              <div className="sidecar-row" data-testid="sidecar-lightagent">
                <div className="sidecar-info">
                  <div className="sidecar-title-line">
                    <Sparkles size={15} strokeWidth={1.5} className="shrink-0 text-[var(--text-secondary)]" />
                    <span>{t('settings.general.sidecar.lightagent.name')}</span>
                    {hookReview?.env_off ? (
                      <span
                        className="s-pill warn"
                        style={{ marginLeft: 0 }}
                        title={lightModelLabel}
                      >
                        {t('settings.general.sidecar.lightagent.envOffBadge')}
                      </span>
                    ) : (
                      <span
                        className="s-kind"
                        title={t('settings.general.sidecar.tierLight', { model: lightModelLabel })}
                      >
                        {lightModelLabel}
                      </span>
                    )}
                    {hookReview?.lightagent?.status === 'no_key' && (
                      <button
                        type="button"
                        className="fix-btn"
                        onClick={() =>
                          lightConnection
                            ? openProfileModal('edit', lightConnection)
                            : openProfileModal('add-endpoint')
                        }
                        data-testid="sidecar-lightagent-fix"
                      >
                        {t('settings.general.sidecar.fixKey', {
                          defaultValue: isZh ? '补全密钥' : 'Add API key',
                        })}
                      </button>
                    )}
                    {hookReview?.lightagent?.status === 'not_configured' && (
                      <button
                        type="button"
                        className="fix-btn warn"
                        onClick={() => openProfileModal('add-endpoint')}
                        data-testid="sidecar-lightagent-fix"
                      >
                        {t('settings.general.sidecar.fixConfigure', {
                          defaultValue: isZh ? '立即配置' : 'Configure',
                        })}
                      </button>
                    )}
                  </div>
                  <div className="sidecar-desc-line">
                    <span className="sidecar-desc-text">
                      {t('settings.general.sidecar.lightagent.roleShort')}
                    </span>
                    <button
                      type="button"
                      className="sidecar-why-btn"
                      aria-label={t('settings.general.sidecar.whyLabel')}
                      aria-expanded={openWhyKey === 'lightagent'}
                      title={t('settings.general.sidecar.lightagent.why')}
                      onClick={() => setOpenWhyKey((k) => (k === 'lightagent' ? null : 'lightagent'))}
                      data-testid="sidecar-why-btn-lightagent"
                    >
                      <Info size={13} strokeWidth={1.5} />
                    </button>
                  </div>
                  {openWhyKey === 'lightagent' && (
                    <div className="sidecar-why-box" data-testid="sidecar-why-box-lightagent">
                      {t('settings.general.sidecar.lightagent.why')}
                    </div>
                  )}
                </div>
                <div className="sidecar-ctl">
                  <div className="sidecar-switch-wrap">
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
                    <span className="whitespace-nowrap text-[11.5px] text-[var(--text-muted)]">
                      {hookReviewEnabled
                        ? t('settings.general.sidecar.lightagent.reviewOn')
                        : t('settings.general.sidecar.lightagent.reviewOff')}
                    </span>
                  </div>
                  <select
                    className="sselect"
                    aria-label={t('settings.general.sidecar.lightagent.selectAria')}
                    title={
                      lightBinding?.profile_id
                        ? `${lightConnection?.name ?? lightBinding.profile_id} (${lightModelLabel})`
                        : `${t('settings.general.sidecar.lightagent.optAutoFallback')}${lightConnection ? ` → ${lightConnection.name}` : ''}`
                    }
                    value={lightBinding?.profile_id ?? ''}
                    disabled={busyKey !== null}
                    onChange={(e) => handleBindSidecar('lightagent', e.target.value)}
                  >
                    <option
                      value=""
                      title={t('settings.general.sidecar.lightagent.optAutoFallback')}
                    >
                      {t('settings.general.sidecar.lightagent.optAutoFallbackShort')}
                    </option>
                    {renderSidecarOptions()}
                  </select>
                </div>
              </div>

              {/* 第 2 行：旁路 AI */}
              <div className="sidecar-row" data-testid="sidecar-observer">
                <div className="sidecar-info">
                  <div className="sidecar-title-line">
                    <Eye size={15} strokeWidth={1.5} className="shrink-0 text-[var(--text-secondary)]" />
                    <span>{t('settings.general.sidecar.observer.name')}</span>
                    {obsConnection ? (
                      <span
                        className="s-kind"
                        title={t('settings.general.sidecar.tierLight', { model: obsModelLabel })}
                      >
                        {obsModelLabel}
                      </span>
                    ) : (
                      <span className="s-pill off" style={{ marginLeft: 0 }}>
                        {t('settings.general.sidecar.observer.offBadge')}
                      </span>
                    )}
                  </div>
                  <div className="sidecar-desc-line">
                    <span className="sidecar-desc-text">
                      {t('settings.general.sidecar.observer.roleShort')}
                    </span>
                    <button
                      type="button"
                      className="sidecar-why-btn"
                      aria-label={t('settings.general.sidecar.whyLabel')}
                      aria-expanded={openWhyKey === 'observer'}
                      title={t('settings.general.sidecar.observer.why')}
                      onClick={() => setOpenWhyKey((k) => (k === 'observer' ? null : 'observer'))}
                      data-testid="sidecar-why-btn-observer"
                    >
                      <Info size={13} strokeWidth={1.5} />
                    </button>
                  </div>
                  {openWhyKey === 'observer' && (
                    <div className="sidecar-why-box" data-testid="sidecar-why-box-observer">
                      {t('settings.general.sidecar.observer.why')}
                    </div>
                  )}
                </div>
                <div className="sidecar-ctl">
                  <select
                    className="sselect"
                    aria-label={t('settings.general.sidecar.observer.selectAria')}
                    title={
                      obsBinding?.profile_id && obsConnection
                        ? `${obsConnection.name}${obsModelLabel ? ` (${obsModelLabel})` : ''}`
                        : t('settings.general.sidecar.observer.optOff')
                    }
                    value={obsBinding?.profile_id ?? ''}
                    disabled={busyKey !== null}
                    onChange={(e) => handleBindSidecar('observer', e.target.value)}
                  >
                    <option value="" title={t('settings.general.sidecar.observer.optOff')}>
                      {t('settings.general.sidecar.observer.optOffShort')}
                    </option>
                    {renderSidecarOptions()}
                  </select>
                </div>
              </div>

              {/* 第 3 行：桌面语音识别 */}
              <div className="sidecar-row" data-testid="sidecar-asr">
                <div className="sidecar-info">
                  <div className="sidecar-title-line">
                    <Mic size={15} strokeWidth={1.5} className="shrink-0 text-[var(--text-secondary)]" />
                    <span>{t('settings.general.sidecar.asr.name')}</span>
                    {asrConnection ? (
                      <span
                        className="s-kind"
                        title={t('settings.general.sidecar.asr.activeBadge', {
                          name: asrConnection.name,
                          model: asrModelLabel,
                        })}
                      >
                        {asrBinding?.profile_id
                          ? asrModelLabel
                          : `${asrConnection.name} · ${asrModelLabel}`}
                      </span>
                    ) : (
                      <>
                        <span className="s-pill off" style={{ marginLeft: 0 }}>
                          {t('settings.general.sidecar.unconfigured')}
                        </span>
                        {profiles.length === 0 && (
                          <button
                            type="button"
                            className="fix-btn warn"
                            onClick={() => openProfileModal('add-endpoint')}
                            data-testid="sidecar-asr-fix"
                          >
                            {t('settings.general.sidecar.fixConfigure', {
                              defaultValue: isZh ? '立即配置' : 'Configure',
                            })}
                          </button>
                        )}
                      </>
                    )}
                  </div>
                  <div className="sidecar-desc-line">
                    <span className="sidecar-desc-text">
                      {t('settings.general.sidecar.asr.roleShort')}
                    </span>
                    <button
                      type="button"
                      className="sidecar-why-btn"
                      aria-label={t('settings.general.sidecar.whyLabel')}
                      aria-expanded={openWhyKey === 'asr'}
                      title={t('settings.general.sidecar.asr.why')}
                      onClick={() => setOpenWhyKey((k) => (k === 'asr' ? null : 'asr'))}
                      data-testid="sidecar-why-btn-asr"
                    >
                      <Info size={13} strokeWidth={1.5} />
                    </button>
                  </div>
                  {openWhyKey === 'asr' && (
                    <div className="sidecar-why-box" data-testid="sidecar-why-box-asr">
                      {t('settings.general.sidecar.asr.why')}
                    </div>
                  )}
                </div>
                <div className="sidecar-ctl">
                  <select
                    className="sselect"
                    aria-label={t('settings.general.sidecar.asr.selectAria')}
                    title={
                      asrBinding?.profile_id && asrConnection
                        ? `${asrConnection.name} (${asrModelLabel})`
                        : t('settings.general.sidecar.asr.optAutoMatch')
                    }
                    value={asrBinding?.profile_id ?? ''}
                    disabled={busyKey !== null}
                    onChange={(e) => handleBindSidecar('asr', e.target.value)}
                    data-testid="sidecar-asr-select"
                  >
                    <option value="" title={t('settings.general.sidecar.asr.optAutoMatch')}>
                      {t('settings.general.sidecar.asr.optAutoMatchShort')}
                    </option>
                    {renderSidecarOptions(true)}
                  </select>
                </div>
              </div>

              {/* 第 4 行：决策模型 */}
              <div
                className="sidecar-row sidecar-row--expandable"
                data-testid="sidecar-decision"
              >
                <div className="sidecar-info">
                  <div className="sidecar-title-line">
                    <Gauge size={15} strokeWidth={1.5} className="shrink-0 text-[var(--text-secondary)]" />
                    <span>{t('settings.general.sidecar.decision.name')}</span>
                    {decisionSettings?.configured && decisionSettings.enabled ? (
                      <span
                        className="s-kind"
                        title={t('settings.general.sidecar.decision.activeBadge', {
                          wire: decisionSettings.wire,
                          model: decisionSettings.model,
                        })}
                      >
                        {`${decisionSettings.wire} · ${decisionSettings.model}`}
                      </span>
                    ) : (
                      <>
                        <span className="s-pill off" style={{ marginLeft: 0 }}>
                          {decisionSettings?.configured
                            ? t('settings.general.sidecar.decision.disabledBadge')
                            : t('settings.general.sidecar.unconfigured')}
                        </span>
                        {!decisionSettings?.configured && !decisionOpen && (
                          <button
                            type="button"
                            className="fix-btn warn"
                            onClick={() => setDecisionOpen(true)}
                            data-testid="sidecar-decision-fix"
                          >
                            {t('settings.general.sidecar.fixConfigure', {
                              defaultValue: isZh ? '立即配置' : 'Configure',
                            })}
                          </button>
                        )}
                      </>
                    )}
                  </div>
                  <div className="sidecar-desc-line">
                    <span className="sidecar-desc-text">
                      {t('settings.general.sidecar.decision.roleShort')}
                    </span>
                    <button
                      type="button"
                      className="sidecar-why-btn"
                      aria-label={t('settings.general.sidecar.whyLabel')}
                      aria-expanded={openWhyKey === 'decision'}
                      title={t('settings.general.sidecar.decision.roleAndWhy')}
                      onClick={() => setOpenWhyKey((k) => (k === 'decision' ? null : 'decision'))}
                      data-testid="sidecar-why-btn-decision"
                    >
                      <Info size={13} strokeWidth={1.5} />
                    </button>
                  </div>
                  {openWhyKey === 'decision' && (
                    <div className="sidecar-why-box" data-testid="sidecar-why-box-decision">
                      {t('settings.general.sidecar.decision.roleAndWhy')}
                    </div>
                  )}
                </div>
                <div className="sidecar-ctl">
                  {decisionSettings?.configured && (
                    <button
                      type="button"
                      role="switch"
                      aria-checked={decisionSettings.enabled}
                      disabled={decisionSaving}
                      onClick={handleToggleDecisionEnabled}
                      className={`tog ${decisionSettings.enabled ? '' : 'off'}`}
                      style={{ marginLeft: 0 }}
                      title={t('settings.general.sidecar.decision.enableSwitch')}
                      data-testid="decision-model-quick-toggle"
                    />
                  )}
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{ height: 30, fontSize: 12, flexShrink: 0 }}
                    onClick={() => setDecisionOpen(!decisionOpen)}
                    data-testid="decision-model-toggle-btn"
                  >
                    <span>
                      {decisionOpen
                        ? t('settings.general.sidecar.decision.hideBtn')
                        : t('settings.general.sidecar.decision.configBtn')}
                    </span>
                    {decisionOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                  </button>
                </div>

                {decisionOpen && (
                  <div className="sidecar-form-slot">
                    <div className="fbox" style={{ background: 'var(--bg-secondary)', padding: '14px 16px' }}>
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
                            {decisionSettings?.has_api_key && (
                              <button
                                type="button"
                                className={`btn btn-sm ${decisionClearKey ? 'danger-out' : 'btn-ghost'}`}
                                onClick={() => setDecisionClearKey(!decisionClearKey)}
                                data-testid="decision-model-clear-key-btn"
                              >
                                {t('settings.decisionModel.clearApiKey')}
                              </button>
                            )}
                          </div>
                          {decisionClearKey && (
                            <span className="hint">{t('settings.decisionModel.clearApiKeyPending')}</span>
                          )}
                        </div>
                      </div>
                      <div className="fgrid2">
                        <div className="fgrp">
                          <label htmlFor="decision-temperature-input">
                            {t('settings.decisionModel.temperatureLabel')}
                          </label>
                          <input
                            id="decision-temperature-input"
                            type="number"
                            step="0.05"
                            min="0.01"
                            className="sinput mono"
                            value={decisionTemperature}
                            onChange={(e) => setDecisionTemperature(e.target.value)}
                            placeholder={t('settings.decisionModel.temperaturePlaceholder')}
                            data-testid="decision-model-temperature-input"
                          />
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
                  </div>
                )}
              </div>
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
                <div className="ssec-sub">{t('settings.general.providers.subtitle')}</div>
              </div>
              <div className="ssec-actions">
                <div
                  className="ui-seg-group"
                  role="group"
                  aria-label={t('settings.general.providers.sortAria')}
                >
                  <button
                    type="button"
                    className={`ui-seg-pill ${profileSortOrder === 'asc' ? 'ui-seg-pill--active' : ''}`}
                    style={{ padding: '0 8px', fontSize: 11.5 }}
                    aria-pressed={profileSortOrder === 'asc'}
                    title={t('settings.general.providers.sortAscTitle')}
                    onClick={() => handleChangeProfileSortOrder('asc')}
                    data-testid="profile-sort-asc"
                  >
                    <ArrowDownAZ size={13} />
                    <span>{t('settings.general.providers.sortAsc')}</span>
                  </button>
                  <button
                    type="button"
                    className={`ui-seg-pill ${profileSortOrder === 'desc' ? 'ui-seg-pill--active' : ''}`}
                    style={{ padding: '0 8px', fontSize: 11.5 }}
                    aria-pressed={profileSortOrder === 'desc'}
                    title={t('settings.general.providers.sortDescTitle')}
                    onClick={() => handleChangeProfileSortOrder('desc')}
                    data-testid="profile-sort-desc"
                  >
                    <ArrowUpZA size={13} />
                    <span>{t('settings.general.providers.sortDesc')}</span>
                  </button>
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ height: 28, fontSize: 12 }}
                  onClick={() => openProfileModal('add-vendor')}
                  data-testid="add-vendor-cli-btn"
                >
                  <Terminal size={13} />
                  {t('settings.general.providers.addVendorBtn')}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  style={{ height: 28, fontSize: 12 }}
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
                    <th
                      style={{ width: '24%' }}
                      aria-sort={profileSortOrder === 'asc' ? 'ascending' : 'descending'}
                    >
                      <button
                        type="button"
                        className="stbl-sort-btn"
                        title={
                          profileSortOrder === 'asc'
                            ? t('settings.general.providers.sortDescTitle')
                            : t('settings.general.providers.sortAscTitle')
                        }
                        onClick={() =>
                          handleChangeProfileSortOrder(
                            profileSortOrder === 'asc' ? 'desc' : 'asc',
                          )
                        }
                        data-testid="profile-sort-toggle"
                      >
                        <span>{t('settings.general.providers.colProvider')}</span>
                        {profileSortOrder === 'asc' ? (
                          <ArrowDownAZ size={13} />
                        ) : (
                          <ArrowUpZA size={13} />
                        )}
                      </button>
                    </th>
                    <th style={{ width: '16%' }}>
                      {t('settings.general.providers.colProtocols')}
                    </th>
                    <th style={{ width: '25%' }}>
                      {t('settings.general.providers.colModels')}
                    </th>
                    <th style={{ width: '25%' }}>
                      {t('settings.general.providers.colUsedBy')}
                    </th>
                    <th style={{ width: '10%' }}>
                      {t('settings.general.providers.colActions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedProfiles.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        style={{ textAlign: 'center', padding: '20px 10px', color: 'var(--text-muted)' }}
                      >
                        {t('settings.general.providers.empty')}
                      </td>
                    </tr>
                  ) : (
                    sortedProfiles.map((p) => {
                      const isRet = p.kind === 'workbuddy';
                      const isVendor = p.kind === 'vendor_cli';
                      const isNoKey = p.kind === 'endpoint' && !p.api_key_masked;
                      const refs = refsByProfile[p.id] || [];
                      const protoTags = getProfileProtocolTags(p);
                      const primaryModel =
                        p.default_model ||
                        p.channels?.find((ch) => ch.models && ch.models.length > 0)?.models[0] ||
                        null;
                      const endpointLabel = formatProviderMetaEndpoint(p);
                      const metaText = isRet
                        ? t('settings.general.providers.metaRetired')
                        : isVendor
                          ? t('settings.general.providers.metaVendor', {
                              core: p.agent_type || 'agy',
                            })
                          : `${endpointLabel}${p.api_key_masked ? ` · ${p.api_key_masked}` : ''}`;

                      const ctxParts: string[] = [];
                      if (p.haiku_model && p.haiku_model !== primaryModel) {
                        ctxParts.push(
                          t('settings.general.providers.lightPrefix', { model: p.haiku_model }),
                        );
                      }
                      if (p.channels) {
                        for (const ch of p.channels) {
                          const chModel = ch.models?.[0];
                          if (chModel && chModel !== primaryModel && chModel !== p.haiku_model) {
                            const chTag = ch.protocol === 'responses' ? 'Responses' : ch.protocol;
                            ctxParts.push(`${chTag}: ${chModel}`);
                          }
                        }
                      }
                      if (p.context_window) {
                        ctxParts.push(`${Math.round(p.context_window / 1000)}k ctx`);
                      }
                      if (p.agy_context_window) {
                        ctxParts.push(`agy ${p.agy_context_window}`);
                      }

                      const isExpanded = Boolean(expandedRefIds[p.id]);
                      const visibleRefs = isExpanded ? refs : refs.slice(0, 2);

                      return (
                        <tr key={p.id} data-testid={`profile-row-${p.id}`}>
                          <td className="nm">
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span className="truncate" title={p.name}>
                                {p.name}
                              </span>
                              {isRet ? (
                                <>
                                  <span
                                    className="s-pill warn shrink-0"
                                    style={{ height: 17, padding: '0 5px', fontSize: 10, marginLeft: 0 }}
                                  >
                                    {t('settings.general.providers.badgeRetired')}
                                  </span>
                                  <button
                                    type="button"
                                    className="fix-btn warn shrink-0"
                                    onClick={() => openProfileModal('add-endpoint')}
                                    data-testid={`profile-fix-${p.id}`}
                                  >
                                    {t('settings.general.providers.fixReplace', {
                                      defaultValue: isZh ? '替换配置' : 'Replace',
                                    })}
                                  </button>
                                </>
                              ) : isVendor ? (
                                <span className="s-kind shrink-0">
                                  {t('settings.general.providers.badgeVendor')}
                                </span>
                              ) : (
                                isNoKey && (
                                  <button
                                    type="button"
                                    className="fix-btn shrink-0"
                                    onClick={() => openProfileModal('edit', p)}
                                    data-testid={`profile-fix-${p.id}`}
                                  >
                                    {t('settings.general.sidecar.fixKey', {
                                      defaultValue: isZh ? '补全密钥' : 'Add API key',
                                    })}
                                  </button>
                                )
                              )}
                            </div>
                            <div className="provider-meta" title={metaText}>
                              {metaText}
                            </div>
                          </td>
                          <td>
                            <div
                              className="proto-text-list"
                              title={protoTags
                                .map((pt) => (pt.url ? `${pt.label} (${pt.url})` : pt.label))
                                .join(' · ')}
                            >
                              {isRet ? (
                                <span className="text-[11.5px] text-[var(--accent-warning)]">
                                  {t('settings.general.providers.protoEncrypted')}
                                </span>
                              ) : (
                                <>
                                  {protoTags.slice(0, 2).map((pt, idx) => (
                                    <span key={`${pt.label}-${idx}`} title={pt.url || undefined}>
                                      {idx > 0 ? '· ' : ''}
                                      {pt.label === 'OpenAI Responses' ? 'Responses' : pt.label}
                                    </span>
                                  ))}
                                  {protoTags.length > 2 && (
                                    <span
                                      className="s-kind"
                                      title={protoTags
                                        .slice(2)
                                        .map((x) => x.label)
                                        .join(', ')}
                                    >
                                      +{protoTags.length - 2}
                                    </span>
                                  )}
                                </>
                              )}
                            </div>
                          </td>
                          <td className="mono">
                            {isRet ? (
                              <span style={{ color: 'var(--text-muted)' }}>—</span>
                            ) : (
                              <>
                                <div className="truncate" title={primaryModel || undefined}>
                                  {primaryModel || t('settings.general.providers.modelDefault')}
                                </div>
                                {ctxParts.length > 0 && (
                                  <div
                                    className="provider-model-sub"
                                    title={ctxParts.join(' · ')}
                                  >
                                    {ctxParts.join(' · ')}
                                  </div>
                                )}
                              </>
                            )}
                          </td>
                          <td>
                            {refs.length === 0 ? (
                              <span className="ref-unused-text">
                                {t('settings.general.providers.refUnused')}
                              </span>
                            ) : (
                              <div className="flex flex-wrap items-center gap-1">
                                {visibleRefs.map((r) => (
                                  <span
                                    key={r.key}
                                    className={`ref-chip ${r.isAuto ? 'ref-chip--auto' : ''}`}
                                  >
                                    {r.label}
                                  </span>
                                ))}
                                {refs.length > 2 && (
                                  <button
                                    type="button"
                                    className="ref-chip ref-chip--more"
                                    data-testid={`profile-refs-toggle-${p.id}`}
                                    title={refs
                                      .slice(2)
                                      .map((x) => x.label)
                                      .join(', ')}
                                    onClick={() =>
                                      setExpandedRefIds((prev) => ({
                                        ...prev,
                                        [p.id]: !prev[p.id],
                                      }))
                                    }
                                  >
                                    {isExpanded ? '−' : `+${refs.length - 2}`}
                                  </button>
                                )}
                              </div>
                            )}
                          </td>
                          <td className="acts">
                            <button
                              type="button"
                              className="btn-icon-sm"
                              title={t('settings.general.providers.editTitle')}
                              aria-label={`Edit ${p.name}`}
                              onClick={() => openProfileModal('edit', p)}
                              data-testid={`edit-profile-${p.id}`}
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              type="button"
                              className="btn-icon-sm"
                              title={t('settings.general.providers.deleteTitle')}
                              aria-label={`Delete ${p.name}`}
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
        <div className="space-y-2">
          <p className="text-sm text-[var(--text-secondary)]">
            {t('settings.profiles.confirmDeleteDesc')}
          </p>
          {deletingProfile && (refsByProfile[deletingProfile.id]?.length ?? 0) > 0 && (
            <div className="salert warn" data-testid="delete-profile-affected-warn">
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <span>
                {t('settings.general.providers.confirmDeleteAffected', {
                  refs: refsByProfile[deletingProfile.id].map((r) => r.label).join(', '),
                })}
              </span>
            </div>
          )}
        </div>
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
