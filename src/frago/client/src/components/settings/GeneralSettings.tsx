/**
 * General Settings Component (Settings ▸ General)
 *
 * Implements the 3-segment tabbed layout (harnesses / sidecar / profiles):
 * 1. Harness 工具 — 4 external CLI coding tools with independent Daily Session & Worker bindings + single-line Danger Zone
 * 2. 内置与旁路 AI — LightAgent, Session Observer, CoreAgent, and inline Decision Model configuration
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
  Bot,
  Check,
  Code,
  Eye,
  EyeOff,
  Gauge,
  KeyRound,
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
        setHarnesses(
          DEFAULT_HARNESSES.map((h) => ({
            ...h,
            main_profile_id:
              profileData.active_profile_id &&
              (profileData.active_targets ?? ['claude']).includes(h.agent_type)
                ? profileData.active_profile_id
                : 'official',
            worker_profile_id: profileData.worker_profile_id || 'follow',
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
          `已调用 VSCode 打开 ${targetHarness?.display_name ?? selectedDangerAgent} 原生配置文件：${targetHarness?.config_path ?? ''}`,
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
        setError(res.error || 'Failed to delete provider');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete provider');
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
        map[h.main_profile_id].push(`${h.display_name} 日常`);
      }
      if (
        h.worker_profile_id &&
        h.worker_profile_id !== 'follow' &&
        h.worker_profile_id !== 'official' &&
        map[h.worker_profile_id]
      ) {
        map[h.worker_profile_id].push(`${h.display_name} Worker`);
      }
    }
    const lightBinding = bindings.find((b) => b.role === 'lightagent');
    const obsBinding = bindings.find((b) => b.role === 'observer');
    const coreBinding = bindings.find((b) => b.role === 'coreagent');

    const lightPid = lightBinding?.profile_id || lightBinding?.connection?.id;
    if (lightPid && map[lightPid]) {
      map[lightPid].push('轻量 AI');
    }
    const obsPid = obsBinding?.profile_id;
    if (obsPid && map[obsPid]) {
      map[obsPid].push('旁路 AI');
    }
    const corePid = coreBinding?.profile_id || coreBinding?.connection?.id;
    if (corePid && map[corePid]) {
      map[corePid].push('内核代理');
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
  const coreBinding = bindings.find((b) => b.role === 'coreagent');

  const lightConnection = lightBinding?.connection ?? profiles[0] ?? null;
  const obsConnection = obsBinding?.profile_id ? (obsBinding.connection ?? findProfile(obsBinding.profile_id)) : null;
  const coreConnection = coreBinding?.connection ?? profiles[0] ?? null;

  const lightModelLabel =
    lightConnection?.haiku_model ||
    lightConnection?.default_model ||
    hookReview?.lightagent?.model ||
    '未配置';
  const obsModelLabel =
    obsConnection?.haiku_model || obsConnection?.default_model || null;
  const coreModelLabel = coreConnection?.default_model || '未配置';
  const hookReviewEnabled = hookReview ? hookReview.enabled : true;

  const renderSidecarOptions = () =>
    profiles.map((p) => {
      if (p.kind === 'workbuddy') {
        return (
          <option key={p.id} value={p.id} disabled>
            {p.name} — 旧客户端已加密
          </option>
        );
      }
      if (p.kind === 'vendor_cli') {
        return (
          <option key={p.id} value={p.id} disabled>
            {p.name} — 厂商 CLI 无 API 密钥
          </option>
        );
      }
      const modelHint = p.haiku_model || p.default_model;
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
            知道了
          </button>
        </div>
      )}

      {/* 顶部三段子视图切换器 */}
      <div className="g-topbar">
        <div className="g-seg" role="tablist" aria-label="常规设置分区切换">
          <button
            type="button"
            role="tab"
            aria-selected={subTab === 'harnesses'}
            className={subTab === 'harnesses' ? 'on' : ''}
            onClick={() => setSubTab('harnesses')}
            data-testid="general-tab-harnesses"
          >
            <Terminal size={13} />
            <span>Harness 工具</span>
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
            <span>内置与旁路 AI</span>
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
            <span>AI 服务商</span>
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
                  <h3>外部 CLI 编码工具（Harness）</h3>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                    每个 Harness 工具均可独立指定「日常会话」与「派活 Worker」所使用的 AI 服务商。
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
                    全部切回原生登录
                  </button>
                )}
              </div>

              <div className="stbl-wrap">
                <table className="htbl">
                  <thead>
                    <tr>
                      <th style={{ width: '29%' }}>
                        Harness 工具
                        <span className="sub">外部 CLI 编码工具与配置文件</span>
                      </th>
                      <th style={{ width: '35.5%' }}>
                        日常会话（写入工具本地配置）
                        <span className="sub">终端手敲命令或新建交互会话生效</span>
                      </th>
                      <th style={{ width: '35.5%' }}>
                        派活 Worker（<code>frago agent</code> 临时注入）
                        <span className="sub">仅向后台子会话注入环境变量，不改文件</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {harnesses.map((h) => {
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
                              <span className="proto-tag">{h.protocol_label}</span>
                              {!h.installed && <span className="s-kind">未安装</span>}
                            </div>
                            <div className="h-meta">{h.config_path}</div>
                          </td>
                          <td>
                            <select
                              className="sselect"
                              aria-label={`${h.display_name} 日常会话配置`}
                              value={curMain}
                              disabled={busyKey !== null}
                              onChange={(e) =>
                                handleBindHarness(h.agent_type, 'main', e.target.value)
                              }
                            >
                              <option value="official">自带原生登录（不改写本地配置）</option>
                              {profiles.map((p) => {
                                if (p.kind === 'workbuddy') {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {p.name} — 旧客户端已加密
                                    </option>
                                  );
                                }
                                if (p.kind === 'vendor_cli') {
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
                                      {p.name} — 仅限派活 Worker
                                    </option>
                                  );
                                }
                                if (
                                  h.agent_type === 'codex' &&
                                  !hasProtocolChannel(p, 'responses')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {p.name} (缺 OpenAI Responses 通道)
                                    </option>
                                  );
                                }
                                if (
                                  (h.agent_type === 'claude' || h.agent_type === 'opencode') &&
                                  !hasProtocolChannel(p, 'anthropic')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {p.name} (缺 Anthropic 通道)
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
                                  <span style={{ color: 'var(--accent-primary)' }}>●</span> 已写入{' '}
                                  <code>{h.config_path}</code>
                                  {mainModel ? ` · ${mainModel}` : ` · ${mainP.name}`}
                                </>
                              ) : (
                                '保持工具自身登录态'
                              )}
                            </div>
                          </td>
                          <td>
                            <select
                              className="sselect"
                              aria-label={`${h.display_name} 派活 Worker 配置`}
                              value={curWorker}
                              disabled={busyKey !== null}
                              onChange={(e) =>
                                handleBindHarness(h.agent_type, 'worker', e.target.value)
                              }
                            >
                              <option value="follow">跟随日常会话（同上）</option>
                              <option value="official">自带原生登录（强制原号）</option>
                              {profiles.map((p) => {
                                if (p.kind === 'workbuddy') {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {p.name} — 旧客户端已加密
                                    </option>
                                  );
                                }
                                if (p.kind === 'vendor_cli') {
                                  return (
                                    <option key={p.id} value={p.id}>
                                      {p.name}
                                      {p.default_model ? ` · ${p.default_model}` : ' · 厂商 CLI 登录'}
                                    </option>
                                  );
                                }
                                if (
                                  h.agent_type === 'codex' &&
                                  !hasProtocolChannel(p, 'responses')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {p.name} (缺 OpenAI Responses 通道)
                                    </option>
                                  );
                                }
                                if (
                                  (h.agent_type === 'claude' || h.agent_type === 'opencode') &&
                                  !hasProtocolChannel(p, 'anthropic')
                                ) {
                                  return (
                                    <option key={p.id} value={p.id} disabled>
                                      {p.name} (缺 Anthropic 通道)
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
                                ? `跟随日常 → ${
                                    mainP
                                      ? `${mainP.name}${mainModel ? ` (${mainModel})` : ''}`
                                      : '原生登录'
                                  }`
                                : curWorker === 'official'
                                  ? '临时走工具自身登录态'
                                  : `每次起会话临时注入 · ${workerModel || workerP?.name || curWorker}`}
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
                Danger Zone
              </b>
              <span>
                直接编辑各 Harness 工具的原生配置文件（含已挂载钩子），改坏语法会导致对应工具或钩子失效：
              </span>
            </div>
            <div className="dzone-bar-r">
              <select
                className="sselect"
                style={{ width: 248, height: 28, fontSize: 12 }}
                aria-label="选择要打开的 Harness 原生配置文件"
                value={selectedDangerAgent}
                onChange={(e) => setSelectedDangerAgent(e.target.value)}
              >
                {harnesses.map((h) => (
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
                用 VSCode 打开
              </button>
            </div>
          </div>
        </>
      )}

      {/* 子视图 2：内置与旁路 AI */}
      {subTab === 'sidecar' && (
        <div className="s-card sc-compact" data-testid="zone-sidecar-ai">
          <div className="ssec">
            <div className="ssec-h">
              <div>
                <h3>
                  内置与旁路 AI（由 <code>frago-core</code> 直接调用接口）
                </h3>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  它们不启动外部 CLI 进程，必须绑定带 API 密钥的「AI 服务商」（无法借用 CLI 原生登录）。
                </div>
              </div>
            </div>

            {/* 第 1 行：轻量 AI · LightAgent */}
            <div className="srow" data-testid="sidecar-lightagent">
              <div className="l">
                <div className="t">
                  <Sparkles size={14} />
                  <span>
                    轻量 AI · <code>LightAgent</code>
                  </span>
                  <span className="s-kind">消费：轻量档 ({lightModelLabel})</span>
                </div>
                <div className="d">
                  <b>职责：</b>钩子审阅（拦危险命令、催收尾交付）、记忆相关性打分、长输出摘要压缩。
                  <br />
                  <b>解决：</b>替代死板正则，用毫秒级低成本小模型做高频语义把关。
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <select
                  className="sselect"
                  style={{ width: 210, height: 28, fontSize: 12 }}
                  aria-label="轻量 AI 服务商"
                  value={lightBinding?.profile_id ?? ''}
                  disabled={busyKey !== null}
                  onChange={(e) => handleBindSidecar('lightagent', e.target.value)}
                >
                  <option value="">自动回退（跟随日常会话的轻量档）</option>
                  {renderSidecarOptions()}
                </select>
                <button
                  type="button"
                  className={`tog ${hookReviewEnabled ? '' : 'off'}`}
                  role="switch"
                  aria-checked={hookReviewEnabled}
                  disabled={busyKey !== null}
                  title="开启或关闭每轮提示审阅"
                  onClick={handleToggleHookReview}
                  data-testid="lightagent-hook-toggle"
                />
                <span style={{ fontSize: 11.5, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                  {hookReviewEnabled ? '审阅开' : '审阅关'}
                </span>
              </div>
            </div>

            {/* 第 2 行：旁路 AI · Session Observer */}
            <div className="srow" data-testid="sidecar-observer">
              <div className="l">
                <div className="t">
                  <Eye size={14} />
                  <span>
                    旁路 AI · <code>Session Observer</code>
                  </span>
                  {obsConnection ? (
                    <span className="s-kind">消费：轻量档 ({obsModelLabel})</span>
                  ) : (
                    <span className="s-pill off" style={{ marginLeft: 0 }}>
                      已关闭 · 零调用
                    </span>
                  )}
                </div>
                <div className="d">
                  <b>职责：</b>在会话页右侧自动归纳「本轮做了什么、动了哪些文件、停在何处」。
                  <br />
                  <b>解决：</b>长会话无需人工翻几百条日志，一眼掌握进展。
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <select
                  className="sselect"
                  style={{ width: 222, height: 28, fontSize: 12 }}
                  aria-label="旁路 AI 服务商"
                  value={obsBinding?.profile_id ?? ''}
                  disabled={busyKey !== null}
                  onChange={(e) => handleBindSidecar('observer', e.target.value)}
                >
                  <option value="">不启用（关闭旁路观察）</option>
                  {renderSidecarOptions()}
                </select>
              </div>
            </div>

            {/* 第 3 行：内核代理 · CoreAgent */}
            <div className="srow" data-testid="sidecar-coreagent">
              <div className="l">
                <div className="t">
                  <Bot size={14} />
                  <span>
                    内核代理 · <code>CoreAgent</code>
                  </span>
                  <span className="s-kind">消费：主模型档 ({coreModelLabel})</span>
                </div>
                <div className="d">
                  <b>职责：</b>处理自然语言定时任务、一句话生成 Todo、会话标题生成及后台独立问答。
                  <br />
                  <b>解决：</b>无需拉起笨重的外部 CLI 终端，即可在后台静默完成轻量自治任务。
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                <select
                  className="sselect"
                  style={{ width: 222, height: 28, fontSize: 12 }}
                  aria-label="内核代理服务商"
                  value={coreBinding?.profile_id ?? ''}
                  disabled={busyKey !== null}
                  onChange={(e) => handleBindSidecar('coreagent', e.target.value)}
                >
                  <option value="">自动回退（跟随日常会话的主模型）</option>
                  {profiles.map((p) => {
                    if (p.kind === 'workbuddy') {
                      return (
                        <option key={p.id} value={p.id} disabled>
                          {p.name} — 旧客户端已加密
                        </option>
                      );
                    }
                    if (p.kind === 'vendor_cli') {
                      return (
                        <option key={p.id} value={p.id} disabled>
                          {p.name} — 厂商 CLI 无 API 密钥
                        </option>
                      );
                    }
                    return (
                      <option key={p.id} value={p.id}>
                        {p.name}
                        {p.default_model ? ` (${p.default_model})` : ''}
                      </option>
                    );
                  })}
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
                      决策模型 · <code>Decision Model</code>
                    </span>
                    {decisionSettings?.configured && decisionSettings.enabled ? (
                      <span className="s-kind">
                        结构化多选判定 · {decisionSettings.wire} · {decisionSettings.model}
                      </span>
                    ) : (
                      <span className="s-pill off" style={{ marginLeft: 0 }}>
                        {decisionSettings?.configured ? '已停用' : '未配置'}
                      </span>
                    )}
                  </div>
                  <div className="d">
                    <b>职责与解决：</b>
                    专门对带选项的结构化问题输出确定性判据（支持 HTTP Decision API 与 Ollama logprobs）。
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ height: 26, fontSize: 12, flexShrink: 0 }}
                  onClick={() => setDecisionOpen(!decisionOpen)}
                  data-testid="decision-model-toggle-btn"
                >
                  {decisionOpen ? '收起参数' : '配置接口 ▾'}
                </button>
              </div>

              {decisionOpen && (
                <div className="fbox" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="fgrid2">
                    <div className="fgrp">
                      <label htmlFor="decision-wire-select">判定接口类型</label>
                      <select
                        id="decision-wire-select"
                        className="sselect"
                        style={{ maxWidth: '100%' }}
                        value={decisionWire}
                        onChange={(e) => setDecisionWire(e.target.value as DecisionWireMode)}
                        data-testid="decision-model-wire-select"
                      >
                        <option value="decisions">HTTP Decisions 接口（OpenAI 兼容）</option>
                        <option value="ollama">本地 Ollama（logprobs 打分）</option>
                      </select>
                    </div>
                    <div className="fgrp">
                      <label htmlFor="decision-model-input">模型名称</label>
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
                      <label htmlFor="decision-url-input">接口地址 (Endpoint URL)</label>
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
                      <label htmlFor="decision-apikey-input">专用 API Key</label>
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
                          title={decisionShowKey ? '隐藏密钥' : '显示密钥'}
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
                      <span>启用决策模型</span>
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
                          重置
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        disabled={decisionSaving}
                        onClick={() => setDecisionOpen(false)}
                      >
                        <X size={12} />
                        取消
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        disabled={decisionSaving}
                        onClick={handleSaveDecisionModel}
                        data-testid="decision-model-save-btn"
                      >
                        <Check size={12} />
                        {decisionSaving ? '保存中…' : '保存参数'}
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
                <h3>AI 服务商与模型路由（共 {profiles.length} 个）</h3>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  统一管理 API 密钥、各协议通道地址（Anthropic / OpenAI Responses）与主、轻两档模型，供各 Harness 与内置 AI 按需选用。
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
                  + 添加厂商 CLI
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  style={{ height: 26, fontSize: 12 }}
                  onClick={() => openProfileModal('add-endpoint')}
                  data-testid="add-endpoint-provider-btn"
                >
                  <Plus size={13} />
                  + 添加服务商
                </button>
              </div>
            </div>

            <div className="stbl-wrap">
              <table className="stbl">
                <thead>
                  <tr>
                    <th style={{ width: '22%' }}>AI 服务商</th>
                    <th style={{ width: '21%' }}>已开通协议通道</th>
                    <th style={{ width: '24%' }}>主模型 / 轻量档</th>
                    <th style={{ width: '23%' }}>当前服务于</th>
                    <th style={{ width: '10%' }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.length === 0 ? (
                    <tr>
                      <td
                        colSpan={5}
                        style={{ textAlign: 'center', padding: '20px 10px', color: 'var(--text-muted)' }}
                      >
                        暂无已保存的 AI 服务商，点击右上角「+ 添加服务商」创建。
                      </td>
                    </tr>
                  ) : (
                    profiles.map((p) => {
                      const isRet = p.kind === 'workbuddy';
                      const isVendor = p.kind === 'vendor_cli';
                      const refs = refsByProfile[p.id] || [];
                      const protoTags = getProfileProtocolTags(p);
                      const ctxParts: string[] = [];
                      if (p.haiku_model) ctxParts.push(`轻: ${p.haiku_model}`);
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
                                  已停用
                                </span>
                              ) : isVendor ? (
                                <span className="s-kind">厂商 CLI</span>
                              ) : (
                                <span className="s-kind">API 密钥</span>
                              )}
                            </div>
                            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                              {isRet
                                ? '旧版客户端借用（已停用）'
                                : isVendor
                                  ? `内核：${p.agent_type || 'agy'} · 走客户端自身登录`
                                  : `${p.endpoint_type}${p.api_key_masked ? ` · ${p.api_key_masked}` : ''}`}
                            </div>
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                              {isRet ? (
                                <span style={{ fontSize: 11, color: 'var(--accent-warning)' }}>
                                  客户端已加密
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
                                <div>{p.default_model || '默认'}</div>
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
                                <span className="ref-chip idle">未引用</span>
                              )}
                            </div>
                          </td>
                          <td className="acts">
                            <button
                              type="button"
                              className="btn-icon-sm"
                              title="编辑 AI 服务商"
                              onClick={() => openProfileModal('edit', p)}
                              data-testid={`edit-profile-${p.id}`}
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              type="button"
                              className="btn-icon-sm"
                              title="删除 AI 服务商"
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
