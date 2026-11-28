/**
 * About Settings Component
 *
 * Shows what frago is and which version is running. The version used to be
 * missing despite this file's own description promising it, so anyone wanting to
 * know what they were running had to leave the interface to find out.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getInitStatus } from '../../api/client';

export default function AboutSettings() {
  const { t } = useTranslation();
  const [version, setVersion] = useState<string | null>(null);
  const [resourceVersion, setResourceVersion] = useState<string | null>(null);

  useEffect(() => {
    // The init status already reports the running version and resource pack,
    // so this needs no endpoint of its own.
    getInitStatus()
      .then((status) => {
        setVersion(status.current_frago_version || null);
        setResourceVersion(status.resources_version || null);
      })
      .catch(() => {
        setVersion(null);
        setResourceVersion(null);
      });
  }, []);

  const shortVersion = version ? `v${version.split('+')[0]}` : null;

  return (
    <div className="about-stack">
      <div className="s-card">
        <div className="hd">
          <span className="ico">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </span>
          <div>
            <div className="nm">frago</div>
            <div className="ds">{t('settings.about.description')}</div>
          </div>
          <span className="s-pill mono">
            {shortVersion ?? t('settings.about.pillVersionUnknown')}
          </span>
        </div>

        <div className="bd">
          <div className="kvgrid">
            <div className="k">{t('settings.about.runningVersion')}</div>
            <div
              className="v mono"
              style={!version ? { color: 'var(--text-muted)' } : undefined}
            >
              {version ?? t('settings.about.versionUnknown')}
            </div>

            <div className="k">{t('settings.about.resourcePack')}</div>
            <div className="v mono">{resourceVersion ?? '—'}</div>

            <div className="k">{t('settings.about.dataDirectory')}</div>
            <div className="v mono">~/.frago/data</div>

            <div className="k">{t('settings.about.licenseLabel')}</div>
            <div className="v">{t('settings.about.licenseValue')}</div>
          </div>
        </div>
      </div>

      {/* 合规署名专卡：Avatar Illustration System by Micah Lanier (CC BY 4.0) & DiceBear (MIT) */}
      <div className="s-card" data-testid="settings-avatar-attribution">
        <div className="hd">
          <span className="ico">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
            </svg>
          </span>
          <div>
            <div className="nm">{t('settings.about.avatarAttrTitle')}</div>
            <div className="ds">{t('settings.about.avatarAttrSubtitle')}</div>
          </div>
          <span className="s-pill mono">CC BY 4.0 · MIT</span>
        </div>

        <div className="bd">
          <div className="kvgrid">
            <div className="k">{t('settings.about.avatarArtworkLabel')}</div>
            <div className="v">
              <strong>Avatar Illustration System by Micah Lanier (CC BY 4.0)</strong>
              <span className="about-attr-sub">
                {' '}— Creative Commons Attribution 4.0 International
              </span>
            </div>

            <div className="k">{t('settings.about.avatarEngineLabel')}</div>
            <div className="v">
              <strong>DiceBear (MIT)</strong>
              <span className="about-attr-sub mono">
                {' '}· @dicebear/core &amp; @dicebear/micah (offline bundled)
              </span>
            </div>

            <div className="k">{t('settings.about.avatarCustomLabel')}</div>
            <div className="v">{t('settings.about.avatarCustomNote')}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
