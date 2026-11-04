/**
 * InitWizardPage — Prototype-aligned single-page Initial Setup flow (#setup).
 *
 * Replaces the archaic 5-step onboarding wizard. `how-to-install-frago`
 * installs all software dependencies and writes ~/.frago/{gui_config,profiles,config}.json
 * automatically; this screen only appears in the edge case where those settings
 * files are missing (e.g., a fresh container or manual install without the skill),
 * or when previewed from Settings → "Initial setup flow".
 */

import { useEffect, useState } from 'react';
import { Check, AlertTriangle, Loader2 } from 'lucide-react';
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
    display_name: 'DeepSeek (Recommended)',
    base_url: 'https://api.deepseek.com/anthropic',
    default_model: 'deepseek-chat',
    responses_url: 'https://api.deepseek.com',
    responses_models: ['deepseek-v4-flash'],
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
  const { config, setLanguage, updateConfig, showToast } = useAppStore();
  const switchPage = usePageStore((s) => s.switchPage);

  const lang: Language = (config?.language as Language) || 'zh';
  const agentLang: AgentLanguage = (config?.agent_language as AgentLanguage) || '';
  const isZh = lang === 'zh';

  const [mode, setMode] = useState<ConnectionMode>('endpoint');
  const [presets, setPresets] = useState<EndpointPreset[]>(FALLBACK_PRESETS as EndpointPreset[]);
  const [cliAgents, setCliAgents] = useState<CliAgentClientStatus[]>([]);
  const [presetId, setPresetId] = useState<string>('deepseek');
  const [profileName, setProfileName] = useState<string>('deepseek');
  const [apiKey, setApiKey] = useState<string>('');
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

  const handlePresetChange = (nextId: string) => {
    setPresetId(nextId);
    if (nextId === 'custom') {
      setProfileName('custom');
      setAnthropicUrl('https://openrouter.ai/api');
      setDefaultModel('qwen/qwen3.7-flash');
      setResponsesUrl('');
      setResponsesModel('');
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
    setLanguage(nextLang);
  };

  const handleAgentLanguageChange = (nextAgentLang: AgentLanguage) => {
    updateConfig({ agent_language: nextAgentLang });
  };

  const persistGuiConfig = async () => {
    try {
      await updateConfig({
        language: lang,
        agent_language: agentLang,
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
      setError(err instanceof Error ? err.message : 'Failed to complete setup');
    } finally {
      setSubmitting(false);
    }
  };

  const handleOpenSettings = async () => {
    await handleSkip();
    switchPage('settings');
  };

  const handleSaveAndEnter = async () => {
    setSubmitting(true);
    setError(null);
    try {
      // 1. Save GUI language & agent_language -> ~/.frago/gui_config.json
      await persistGuiConfig();

      // 2. If in API key profile mode and an API key is provided, create/update profile & bind roles
      const trimmedKey = apiKey.trim();
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
          throw new Error(createRes.error || 'Failed to create profile');
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
      showToast?.(
        isZh ? '初始配置已保存，欢迎进入工作台' : 'Initial setup saved',
        'success'
      );
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save configuration');
    } finally {
      setSubmitting(false);
    }
  };

  const inputCls =
    'w-full rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] px-2.5 py-1.5 text-[12px] text-[var(--text-primary)] focus:border-[var(--text-secondary)] focus:outline-none';
  const selectCls =
    'w-full rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] px-2.5 py-1.5 text-[12px] text-[var(--text-primary)] focus:border-[var(--text-secondary)] focus:outline-none';

  return (
    <div className="flex h-full min-h-0 flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]">
      <PageHeader
        title={isZh ? 'Initial setup · 初始配置' : 'Initial setup'}
        meta={
          isZh
            ? '~/.frago 缺失设置文件 · 边界情况恢复流程'
            : 'Settings files missing in ~/.frago · edge-case recovery flow'
        }
        secondary={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleOpenSettings}
              disabled={submitting}
              className="rounded-[6px] px-2.5 py-1 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              Settings
            </button>
            <button
              type="button"
              onClick={handleSkip}
              disabled={submitting}
              data-testid="setup-skip-top"
              title="Write default config.json (init_completed=true) and open workbench immediately"
              className="rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] px-2.5 py-1 text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
            >
              {isZh ? '直接进入工作台 →' : 'Skip to workbench →'}
            </button>
          </div>
        }
      />

      <div className="flex-1 overflow-y-auto px-7 py-4">
        <div className="mx-auto max-w-[680px]" data-testid="setup-container">
          {/* Section Header */}
          <div className="mb-2.5">
            <h2 className="text-[15px] font-semibold text-[var(--text-primary)]">
              {isZh ? 'Complete missing settings · 补齐缺失的设置文件' : 'Complete missing settings'}
            </h2>
            <p className="mt-1 text-[12px] leading-[1.55] text-[var(--text-secondary)]">
              <code className="rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[11px]">
                how-to-install-frago
              </code>{' '}
              {isZh
                ? '会自动装齐全部软件依赖并写入三份配置文件。本页仅在全新容器或手动安装导致 '
                : 'installs all software dependencies and writes these settings automatically. This screen only appears when '}
              <code className="rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[11px]">
                ~/.frago/
              </code>{' '}
              {isZh
                ? '下缺失设置文件时出现。'
                : 'settings files are missing in a fresh container or manual install.'}
            </p>
          </div>

          {/* Environment Readiness Strip */}
          {isBare ? (
            <div
              data-testid="setup-env-strip"
              className="mb-2.5 flex items-center justify-between gap-3 rounded-[8px] border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.08)] px-3 py-2 text-[12px]"
            >
              <div className="flex min-w-0 items-center gap-2 text-[var(--text-secondary)]">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent-warning)]" />
                <span className="truncate">
                  {isZh ? (
                    <>
                      全新容器：未检测到外部 Agent CLI · 填入 API Key 后即可直接运行内置{' '}
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                        CoreAgent
                      </code>
                    </>
                  ) : (
                    <>
                      Fresh container: 0 external agent CLIs detected · built-in{' '}
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                        CoreAgent
                      </code>{' '}
                      is ready once an API key is set
                    </>
                  )}
                </span>
              </div>
              <span className="shrink-0 rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2 py-0.5 text-[11px] text-[var(--accent-warning)]">
                Software managed in Environment
              </span>
            </div>
          ) : (
            <div
              data-testid="setup-env-strip"
              className="mb-2.5 flex items-center justify-between gap-3 rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-3 py-2 text-[12px]"
            >
              <div className="flex min-w-0 items-center gap-2 text-[var(--text-secondary)]">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent-primary)]" />
                <span className="truncate">
                  Environment ready ·{' '}
                  <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                    git
                  </code>
                  ,{' '}
                  <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                    uv
                  </code>
                  ,{' '}
                  <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px] text-[var(--text-primary)]">
                    tmux
                  </code>{' '}
                  present ·{' '}
                  {installedClis.map((c) => c.display_name).join(', ')} hooked
                </span>
              </div>
              <span className="shrink-0 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)]">
                Missing settings in ~/.frago
              </span>
            </div>
          )}

          {/* Card 1: Appearance & Language */}
          <div
            data-testid="setup-card-appearance"
            className="mb-2.5 rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-3"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">
                1. Appearance &amp; language
              </h3>
              <span className="font-mono text-[11px] text-[var(--text-muted)]">
                ~/.frago/gui_config.json
              </span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <label className="text-[11.5px] font-medium text-[var(--text-secondary)]">
                  Interface language
                </label>
                <select
                  data-testid="setup-lang-select"
                  value={lang}
                  onChange={(e) => handleLanguageChange(e.target.value as Language)}
                  className={selectCls}
                >
                  <option value="zh">简体中文 (Chinese)</option>
                  <option value="en">English</option>
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[11.5px] font-medium text-[var(--text-secondary)]">
                  Agent speaks
                </label>
                <select
                  data-testid="setup-agent-lang-select"
                  value={agentLang}
                  onChange={(e) => handleAgentLanguageChange(e.target.value as AgentLanguage)}
                  className={selectCls}
                >
                  <option value="">
                    Same as interface ({isZh ? '简体中文' : 'English'})
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

          {/* Card 2: Model connection & role bindings */}
          <div
            data-testid="setup-card-connection"
            className="mb-2.5 rounded-[8px] border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-4 py-3"
          >
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-[13px] font-semibold text-[var(--text-primary)]">
                  2. Model connection &amp; role bindings
                </h3>
                <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                  Populates{' '}
                  <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                    ~/.frago/profiles.json
                  </code>{' '}
                  and{' '}
                  <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                    ~/.frago/config.json
                  </code>
                </div>
              </div>
              <div
                role="tablist"
                className="inline-flex rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] p-0.5"
              >
                <button
                  type="button"
                  data-testid="setup-mode-endpoint"
                  onClick={() => setMode('endpoint')}
                  className={`rounded-[5px] px-2.5 py-1 text-[11.5px] transition-colors ${
                    mode === 'endpoint'
                      ? 'border border-[var(--sel-border)] bg-[var(--sel-bg)] font-medium text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  API key profile
                </button>
                <button
                  type="button"
                  data-testid="setup-mode-official"
                  onClick={() => setMode('official')}
                  className={`rounded-[5px] px-2.5 py-1 text-[11.5px] transition-colors ${
                    mode === 'official'
                      ? 'border border-[var(--sel-border)] bg-[var(--sel-bg)] font-medium text-[var(--text-primary)]'
                      : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  CLI login only
                </button>
              </div>
            </div>

            {mode === 'official' ? (
              <div className="divide-y divide-[var(--border-subtle)]">
                <div className="flex items-center justify-between gap-3 py-2.5">
                  <div>
                    <div className="text-[12.5px] font-medium text-[var(--text-primary)]">
                      Main agent CLIs &amp; Sub-agents (
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                        frago agent
                      </code>
                      )
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                      Sessions run on each CLI&apos;s own subscription login. frago writes nothing
                      into{' '}
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                        ~/.claude/settings.json
                      </code>
                      .
                    </div>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-2.5 py-0.5 text-[11px] text-[var(--text-secondary)]">
                    <Check size={12} />
                    Official subscription
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3 pt-2.5 pb-1">
                  <div>
                    <div className="text-[12.5px] font-medium text-[var(--text-primary)]">
                      LightAgent, Session observer &amp; CoreAgent
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-[var(--text-muted)]">
                      Require an API endpoint key that{' '}
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                        frago-core
                      </code>{' '}
                      can call directly. Rules and knowledge match by keyword until you add a
                      profile in{' '}
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                        Settings → General
                      </code>
                      .
                    </div>
                  </div>
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-full border border-[rgba(245,158,11,0.3)] bg-[rgba(245,158,11,0.1)] px-2.5 py-0.5 text-[11px] text-[var(--accent-warning)]">
                    <AlertTriangle size={12} />
                    Paused for now
                  </span>
                </div>
              </div>
            ) : (
              <div>
                {/* Preset + Profile Name + API Key */}
                <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                  <div className="flex flex-col gap-1">
                    <label className="text-[11.5px] font-medium text-[var(--text-secondary)]">
                      Provider preset
                    </label>
                    <select
                      data-testid="setup-preset-select"
                      value={presetId}
                      onChange={(e) => handlePresetChange(e.target.value)}
                      className={selectCls}
                    >
                      {presets.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.id === 'deepseek' ? 'DeepSeek (Recommended)' : p.display_name}
                        </option>
                      ))}
                      <option value="custom">OpenRouter / Custom URL</option>
                    </select>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[11.5px] font-medium text-[var(--text-secondary)]">
                      Profile name
                    </label>
                    <input
                      data-testid="setup-profile-name"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      className={inputCls}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[11.5px] font-medium text-[var(--text-secondary)]">
                      API Key{' '}
                      <span className="font-mono font-normal text-[var(--text-muted)]">(0600)</span>
                    </label>
                    <input
                      data-testid="setup-api-key"
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-..."
                      className={`${inputCls} font-mono`}
                    />
                  </div>
                </div>

                {/* Protocol endpoints & default models */}
                <div className="mt-2 rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2">
                  <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[12px] font-semibold text-[var(--text-primary)]">
                      Protocol endpoints &amp; default models
                    </span>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      Anthropic → Claude / LightAgent / Observer / CoreAgent · Responses → Codex
                    </span>
                  </div>
                  <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] text-[var(--text-secondary)]">
                        Anthropic API URL
                      </label>
                      <input
                        value={anthropicUrl}
                        onChange={(e) => setAnthropicUrl(e.target.value)}
                        className={`${inputCls} font-mono py-1`}
                      />
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-[11px] text-[var(--text-secondary)]">
                        Default Model
                      </label>
                      <input
                        value={defaultModel}
                        onChange={(e) => setDefaultModel(e.target.value)}
                        className={`${inputCls} font-mono py-1`}
                      />
                    </div>
                  </div>
                  {(responsesUrl || presetId === 'deepseek' || presetId === 'volcengine_plan') && (
                    <div className="mt-2 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                      <div className="flex flex-col gap-1">
                        <label className="text-[11px] text-[var(--text-secondary)]">
                          OpenAI Responses URL (Codex)
                        </label>
                        <input
                          value={responsesUrl}
                          onChange={(e) => setResponsesUrl(e.target.value)}
                          className={`${inputCls} font-mono py-1`}
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-[11px] text-[var(--text-secondary)]">
                          Responses Model
                        </label>
                        <input
                          value={responsesModel}
                          onChange={(e) => setResponsesModel(e.target.value)}
                          className={`${inputCls} font-mono py-1`}
                        />
                      </div>
                    </div>
                  )}
                </div>

                {/* Role bindings */}
                <div className="mt-2 rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2">
                  <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[12px] font-semibold text-[var(--text-primary)]">
                      Role bindings (
                      <code className="rounded bg-[var(--bg-hover)] px-1 py-0.5 font-mono text-[11px]">
                        Connections by role
                      </code>
                      )
                    </span>
                    <span className="text-[11px] text-[var(--text-muted)]">
                      Roles bound to <b>{profileName || 'this profile'}</b> on startup
                    </span>
                  </div>

                  <div className="space-y-1.5">
                    <label className="flex cursor-pointer items-start gap-2.5 rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-2.5 py-1.5 text-[12px]">
                      <input
                        type="checkbox"
                        checked={bindCoreRoles}
                        onChange={(e) => setBindCoreRoles(e.target.checked)}
                        className="mt-0.5"
                      />
                      <div>
                        <div>
                          <b className="font-medium text-[var(--text-primary)]">
                            LightAgent, Session observer &amp; CoreAgent
                          </b>{' '}
                          <span className="ml-1 rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--text-muted)]">
                            frago-core
                          </span>
                        </div>
                        <div className="text-[11px] text-[var(--text-muted)]">
                          Pre-turn prompt guidance (
                          <code className="font-mono">hook_review.enabled = true</code>), live
                          observer digests &amp; built-in CoreAgent
                        </div>
                      </div>
                    </label>

                    <label className="flex cursor-pointer items-start gap-2.5 rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-2.5 py-1.5 text-[12px]">
                      <input
                        type="checkbox"
                        checked={bindWorker}
                        onChange={(e) => setBindWorker(e.target.checked)}
                        className="mt-0.5"
                      />
                      <div>
                        <div>
                          <b className="font-medium text-[var(--text-primary)]">
                            Sub-agents (
                            <code className="font-mono text-[11px]">frago agent</code>)
                          </b>{' '}
                          <span className="ml-1 rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--text-muted)]">
                            worker
                          </span>
                        </div>
                        <div className="text-[11px] text-[var(--text-muted)]">
                          Background workers dispatched in tmux run on this connection without
                          touching your main terminal login
                        </div>
                      </div>
                    </label>

                    <label
                      className={`flex items-start gap-2.5 rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-secondary)] px-2.5 py-1.5 text-[12px] ${
                        isBare ? 'cursor-not-allowed opacity-55' : 'cursor-pointer'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={bindMain}
                        disabled={isBare}
                        onChange={(e) => setBindMain(e.target.checked)}
                        className="mt-0.5"
                      />
                      <div>
                        <div>
                          <b className="font-medium text-[var(--text-primary)]">
                            Main agent CLIs (Claude Code / codex)
                          </b>{' '}
                          <span className="ml-1 rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[10.5px] text-[var(--text-muted)]">
                            main
                          </span>
                        </div>
                        <div className="text-[11px] text-[var(--text-muted)]">
                          {isBare
                            ? 'No external agent CLI installed in this container — sessions default to CoreAgent'
                            : "Leave unchecked to keep your CLI's own official subscription login untouched"}
                        </div>
                      </div>
                    </label>
                  </div>
                </div>
              </div>
            )}
          </div>

          {error && (
            <div className="mb-2.5 rounded-[6px] border border-[rgba(239,68,68,0.35)] bg-[rgba(239,68,68,0.1)] px-3 py-2 text-[12px] text-[var(--accent-error)]">
              {error}
            </div>
          )}

          {/* Footer Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="text-[11.5px] text-[var(--text-muted)]">
              Writes{' '}
              <code className="rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[11px]">
                init_completed: true
              </code>{' '}
              to{' '}
              <code className="rounded bg-[var(--bg-hover)] px-1.5 py-0.5 font-mono text-[11px]">
                ~/.frago/config.json
              </code>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="setup-skip-bottom"
                onClick={handleSkip}
                disabled={submitting}
                className="rounded-[6px] border border-[var(--border-color)] bg-[var(--bg-subtle)] px-3 py-1.5 text-[12px] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
              >
                Skip for now
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
                  ? 'Save language & enter workbench'
                  : 'Save & enter workbench'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
