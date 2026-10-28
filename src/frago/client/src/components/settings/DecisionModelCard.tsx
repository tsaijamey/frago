/**
 * DecisionModelCard - Custom endpoint configuration card for Decision Models
 *
 * Decision models do not have fixed service providers or built-in model presets.
 * Users configure their own custom endpoint directly under two request modes:
 * - decisions: HTTP Decision API POST JSON {model, state, questions} -> {answers}
 * - ollama: Ollama /api/generate raw template + logprobs
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Check,
  Compass,
  Eye,
  EyeOff,
  Pencil,
  Sliders,
  Trash2,
  X,
} from 'lucide-react';
import {
  getDecisionModelSettings,
  resetDecisionModelSettings,
  updateDecisionModelSettings,
} from '@/api';
import type { DecisionModelSettings, DecisionWireMode } from '@/api';

export default function DecisionModelCard() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<DecisionModelSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state (user-customized only, no presets)
  const [enabled, setEnabled] = useState(true);
  const [wire, setWire] = useState<DecisionWireMode>('decisions');
  const [url, setUrl] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [clearApiKey, setClearApiKey] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [temperature, setTemperature] = useState('');

  useEffect(() => {
    void loadSettings();
  }, []);

  const populateForm = (data: DecisionModelSettings) => {
    setEnabled(data.configured ? data.enabled : true);
    setWire(data.wire);
    setUrl(data.url ?? '');
    setModel(data.model ?? '');
    setApiKey('');
    setClearApiKey(false);
    setShowApiKey(false);
    setTemperature(data.temperature != null ? String(data.temperature) : '');
  };

  const loadSettings = async () => {
    try {
      setLoading(true);
      const data = await getDecisionModelSettings();
      setSettings(data);
      populateForm(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('settings.decisionModel.loadFailed')
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      const parsedTemp =
        temperature.trim() !== '' ? Number(temperature.trim()) : null;
      if (parsedTemp !== null && (Number.isNaN(parsedTemp) || parsedTemp <= 0)) {
        setError(t('settings.decisionModel.saveFailed'));
        setSaving(false);
        return;
      }

      const updated = await updateDecisionModelSettings({
        enabled,
        wire,
        url: url.trim() || null,
        model: model.trim(),
        api_key: apiKey.trim() || null,
        clear_api_key: clearApiKey,
        temperature: parsedTemp,
      });
      setSettings(updated);
      populateForm(updated);
      setEditing(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('settings.decisionModel.saveFailed')
      );
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async () => {
    if (!settings || !settings.configured) return;
    try {
      setSaving(true);
      setError(null);
      const updated = await updateDecisionModelSettings({
        enabled: !settings.enabled,
        wire: settings.wire,
        url: settings.url,
        model: settings.model,
        temperature: settings.temperature,
      });
      setSettings(updated);
      populateForm(updated);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('settings.decisionModel.saveFailed')
      );
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    try {
      setSaving(true);
      setError(null);
      const resetData = await resetDecisionModelSettings();
      setSettings(resetData);
      populateForm(resetData);
      setEditing(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('settings.decisionModel.saveFailed')
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading || !settings) {
    return null;
  }

  return (
    <div className="s-card" data-testid="decision-model-card">
      <div className="hd">
        <span className="ico">
          <Compass size={15} />
        </span>
        <div>
          <div className="nm">{t('settings.decisionModel.title')}</div>
          <div className="ds">{t('settings.decisionModel.desc')}</div>
        </div>
        {settings.configured ? (
          settings.enabled ? (
            <span className="s-pill" data-testid="decision-model-status-active">
              <Check size={12} />
              {t('settings.decisionModel.statusActive')}
            </span>
          ) : (
            <span className="s-pill muted" data-testid="decision-model-status-disabled">
              {t('settings.decisionModel.statusDisabled')}
            </span>
          )
        ) : (
          <span className="s-pill muted" data-testid="decision-model-status-unconfigured">
            {t('settings.decisionModel.statusUnconfigured')}
          </span>
        )}
      </div>

      {error && (
        <div style={{ padding: '10px 16px 0' }}>
          <div className="salert err">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        </div>
      )}

      {!editing ? (
        settings.configured ? (
          <>
            <div className="kvgrid">
              <div>
                <div className="k">{t('settings.decisionModel.wireLabel')}</div>
                <div className="v flex items-center gap-1.5 flex-wrap">
                  <span className="s-kind">
                    {t(`settings.decisionModel.wireBadge.${settings.wire}`)}
                  </span>
                  <span>{t(`settings.decisionModel.wires.${settings.wire}`)}</span>
                </div>
              </div>
              <div>
                <div className="k">{t('settings.decisionModel.modelLabel')}</div>
                <div className="v mono" data-testid="decision-model-summary-model">
                  {settings.model}
                </div>
              </div>
              <div>
                <div className="k">{t('settings.decisionModel.urlLabel')}</div>
                <div
                  className="v mono truncate"
                  title={settings.url ?? ''}
                  data-testid="decision-model-summary-url"
                >
                  {settings.url || '—'}
                </div>
              </div>
              <div>
                <div className="k">{t('settings.decisionModel.apiKeyLabel')}</div>
                <div className="v mono">
                  {settings.has_api_key ? settings.api_key_masked : '—'}
                </div>
              </div>
              {settings.temperature != null && (
                <div>
                  <div className="k">{t('settings.decisionModel.temperatureLabel')}</div>
                  <div className="v mono">{settings.temperature}</div>
                </div>
              )}
            </div>

            <div className="row full">
              <button
                type="button"
                role="switch"
                aria-checked={settings.enabled}
                disabled={saving}
                onClick={handleToggleEnabled}
                className={`sw ${settings.enabled ? 'on' : ''}`}
                title={t('settings.decisionModel.enabledLabel')}
                data-testid="decision-model-quick-toggle"
              />
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {t('settings.decisionModel.enabledLabel')}
              </span>
              <div className="ml-auto flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    populateForm(settings);
                    setEditing(true);
                  }}
                  className="btn btn-sm"
                  data-testid="decision-model-edit-btn"
                >
                  <Pencil size={13} />
                  {t('settings.decisionModel.edit')}
                </button>
                <button
                  type="button"
                  onClick={handleReset}
                  disabled={saving}
                  className="btn btn-sm btn-danger-outline"
                  data-testid="decision-model-reset-btn"
                >
                  <Trash2 size={13} />
                  {t('settings.decisionModel.reset')}
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="row full">
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {t('settings.decisionModel.unconfiguredHint')}
            </div>
            <button
              type="button"
              onClick={() => {
                populateForm(settings);
                setEditing(true);
              }}
              className="btn btn-sm ml-auto shrink-0"
              data-testid="decision-model-configure-btn"
            >
              <Sliders size={13} />
              {t('settings.decisionModel.configure')}
            </button>
          </div>
        )
      ) : (
        <div>
          {/* Enable toggle */}
          <div className="srow">
            <div className="lbl">
              <div className="t">{t('settings.decisionModel.enabledLabel')}</div>
              <div className="d">{t('settings.decisionModel.enabledHint')}</div>
            </div>
            <div className="ctl">
              <button
                type="button"
                role="switch"
                aria-checked={enabled}
                onClick={() => setEnabled(!enabled)}
                className={`sw ${enabled ? 'on' : ''}`}
                data-testid="decision-model-enabled-switch"
              />
            </div>
          </div>

          {/* Wire / Request mode selector */}
          <div className="srow">
            <div className="lbl">
              <div className="t">{t('settings.decisionModel.wireLabel')}</div>
              <div className="d">{t(`settings.decisionModel.wireHint.${wire}`)}</div>
            </div>
            <div className="ctl">
              <select
                className="sselect"
                style={{ minWidth: 280 }}
                value={wire}
                onChange={(e) => setWire(e.target.value as DecisionWireMode)}
                data-testid="decision-model-wire-select"
              >
                <option value="decisions">
                  {t('settings.decisionModel.wires.decisions')}
                </option>
                <option value="ollama">{t('settings.decisionModel.wires.ollama')}</option>
              </select>
            </div>
          </div>

          {/* Custom Endpoint URL */}
          <div className="srow">
            <div className="lbl">
              <div className="t">{t('settings.decisionModel.urlLabel')}</div>
              <div className="d">{t(`settings.decisionModel.urlHint.${wire}`)}</div>
            </div>
            <div className="ctl">
              <input
                type="text"
                className="sinput mono"
                style={{ minWidth: 280 }}
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={t(`settings.decisionModel.urlPlaceholder.${wire}`)}
                data-testid="decision-model-url-input"
              />
            </div>
          </div>

          {/* Custom Model Name */}
          <div className="srow">
            <div className="lbl">
              <div className="t">{t('settings.decisionModel.modelLabel')}</div>
            </div>
            <div className="ctl">
              <input
                type="text"
                className="sinput mono"
                style={{ minWidth: 280 }}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={t(`settings.decisionModel.modelPlaceholder.${wire}`)}
                data-testid="decision-model-model-input"
              />
            </div>
          </div>

          {/* API Key */}
          <div className="srow">
            <div className="lbl">
              <div className="t">{t('settings.decisionModel.apiKeyLabel')}</div>
              <div className="d">{t('settings.decisionModel.apiKeyHint')}</div>
            </div>
            <div className="ctl flex-col items-end gap-1.5">
              <div className="flex items-center gap-1.5">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  className="sinput mono"
                  style={{ minWidth: 248 }}
                  value={apiKey}
                  disabled={clearApiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={
                    settings.has_api_key && !clearApiKey
                      ? t('settings.decisionModel.apiKeyConfiguredPlaceholder', {
                          masked: settings.api_key_masked,
                        })
                      : t('settings.decisionModel.apiKeyPlaceholder')
                  }
                  data-testid="decision-model-apikey-input"
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="btn btn-sm btn-ghost"
                  title={
                    showApiKey
                      ? t('settings.general.hideApiKey')
                      : t('settings.general.showApiKey')
                  }
                >
                  {showApiKey ? <EyeOff size={13} /> : <Eye size={13} />}
                </button>
              </div>
              {settings.has_api_key && (
                <button
                  type="button"
                  onClick={() => {
                    setClearApiKey(!clearApiKey);
                    if (!clearApiKey) setApiKey('');
                  }}
                  className="text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  data-testid="decision-model-clear-apikey-btn"
                >
                  {clearApiKey
                    ? t('settings.decisionModel.clearApiKeyPending')
                    : t('settings.decisionModel.clearApiKey')}
                </button>
              )}
            </div>
          </div>

          {/* Optional Temperature */}
          <div className="srow">
            <div className="lbl">
              <div className="t">{t('settings.decisionModel.temperatureLabel')}</div>
              <div className="d">{t('settings.decisionModel.temperatureHint')}</div>
            </div>
            <div className="ctl">
              <input
                type="text"
                inputMode="decimal"
                className="sinput mono"
                style={{ minWidth: 280 }}
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                placeholder={t('settings.decisionModel.temperaturePlaceholder')}
                data-testid="decision-model-temperature-input"
              />
            </div>
          </div>

          {/* Actions */}
          <div className="row full">
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setEditing(false);
                }}
                disabled={saving}
                className="btn btn-sm btn-ghost"
                data-testid="decision-model-cancel-btn"
              >
                <X size={13} />
                {t('settings.decisionModel.cancel')}
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="btn btn-sm btn-primary"
                data-testid="decision-model-save-btn"
              >
                <Check size={13} />
                {saving
                  ? t('settings.decisionModel.saving')
                  : t('settings.decisionModel.save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
