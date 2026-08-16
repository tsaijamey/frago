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

  useEffect(() => {
    // The init status already reports the running version, so this needs no
    // endpoint of its own. A failure leaves the version simply unshown — not
    // knowing the version is no reason to break the panel.
    getInitStatus()
      .then((status) => setVersion(status.current_frago_version || null))
      .catch(() => setVersion(null));
  }, []);

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
        {t('settings.about.title')}
      </h2>

      <div className="space-y-3 text-sm text-[var(--text-muted)]">
        <p>
          <span className="font-medium text-[var(--text-primary)]">frago</span>{' '}
          {t('settings.about.tagline')}
        </p>

        <p>
          {t('settings.about.version')}:{' '}
          <span className="font-mono text-[var(--text-primary)]">
            {version ?? t('settings.about.versionUnknown')}
          </span>
        </p>

        <p className="pt-2 border-t border-[var(--border-color)]">
          {t('settings.about.license')}
        </p>
      </div>
    </div>
  );
}
