/**
 * CliAgentSettings — 设置页「CLI 客户端」分区。
 *
 * 列出本机支持的各家 CLI Agent 客户端：已检测到的客户端点亮显示（带可执行文件
 * 路径与绿色在线圆点），未安装的客户端置灰。
 *
 * OpenCode 卡片下提供 2.0 后台常驻服务端（opencode serve --service）的禁用开关：
 * 勾选即执行 `opencode service set disabled true`（停掉常驻进程并写入
 * `~/.config/opencode/service.json`），取消勾选则执行 `opencode service unset disabled`。
 */

import { useCallback, useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { CircleSlash, LoaderCircle, Terminal } from 'lucide-react';

import { getCliAgentsStatus, setOpencodeServiceDisabled } from '@/api';
import type { CliAgentClientStatus, CliAgentsStatus } from '@/api';

const AGENT_ICONS: Record<string, string> = {
  claude: '/icons/claude-code.svg',
  'claude-code': '/icons/claude-code.svg',
  codex: '/icons/codex.svg',
  opencode: '/icons/opencode.svg',
  agy: '/icons/antigravity.png',
};

function agentIconSrc(agent: CliAgentClientStatus): string | null {
  return (
    (agent.family && AGENT_ICONS[agent.family]) ||
    AGENT_ICONS[agent.agent_type] ||
    null
  );
}

export default function CliAgentSettings() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<CliAgentsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await getCliAgentsStatus());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.cliAgents.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const handleOpencodeToggle = async (disabled: boolean) => {
    setSaving(true);
    try {
      setStatus(await setOpencodeServiceDisabled(disabled));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.cliAgents.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="settings-cap-loading">
        <LoaderCircle size={16} className="cs-spin" />
        {t('common.loadingConfiguration')}
      </div>
    );
  }

  if (!status) {
    return <div className="settings-cap-error">{error || t('settings.cliAgents.loadFailed')}</div>;
  }

  return (
    <div className="settings-cap">
      {error && <div className="settings-cap-error">{error}</div>}

      {status.agents.map((agent) => {
        const iconSrc = agentIconSrc(agent);
        const installed = agent.installed;
        const ocService = agent.opencode_service;

        return (
          <section
            key={agent.agent_type}
            data-testid={`cli-agent-card-${agent.agent_type}`}
            data-installed={installed ? 'true' : 'false'}
            className={`settings-cap-card ${installed ? 'is-ok' : 'is-off opacity-55'}`}
          >
            <header className="settings-cap-head">
              <span className="settings-cap-mark">
                {iconSrc ? (
                  <img
                    src={iconSrc}
                    alt=""
                    className={`h-4 w-4 object-contain ${installed ? '' : 'grayscale opacity-50'}`}
                  />
                ) : (
                  <Terminal size={16} />
                )}
              </span>
              <div className="settings-cap-heading">
                <h3 className="settings-cap-name">{agent.display_name}</h3>
                <p className="settings-cap-lede font-mono text-xs">
                  {installed && agent.path
                    ? agent.path
                    : t('settings.cliAgents.notDetectedHint')}
                </p>
              </div>
              <span className={`settings-cap-badge ${installed ? 'is-ok' : 'is-off'}`}>
                {installed ? (
                  <i className="settings-cap-dot" aria-hidden="true" />
                ) : (
                  <CircleSlash size={12} />
                )}
                {installed
                  ? t('settings.cliAgents.detectedBadge')
                  : t('settings.cliAgents.notDetectedBadge')}
              </span>
            </header>

            {agent.agent_type === 'opencode' && installed && ocService && (
              ocService.supported ? (
                <div className="settings-cap-switch">
                  <div className="settings-cap-switch-text">
                    <span className="settings-cap-switch-label">
                      {t('settings.cliAgents.opencode.serviceSwitch')}
                    </span>
                    <span className="settings-cap-switch-desc">
                      <Trans
                        i18nKey="settings.cliAgents.opencode.serviceSwitchDesc"
                        components={{ c: <code /> }}
                      />
                    </span>
                  </div>
                  <label className="settings-cap-toggle">
                    <input
                      type="checkbox"
                      checked={ocService.disabled}
                      disabled={saving}
                      onChange={(e) => handleOpencodeToggle(e.target.checked)}
                      aria-label={t('settings.cliAgents.opencode.serviceSwitch')}
                    />
                    <span className="settings-cap-toggle-track" />
                  </label>
                </div>
              ) : (
                <p className="settings-cap-note">
                  {t('settings.cliAgents.opencode.serviceUnsupported')}
                </p>
              )
            )}
          </section>
        );
      })}
    </div>
  );
}
