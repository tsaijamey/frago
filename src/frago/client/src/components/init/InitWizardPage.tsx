/**
 * InitWizardPage — 面向零先验普通用户的单页首次快速设置向导 (#setup)。
 *
 * 1. 全量接入 i18n（setupWizard 命名空间），支持中文浏览器开箱 100% 纯正简体中文展示；
 * 2. 主界面仅保留「界面与回复语言」和「选择服务商 + 粘贴 API 密钥」两步核心动作，
 *    将协议端点、模型名与角色分配等工程参数收拢至默认折叠的高级面板（选自定义地址时自动展开）；
 * 3. 保存后自动把密钥绑定给内置 CoreAgent、LightAgent、Observer 与后台数字员工（worker）。
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Check,
  AlertTriangle,
  Loader2,
  Eye,
  EyeOff,
  ChevronDown,
  ChevronUp,
  Sparkles,
} from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { useAppStore } from '@/stores/appStore';
import { usePageStore } from '@/stores/pageStore';
import type { AgentLanguage, Language } from '@/types/pywebview';
import {
  bindRole,
  createProfile,
  getCliAgentsStatus,
  getEndpointPresets,
  getProfiles,
  markInitComplete,
  setHookReviewEnabled,
  type CliAgentClientStatus,
  type EndpointPreset,
} from '@/api/client';

interface InitWizardPageProps {
  onComplete: () => void;
}

type ConnectionMode = 'endpoint' | 'official';

interface BuiltinPresetFallback {
  id: string;
  display_name: string;
  base_url: string;
  default_model: string;
  responses_url: string | null;
  responses_models: string[];
}

const FALLBACK_PRESETS: BuiltinPresetFallback[] = [
  {
    id: 'deepseek',
    display_name: 'DeepSeek (deepseek-chat)',
    base_url: 'https://api.deepseek.com/anthropic',
    default_model: 'deepseek-chat',
    responses_url: 'https://api.deepseek.com',
    responses_models: ['deepseek-v4-flash'],
  },
  {
    id: 'kimi',
    display_name: 'Kimi K2 (kimi-k2-turbo-preview)',
    base_url: 'https://api.moonshot.cn/anthropic',
    default_model: 'kimi-k2-turbo-preview',
    responses_url: null,
    responses_models: [],
  },
  {
    id: 'aliyun',
    display_name: 'Aliyun Bailian (qwen3-max)',
    base_url: 'https://dashscope.aliyuncs.com/apps/anthropic',
    default_model: 'qwen3-max',
    responses_url: null,
    responses_models: [],
  },
  {
    id: 'volcengine_plan',
    display_name: 'Volcengine Ark Agent Plan',
    base_url: 'https://ark.cn-beijing.volces.com/api/plan',
    default_model: 'ark-code-latest',
    responses_url: 'https://ark.cn-beijing.volces.com/api/plan/v3',
    responses_models: ['ark-code-latest'],
  },
];

const AGENT_LANGUAGES: { value: Exclude<AgentLanguage, ''>; name: string }[] = [
  { value: 'zh-Hans', name: '简体中文' },
  { value: 'en', name: 'English' },
  { value: 'zh-Hant', name: '繁體中文' },
  { value: 'ja', name: '日本語' },
  { value: 'de', name: 'Deutsch' },
  { value: 'fr', name: 'Français' },
  { value: 'es', name: 'Español' },
];

export function InitWizardPage({ onComplete }: InitWizardPageProps) {
  const { t, i18n } = useTranslation();
  const { config, setLanguage, updateConfig, showToast } = useAppStore();
  const switchPage = usePageStore((s) => s.switchPage);

  const detectedLang: Language = i18n.language?.startsWith('zh') ? 'zh' : 'en';
  const [selectedLang, setSelectedLang] = useState<Language>(
    (config?.language as Language) || detectedLang
  );
  const [selectedAgentLang, setSelectedAgentLang] = useState<AgentLanguage>(
    (config?.agent_language as AgentLanguage) || ''
  );

  useEffect(() => {
    if (config?.language === 'zh' || config?.language === 'en') {
      setSelectedLang(config.language);
    }
  }, [config?.language]);

  useEffect(() => {
    if (config?.agent_language !== undefined) {
      setSelectedAgentLang((config.agent_language as AgentLanguage) || '');
    }
  }, [config?.agent_language]);

  const isZh = selectedLang === 'zh';

  const [mode, setMode] = useState<ConnectionMode>('endpoint');
  const [presets, setPresets] = useState<EndpointPreset[]>(FALLBACK_PRESETS as EndpointPreset[]);
  const [cliAgents, setCliAgents] = useState<CliAgentClientStatus[]>([]);
  const [presetId, setPresetId] = useState<string>('deepseek');
  const [profileName, setProfileName] = useState<string>('deepseek');
  const [apiKey, setApiKey] = useState<string>('');
  const [showApiKey, setShowApiKey] = useState<boolean>(false);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [anthropicUrl, setAnthropicUrl] = useState<string>('https://api.deepseek.com/anthropic');
  const [defaultModel, setDefaultModel] = useState<string>('deepseek-chat');
  const [responsesUrl, setResponsesUrl] = useState<string>('https://api.deepseek.com');
  const [responsesModel, setResponsesModel] = useState<string>('deepseek-v4-flash');

  const [bindCoreRoles, setBindCoreRoles] = useState<boolean>(true);
  const [bindWorker, setBindWorker] = useState<boolean>(true);
  const [bindMain, setBindMain] = useState<boolean>(false);

  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getEndpointPresets()
      .then((res) => {
        if (!alive || !res.presets?.length) return;
        setPresets(res.presets);
        const ds = res.presets.find((p) => p.id === 'deepseek') ?? res.presets[0];
        if (ds) {
          setPresetId(ds.id);
          setProfileName(ds.id);
          setAnthropicUrl(ds.base_url);
          setDefaultModel(ds.default_model);
          setResponsesUrl(ds.responses_url || '');
          setResponsesModel(ds.responses_models?.[0] || '');
        }
      })
      .catch(() => {});

    getCliAgentsStatus()
      .then((res) => {
        if (alive && res.agents) setCliAgents(res.agents);
      })
      .catch(() => {});

    return () => {
      alive = false;
    };
  }, []);

  const installedClis = cliAgents.filter((a) => a.installed);
  const isBare = installedClis.length === 0;

  const getPresetDisplayLabel = (preset: { id: string; display_name: string }): string => {
    const key = `setupWizard.presets.${preset.id}`;
    const translated = t(key, { defaultValue: '' });
    return translated || preset.display_name;
  };

  const handlePresetChange = (nextId: string) => {
    setPresetId(nextId);
    setError(null);
    if (nextId === 'custom') {
      setProfileName('custom');
      setAnthropicUrl('https://openrouter.ai/api');
      setDefaultModel('qwen/qwen3.7-flash');
      setResponsesUrl('');
      setResponsesModel('');
      setShowAdvanced(true);
      return;
    }
    const found = presets.find((p) => p.id === nextId);
    if (found) {
      setProfileName(found.id);
      setAnthropicUrl(found.base_url);
      setDefaultModel(found.default_model);
      setResponsesUrl(found.responses_url || '');
      setResponsesModel(found.responses_models?.[0] || found.default_model || '');
    }
  };

  const handleLanguageChange = (nextLang: Language) => {
    setSelectedLang(nextLang);
    void i18n.changeLanguage(nextLang);
    setLanguage(nextLang);
  };

  const handleAgentLanguageChange = (nextAgentLang: AgentLanguage) => {
    setSelectedAgentLang(nextAgentLang);
    void updateConfig({ agent_language: nextAgentLang });
  };

  const persistGuiConfig = async () => {
    try {
      await updateConfig({
        language: selectedLang,
        agent_language: selectedAgentLang,
      });
    } catch {
      // Non-fatal; continue setup completion
    }
  };

  const handleSkip = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await persistGuiConfig();
      await markInitComplete();
      onComplete();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t('setupWizard.errorSkipFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleOpenSettings = async () => {
    await handleSkip();
    switchPage('settings');
  };

  const handleSaveAndEnter = async () => {
    const trimmedKey = apiKey.trim();
    if (mode === 'endpoint' && !trimmedKey) {
      setError(t('setupWizard.errorEmptyApiKey'));
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      // 1. Save GUI language & agent_language -> ~/.frago/gui_config.json
      await persistGuiConfig();

      // 2. In API key mode, create/update profile & bind selected roles
      if (mode === 'endpoint' && trimmedKey) {
        const cleanName = (profileName || presetId || 'deepseek').trim();
        const channels = responsesUrl.trim()
          ? [
              {
                protocol: 'responses',
                url: responsesUrl.trim(),
                models: responsesModel.trim() ? [responsesModel.trim()] : [],
              },
            ]
          : [];

        const createRes = await createProfile({
          name: cleanName,
          kind: 'endpoint',
          endpoint_type: presetId,
          api_key: trimmedKey,
          url: anthropicUrl.trim() || null,
          default_model: defaultModel.trim() || null,
          channels,
        });

        if (createRes.status === 'error' && !createRes.error?.includes('already exists')) {
          throw new Error(createRes.error || t('setupWizard.errorCreateProfile'));
        }

        // Resolve profile ID and bind selected roles
        const listRes = await getProfiles();
        const targetProfile =
          listRes.profiles.find((p) => p.name === cleanName) ??
          listRes.profiles[listRes.profiles.length - 1];

        if (targetProfile) {
          if (bindCoreRoles) {
            await Promise.all([
              bindRole('lightagent', targetProfile.id),
              bindRole('observer', targetProfile.id),
              bindRole('coreagent', targetProfile.id),
              setHookReviewEnabled(true),
            ]);
          }
          if (bindWorker) {
            await bindRole('worker', targetProfile.id);
          }
          if (bindMain && !isBare) {
            await bindRole('main', targetProfile.id);
          }
        }
      }

      // 3. Mark init_completed = true -> ~/.frago/config.json
      await markInitComplete();
      showToast?.(t('setupWizard.toastSaved'), 'success');
      onComplete();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t('setupWizard.errorSaveFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  const inputCls =
    'init-field font-mono';
  const selectCls =
    'init-field';

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]">
      <PageHeader
        title={t('setupWizard.pageTitle')}
        meta={t('setupWizard.pageSubtitle')}
        secondary={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleOpenSettings}
              disabled={submitting}
              className="rounded-[6px] px-2.5 py-1 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              {t('setupWizard.openSettings')}
            </button>
            <button
              type="button"
              onClick={handleSkip}
              disabled={submitting}
              data-testid="setup-skip-top"
              title={t('setupWizard.skipTopHint')}
              className="rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] px-2.5 py-1 text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
            >
              {t('setupWizard.skipTop')}
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto px-7 py-4">
        <div className="mx-auto max-w-[680px]" data-testid="setup-container">
          {/* Section Header */}
          <div className="mb-3">
            <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">
              {t('setupWizard.introTitle')}
            </h2>
            <p className="mt-1 text-[13px] leading-[1.6] text-[var(--text-secondary)]">
              {t('setupWizard.introDesc')}
            </p>
          </div>

          {/* Environment Readiness Strip */}
          <div
            data-testid="setup-env-strip"
            className="ui-bezel-card init-card init-env-strip mb-3 flex flex-wrap items-center justify-between gap-3 text-[12px]"
          >
            <div className="flex min-w-0 items-center gap-2 text-[var(--text-secondary)]">
              <Sparkles size={14} className="shrink-0 text-[var(--accent-primary)]" />
              <span>
                {isBare
                  ? t('setupWizard.envCoreReady')
                  : t('setupWizard.envClisDetected', {
                      clis: installedClis.map((c) => c.display_name).join('、'),
                    })}
              </span>
            </div>
            <span className="shrink-0 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-2.5 py-0.5 text-[11px] font-medium text-[var(--accent-primary)]">
              {isBare ? t('setupWizard.envCoreReadyBadge') : t('setupWizard.envClisDetectedBadge')}
            </span>
          </div>

          {/* Card 1: Interface & Reply Language */}
          <div
            data-testid="setup-card-appearance"
            className="ui-bezel-card init-card mb-3"
          >
            <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">
                {t('setupWizard.card1Title')}
              </h3>
              <span className="text-[12px] text-[var(--text-muted)]">
                {t('setupWizard.card1Hint')}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="setup-lang-select"
                  className="text-[12px] font-medium text-[var(--text-secondary)]"
                >
                  {t('setupWizard.interfaceLangLabel')}
                </label>
                <select
                  id="setup-lang-select"
                  data-testid="setup-lang-select"
                  value={selectedLang}
                  onChange={(e) => handleLanguageChange(e.target.value as Language)}
                  className={selectCls}
                >
                  <option value="zh">{t('setupWizard.interfaceLangZh')}</option>
                  <option value="en">{t('setupWizard.interfaceLangEn')}</option>
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="setup-agent-lang-select"
                  className="text-[12px] font-medium text-[var(--text-secondary)]"
                >
                  {t('setupWizard.agentLangLabel')}
                </label>
                <select
                  id="setup-agent-lang-select"
                  data-testid="setup-agent-lang-select"
                  value={selectedAgentLang}
                  onChange={(e) => handleAgentLanguageChange(e.target.value as AgentLanguage)}
                  className={selectCls}
                >
                  <option value="">
                    {t('setupWizard.agentLangFollow', {
                      name: isZh ? '简体中文' : 'English',
                    })}
                  </option>
                  {AGENT_LANGUAGES.map((l) => (
                    <option key={l.value} value={l.value}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Card 2: Connect AI Model */}
          <div
            data-testid="setup-card-connection"
            className="ui-bezel-card init-card mb-3"
          >
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">
                  {t('setupWizard.card2Title')}
                </h3>
                <div className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                  {t('setupWizard.card2Subtitle')}
                </div>
              </div>
              <div role="tablist" className="ui-seg-group">
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === 'endpoint'}
                  data-testid="setup-mode-endpoint"
                  onClick={() => {
                    setMode('endpoint');
                    setError(null);
                  }}
                  className={`ui-seg-pill ${mode === 'endpoint' ? 'ui-seg-pill--active' : ''}`}
                >
                  {t('setupWizard.modeEndpoint')}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === 'official'}
                  data-testid="setup-mode-official"
                  onClick={() => {
                    setMode('official');
                    setError(null);
                  }}
                  className={`ui-seg-pill ${mode === 'official' ? 'ui-seg-pill--active' : ''}`}
                >
                  {t('setupWizard.modeOfficial')}
                </button>
              </div>
            </div>

            {mode === 'official' ? (
              <div className="divide-y divide-[var(--border-subtle)]">
                <div className="flex items-center justify-between gap-3 py-2.5">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">
                      {t('setupWizard.officialMainTitle')}
                    </div>
                    <div className="mt-0.5 text-[12px] leading-[1.5] text-[var(--text-muted)]">
                      {t('setupWizard.officialMainDesc')}
                    </div>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-2.5 py-0.5 text-[11px] text-[var(--text-secondary)]">
                    <Check size={12} />
                    {t('setupWizard.officialMainBadge')}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3 pt-2.5 pb-1">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">
                      {t('setupWizard.officialCoreTitle')}
                    </div>
                    <div className="mt-0.5 text-[12px] leading-[1.5] text-[var(--text-muted)]">
                      {t('setupWizard.officialCoreDesc')}
                    </div>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2.5 py-0.5 text-[11px] text-[var(--accent-warning)]">
                    <AlertTriangle size={12} />
                    {t('setupWizard.officialCoreBadge')}
                  </span>
                </div>
              </div>
            ) : (
              <div>
                {/* Primary 2-column row: Provider Preset + API Key */}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1">
                    <label
                      htmlFor="setup-preset-select"
                      className="text-[12px] font-medium text-[var(--text-secondary)]"
                    >
                      {t('setupWizard.presetLabel')}
                    </label>
                    <select
                      id="setup-preset-select"
                      data-testid="setup-preset-select"
                      value={presetId}
                      onChange={(e) => handlePresetChange(e.target.value)}
                      className={selectCls}
                    >
                      {presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {getPresetDisplayLabel(p)}
                        </option>
                      ))}
                      <option value="custom">{t('setupWizard.presets.custom')}</option>
                    </select>
                  </div>

                  <div className="flex flex-col gap-1">
                    <label
                      htmlFor="setup-api-key"
                      className="text-[12px] font-medium text-[var(--text-secondary)]"
                    >
                      {t('setupWizard.apiKeyLabel')}
                    </label>
                    <div className="relative flex items-center">
                      <input
                        id="setup-api-key"
                        data-testid="setup-api-key"
                        type={showApiKey ? 'text' : 'password'}
                        value={apiKey}
                        onChange={(e) => {
                          setApiKey(e.target.value);
                          if (error) setError(null);
                        }}
                        placeholder={t('setupWizard.apiKeyPlaceholder')}
                        className={`${inputCls} pr-8 font-mono`}
                      />
                      <button
                        type="button"
                        data-testid="setup-toggle-apikey-visibility"
                        aria-label={
                          showApiKey ? t('setupWizard.hideApiKey') : t('setupWizard.showApiKey')
                        }
                        title={
                          showApiKey ? t('setupWizard.hideApiKey') : t('setupWizard.showApiKey')
                        }
                        onClick={() => setShowApiKey((prev) => !prev)}
                        className="absolute right-2 inline-flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                      >
                        {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                </div>

                <p className="mt-2 text-[12px] leading-[1.5] text-[var(--text-muted)]">
                  {t('setupWizard.apiKeyHelper')}
                </p>

                {/* Collapsible Engineering & Role Binding Options */}
                <div className="mt-2.5">
                  <button
                    type="button"
                    data-testid="setup-advanced-toggle"
                    aria-expanded={showAdvanced}
                    onClick={() => setShowAdvanced((prev) => !prev)}
                    className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  >
                    {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                    <span>
                      {showAdvanced
                        ? t('setupWizard.advancedToggleHide')
                        : t('setupWizard.advancedToggleShow')}
                    </span>
                  </button>

                  {showAdvanced && (
                    <div
                      data-testid="setup-advanced-panel"
                      className="init-advanced mt-2 space-y-2.5"
                    >
                      <div className="flex flex-col gap-1">
                        <label
                          htmlFor="setup-profile-name"
                          className="text-[11px] font-medium text-[var(--text-secondary)]"
                        >
                          {t('setupWizard.profileNameLabel')}
                        </label>
                        <input
                          id="setup-profile-name"
                          data-testid="setup-profile-name"
                          value={profileName}
                          onChange={(e) => setProfileName(e.target.value)}
                          className={inputCls}
                        />
                      </div>

                      {/* Protocol endpoints & default models */}
                      <div className="pt-1">
                        <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                          <span className="text-[12px] font-semibold text-[var(--text-primary)]">
                            {t('setupWizard.endpointsSectionTitle')}
                          </span>
                          <span className="text-[11px] text-[var(--text-muted)]">
                            {t('setupWizard.endpointsSectionHint')}
                          </span>
                        </div>
                        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                          <div className="flex flex-col gap-1">
                            <label className="text-[11px] text-[var(--text-secondary)]">
                              {t('setupWizard.anthropicUrlLabel')}
                            </label>
                            <input
                              value={anthropicUrl}
                              onChange={(e) => setAnthropicUrl(e.target.value)}
                              className={inputCls}
                            />
                          </div>
                          <div className="flex flex-col gap-1">
                            <label className="text-[11px] text-[var(--text-secondary)]">
                              {t('setupWizard.defaultModelLabel')}
                            </label>
                            <input
                              value={defaultModel}
                              onChange={(e) => setDefaultModel(e.target.value)}
                              className={inputCls}
                            />
                          </div>
                        </div>
                        {(responsesUrl ||
                          presetId === 'deepseek' ||
                          presetId === 'volcengine_plan' ||
                          presetId === 'custom') && (
                          <div className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                            <div className="flex flex-col gap-1">
                              <label className="text-[11px] text-[var(--text-secondary)]">
                                {t('setupWizard.responsesUrlLabel')}
                              </label>
                              <input
                                value={responsesUrl}
                                onChange={(e) => setResponsesUrl(e.target.value)}
                                className={inputCls}
                              />
                            </div>
                            <div className="flex flex-col gap-1">
                              <label className="text-[11px] text-[var(--text-secondary)]">
                                {t('setupWizard.responsesModelLabel')}
                              </label>
                              <input
                                value={responsesModel}
                                onChange={(e) => setResponsesModel(e.target.value)}
                                className={inputCls}
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Role bindings */}
                      <div className="pt-1">
                        <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                          <span className="text-[12px] font-semibold text-[var(--text-primary)]">
                            {t('setupWizard.rolesSectionTitle')}
                          </span>
                          <span className="text-[11px] text-[var(--text-muted)]">
                            {t('setupWizard.rolesSectionHint', {
                              name: profileName || t('setupWizard.defaultProfileFallback'),
                            })}
                          </span>
                        </div>

                        <div className="space-y-1.5">
                          <label className="init-check-row">
                            <input
                              type="checkbox"
                              checked={bindCoreRoles}
                              onChange={(e) => setBindCoreRoles(e.target.checked)}
                              className="mt-0.5"
                            />
                            <div>
                              <div className="font-medium text-[var(--text-primary)]">
                                {t('setupWizard.roleCoreTitle')}
                              </div>
                              <div className="text-[11px] text-[var(--text-muted)]">
                                {t('setupWizard.roleCoreDesc')}
                              </div>
                            </div>
                          </label>

                          <label className="init-check-row">
                            <input
                              type="checkbox"
                              checked={bindWorker}
                              onChange={(e) => setBindWorker(e.target.checked)}
                              className="mt-0.5"
                            />
                            <div>
                              <div className="font-medium text-[var(--text-primary)]">
                                {t('setupWizard.roleWorkerTitle')}
                              </div>
                              <div className="text-[11px] text-[var(--text-muted)]">
                                {t('setupWizard.roleWorkerDesc')}
                              </div>
                            </div>
                          </label>

                          <label className={`init-check-row ${isBare ? 'is-disabled' : ''}`}>
                            <input
                              type="checkbox"
                              checked={bindMain}
                              disabled={isBare}
                              onChange={(e) => setBindMain(e.target.checked)}
                              className="mt-0.5"
                            />
                            <div>
                              <div className="font-medium text-[var(--text-primary)]">
                                {t('setupWizard.roleMainTitle')}
                              </div>
                              <div className="text-[11px] text-[var(--text-muted)]">
                                {isBare
                                  ? t('setupWizard.roleMainDescBare')
                                  : t('setupWizard.roleMainDescInstalled')}
                              </div>
                            </div>
                          </label>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {error && (
            <div
              data-testid="setup-error-banner"
              role="alert"
              className="mb-3 rounded-[6px] border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 text-[12px] text-[var(--accent-error)]"
            >
              {error}
            </div>
          )}

          {/* Footer Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="text-[12px] text-[var(--text-muted)]">
              {t('setupWizard.footerPrivacyNote')}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="setup-skip-bottom"
                onClick={handleSkip}
                disabled={submitting}
                className="rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] px-3 py-1.5 text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
              >
                {t('setupWizard.skipBottom')}
              </button>
              <button
                type="button"
                data-testid="setup-save-submit"
                onClick={handleSaveAndEnter}
                disabled={submitting}
                className="inline-flex items-center gap-1.5 rounded-[6px] bg-[var(--accent-primary)] px-3.5 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-60"
              >
                {submitting && <Loader2 size={13} className="animate-spin" />}
                {mode === 'official'
                  ? t('setupWizard.saveLangAndEnter')
                  : t('setupWizard.saveAndEnter')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
