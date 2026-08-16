/**
 * PromptCapabilitySettings — frago 给 agent 的提示分两层，这里把两层摊开讲。
 *
 * 设置页其余分区的框架是"给你一堆东西去管理"。一个刚装好 frago 的人第一眼要
 * 知道的不是清单，是**此刻到底有没有在工作**——尤其是轻量 ai 那层：不配模型
 * 它就静默不存在，配了而 api key 为空则每一轮都白等一次注定失败的请求。两种
 * 情况过去在界面上都毫无痕迹。
 *
 * 所以这个面板按状态组织，而不是按选项组织：每层一张卡，卡上先说它是什么、
 * 现在活没活、不活的后果是什么，再给一键去补的入口。
 */

import { useCallback, useEffect, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import {
  ShieldCheck,
  Sparkles,
  CircleCheck,
  TriangleAlert,
  CircleSlash,
  KeyRound,
  ArrowRight,
  LoaderCircle,
} from 'lucide-react';

import { getHookReviewStatus, setHookReviewEnabled } from '@/api';
import type { HookReviewStatus, LightweightAiStatus } from '@/api';

interface PromptCapabilitySettingsProps {
  /** 跳去配模型 profile 的地方（general 分区的模型配置弹窗）。 */
  onConfigureProfile: () => void;
}

/** 每种状态配一个语气：色调、图标、以及卡片的整体舒适态。 */
const TONE: Record<LightweightAiStatus, { tone: string; Icon: typeof CircleCheck }> = {
  enabled: { tone: 'ok', Icon: CircleCheck },
  disabled: { tone: 'off', Icon: CircleSlash },
  not_configured: { tone: 'warn', Icon: TriangleAlert },
  no_key: { tone: 'alert', Icon: KeyRound },
};

export default function PromptCapabilitySettings({
  onConfigureProfile,
}: PromptCapabilitySettingsProps) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<HookReviewStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await getHookReviewStatus());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.capability.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggle = async (enabled: boolean) => {
    setSaving(true);
    try {
      // 后端回的是重算后的完整状态，所以不做乐观更新——开关和它导致的状态
      // 文案必须是同一次判定的结果，否则会短暂显示一组自相矛盾的说明。
      setStatus(await setHookReviewEnabled(enabled));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.capability.saveFailed'));
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
    return <div className="settings-cap-error">{error || t('settings.capability.loadFailed')}</div>;
  }

  const ai = status.lightweight_ai;
  const { tone, Icon } = TONE[ai.status];
  const count = status.static_rules.count;

  return (
    <div className="settings-cap">
      <p className="settings-cap-intro">{t('settings.capability.intro')}</p>

      {error && <div className="settings-cap-error">{error}</div>}

      {/* ── 第一层：静态规则 ───────────────────────────────────── */}
      <section className="settings-cap-card is-ok">
        <header className="settings-cap-head">
          <span className="settings-cap-mark">
            <ShieldCheck size={18} />
          </span>
          <div className="settings-cap-heading">
            <h3 className="settings-cap-name">{t('settings.capability.static.name')}</h3>
            <p className="settings-cap-lede">{t('settings.capability.static.lede')}</p>
          </div>
          <span className="settings-cap-badge is-ok">
            <CircleCheck size={13} />
            {t('settings.capability.static.badge')}
          </span>
        </header>

        {/* `total`, not `count` — i18next reserves `count` for plural selection,
            and this string has no plural forms to select between. */}
        <p className="settings-cap-body">
          {count === null
            ? t('settings.capability.static.countUnknown')
            : t('settings.capability.static.count', { total: count })}
        </p>
        <p className="settings-cap-note">{t('settings.capability.static.noConfigNeeded')}</p>
      </section>

      {/* ── 第二层：轻量 ai ────────────────────────────────────── */}
      <section className={`settings-cap-card is-${tone}`}>
        <header className="settings-cap-head">
          <span className="settings-cap-mark">
            <Sparkles size={18} />
          </span>
          <div className="settings-cap-heading">
            <h3 className="settings-cap-name">{t('settings.capability.ai.name')}</h3>
            <p className="settings-cap-lede">{t('settings.capability.ai.lede')}</p>
          </div>
          <span className={`settings-cap-badge is-${tone}`}>
            <Icon size={13} />
            {t(`settings.capability.ai.badge.${ai.status}`)}
          </span>
        </header>

        <p className="settings-cap-body">
          {t(`settings.capability.ai.body.${ai.status}`, {
            model: ai.model || t('settings.capability.ai.unknownModel'),
            profile: ai.profile_name || t('settings.capability.ai.unnamedProfile'),
          })}
        </p>

        {(ai.status === 'not_configured' || ai.status === 'no_key') && (
          <p className="settings-cap-consequence">
            {t(`settings.capability.ai.consequence.${ai.status}`)}
          </p>
        )}

        {ai.detail && <p className="settings-cap-detail">{ai.detail}</p>}

        {(ai.status === 'not_configured' || ai.status === 'no_key') && (
          <button type="button" className="btn btn-primary btn-sm settings-cap-cta" onClick={onConfigureProfile}>
            {t(`settings.capability.ai.cta.${ai.status}`)}
            <ArrowRight size={14} />
          </button>
        )}

        {/* 开关 */}
        <div className="settings-cap-switch">
          <div className="settings-cap-switch-text">
            <span className="settings-cap-switch-label">{t('settings.capability.ai.switch')}</span>
            <span className="settings-cap-switch-desc">{t('settings.capability.ai.switchDesc')}</span>
          </div>
          <label className="settings-cap-toggle">
            <input
              type="checkbox"
              checked={status.enabled}
              disabled={saving}
              onChange={(e) => handleToggle(e.target.checked)}
              aria-label={t('settings.capability.ai.switch')}
            />
            <span className="settings-cap-toggle-track" />
          </label>
        </div>

        {/* Trans, so paths and env vars keep code styling inline without any
            Chinese being hardcoded here and without a markdown dependency. */}
        <p className="settings-cap-note">
          <Trans i18nKey="settings.capability.ai.persistence" components={{ c: <code /> }} />
        </p>

        {status.env_off && (
          <p className="settings-cap-consequence">
            <Trans i18nKey="settings.capability.ai.envOff" components={{ c: <code /> }} />
          </p>
        )}
      </section>
    </div>
  );
}
