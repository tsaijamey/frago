/**
 * General Settings Component
 * Main configuration: API endpoint, working directory
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getMainConfig, getProfiles, deactivateProfile, openWorkingDirectory, checkVSCode, openConfigInVSCode } from '@/api';
import type { ProfileItem } from '@/api';
import type { MainConfig } from '@/types/pywebview';
import { FolderOpen, Code } from 'lucide-react';
import ProfileManager from '@/components/settings/ProfileManager';
import AuthStatusCard from '@/components/settings/AuthStatusCard';
import ActiveProfileCard from '@/components/settings/ActiveProfileCard';
import Modal from '@/components/ui/Modal';

interface GeneralSettingsProps {
  /**
   * Incremented by the capability panel when the user clicks through to
   * configure a model. Landing on this panel is not enough — the profile
   * editor is behind a dialog, so arriving without it open would drop the
   * user one step short of where they asked to go.
   */
  openProfilesSignal?: number;
}

export default function GeneralSettings({ openProfilesSignal = 0 }: GeneralSettingsProps = {}) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<MainConfig | null>(null);
  const [profiles, setProfiles] = useState<ProfileItem[]>([]);
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [vscodeInstalled, setVscodeInstalled] = useState(false);
  const [showProfileManager, setShowProfileManager] = useState(false);
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 0 is the initial value, i.e. "nobody asked" — only a bump opens the dialog.
  useEffect(() => {
    if (openProfilesSignal > 0) {
      setShowProfileManager(true);
    }
  }, [openProfilesSignal]);

  const loadData = async () => {
    try {
      setLoading(true);
      const [configData, profileData] = await Promise.all([
        getMainConfig(),
        getProfiles()
      ]);

      setConfig(configData);
      setProfiles(profileData.profiles);
      setActiveProfileId(profileData.active_profile_id);

      // Check VSCode availability
      try {
        const vscodeStatus = await checkVSCode();
        setVscodeInstalled(vscodeStatus.available);
      } catch {
        setVscodeInstalled(false);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToLoadConfig'));
    } finally {
      setLoading(false);
    }
  };

  const handleDeactivate = () => {
    setShowConfirmDialog(true);
  };

  const confirmDeactivate = async () => {
    try {
      const result = await deactivateProfile();
      if (result.status === 'ok') {
        setShowConfirmDialog(false);
        await loadData();
      } else {
        setError(result.error || t('errors.deactivateFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('errors.deactivateFailed'));
    }
  };

  const handleOpenWorkingDirectory = async () => {
    try {
      const result = await openWorkingDirectory();
      if (result.status === 'error') {
        setError(result.error || t('settings.general.failedToOpenDir'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToOpenDir'));
    }
  };

  const handleOpenInVSCode = async () => {
    try {
      const result = await openConfigInVSCode();
      if (result.status === 'error') {
        setError(result.error || t('settings.general.failedToOpenVSCode'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.general.failedToOpenVSCode'));
    }
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

  const activeProfile = activeProfileId ? profiles.find(p => p.id === activeProfileId) : null;

  return (
    <div className="space-y-4">
      {error && (
        <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
          <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
        </div>
      )}

      {/* Authentication Status Card */}
      <AuthStatusCard
        authMethod={config.auth_method}
        apiEndpoint={config.api_endpoint}
        onManageProfiles={() => setShowProfileManager(true)}
      />

      {/* Active Profile Card */}
      {activeProfile && (
        <ActiveProfileCard
          profile={activeProfile}
          onSwitch={() => setShowProfileManager(true)}
          onDeactivate={handleDeactivate}
        />
      )}

      {/* Working Directory Card */}
      <div className="bg-[var(--bg-card)] rounded-lg border border-[var(--border-color)] p-4">
        <div className="mb-3">
          <label className="text-sm font-medium text-[var(--text-primary)]">
            {t('settings.general.workingDirectory')}
          </label>
        </div>

        <div className="flex gap-2 items-center">
          <div className="flex-1 bg-[var(--bg-subtle)] rounded-md px-3 py-2 overflow-x-auto">
            <span className="text-[var(--text-secondary)] font-mono text-sm whitespace-nowrap">
              {config.working_directory_display || '~/.frago/projects'}
            </span>
          </div>
          <button
            type="button"
            onClick={handleOpenWorkingDirectory}
            className="btn btn-ghost btn-sm flex items-center gap-1 shrink-0"
            title={t('settings.general.openInFileManager')}
          >
            <FolderOpen size={16} />
            {t('settings.general.open')}
          </button>
        </div>
      </div>

      {/* Claude Code settings file — its own card.
          This edit button used to live in the working-directory card above,
          where it read as "edit the working directory". It edits neither that
          directory nor anything of frago's: it opens Claude Code's own settings
          file, which is a separate subject and now says so. */}
      {vscodeInstalled && (
        <div className="bg-[var(--bg-card)] rounded-lg border border-[var(--border-color)] p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <label className="text-sm font-medium text-[var(--text-primary)]">
                {t('settings.general.claudeSettingsFile')}
              </label>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                {t('settings.general.claudeSettingsFileDesc')}
              </p>
            </div>
            <button
              type="button"
              onClick={handleOpenInVSCode}
              className="btn btn-ghost btn-sm flex items-center gap-1 shrink-0"
              title={t('settings.general.openInVSCode')}
            >
              <Code size={16} />
              {t('settings.general.edit')}
            </button>
          </div>
          <div className="bg-[var(--bg-subtle)] rounded-md px-3 py-2 overflow-x-auto">
            <span className="text-[var(--text-secondary)] font-mono text-sm whitespace-nowrap">
              ~/.claude/settings.json
            </span>
          </div>
        </div>
      )}

      {/* Deactivate Confirmation Dialog */}
      <Modal
        isOpen={showConfirmDialog}
        onClose={() => setShowConfirmDialog(false)}
        title={t('settings.profiles.confirmDeactivate')}
        footer={
          <>
            <button
              type="button"
              onClick={() => setShowConfirmDialog(false)}
              className="btn btn-ghost"
            >
              {t('settings.general.cancel')}
            </button>
            <button
              type="button"
              onClick={confirmDeactivate}
              className="btn btn-primary"
            >
              {t('settings.profiles.deactivate')}
            </button>
          </>
        }
      >
        <p className="text-sm text-[var(--text-secondary)]">
          {t('settings.profiles.confirmDeactivateDesc')}
        </p>
      </Modal>

      {/* Profile Manager Modal */}
      <ProfileManager
        isOpen={showProfileManager}
        onClose={() => setShowProfileManager(false)}
        onProfileActivated={() => loadData()}
      />
    </div>
  );
}
