/**
 * General Settings Component
 * Main configuration: API endpoint, working directory
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getMainConfig, getProfiles, getConnections, getActivationTargets, deactivateProfile, checkVSCode, openConfigInVSCode } from '@/api';
import type { ProfileItem, RoleBinding } from '@/api';
import type { MainConfig } from '@/types/pywebview';
import { Code, AlertTriangle, Shield, Check, RefreshCw } from 'lucide-react';
import ProfileManager from '@/components/settings/ProfileManager';
import ConnectionRolesCard from '@/components/settings/ConnectionRolesCard';
import ActiveProfileCard from '@/components/settings/ActiveProfileCard';
import DecisionModelCard from '@/components/settings/DecisionModelCard';
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
  // Everything the two role rows need: the bindable connections (subscription
  // included) and what each role is on right now.
  const [connections, setConnections] = useState<ProfileItem[]>([]);
  const [bindings, setBindings] = useState<RoleBinding[]>([]);
  // agent_type → display name, shared by the role rows and the "written into"
  // line, so neither can print a bare key like "agy".
  const [coreNames, setCoreNames] = useState<Record<string, string>>({});
  const [activeProfileId, setActiveProfileId] = useState<string | null>(null);
  // Which agent CLIs the active profile was written into, already resolved to
  // display names. "Active" used to say nothing about who it affected.
  const [activeTargetNames, setActiveTargetNames] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [vscodeInstalled, setVscodeInstalled] = useState(false);
  const [showProfileManager, setShowProfileManager] = useState(false);
  const [initialPickTargetId, setInitialPickTargetId] = useState<string | null>(null);
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
      const [configData, profileData, connectionData, targetData] = await Promise.all([
        getMainConfig(),
        getProfiles(),
        getConnections().catch(() => ({ connections: [], bindings: [], vendor_cores: [] })),
        // Names come from the backend roster so the card cannot drift from what
        // the picker offered.
        getActivationTargets().catch(() => ({ targets: [], default_targets: [] }))
      ]);

      setConfig(configData);
      setProfiles(profileData.profiles);
      setActiveProfileId(profileData.active_profile_id);
      setConnections(connectionData.connections);
      setBindings(connectionData.bindings);
      // Both rosters name cores, and neither one alone covers them all: the
      // activation targets are the CLIs frago can write into, the vendor cores
      // are the ones it cannot.
      const names: Record<string, string> = {};
      for (const core of connectionData.vendor_cores) names[core.agent_type] = core.display_name;
      for (const target of targetData.targets) names[target.agent_type] = target.display_name;
      setCoreNames(names);
      const displayNames = new Map(targetData.targets.map((target) => [target.agent_type, target.display_name]));
      setActiveTargetNames((profileData.active_targets ?? []).map((agentType) => displayNames.get(agentType) ?? agentType));

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
    <div className="space-y-3">
      {error && (
        <div className="salert err">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Which connection each role runs on. */}
      <ConnectionRolesCard
        connections={connections}
        bindings={bindings}
        coreNames={coreNames}
        profileCount={profiles.length}
        onManageProfiles={() => {
          setInitialPickTargetId(null);
          setShowProfileManager(true);
        }}
        onBindingChanged={() => loadData()}
      />

      {/* Active Profile Card or Official API Card */}
      {activeProfile ? (
        <ActiveProfileCard
          profile={activeProfile}
          activeTargets={activeTargetNames}
          onChangeTargets={() => {
            setInitialPickTargetId(activeProfile.id);
            setShowProfileManager(true);
          }}
          onSwitch={() => {
            setInitialPickTargetId(null);
            setShowProfileManager(true);
          }}
          onDeactivate={handleDeactivate}
        />
      ) : (
        <div className="s-card">
          <div className="hd">
            <span className="ico">
              <Shield size={15} />
            </span>
            <div>
              <div className="nm">{t('settings.general.officialApi')}</div>
              <div className="ds">{t('settings.general.officialApiDesc')}</div>
            </div>
            <span className="s-pill">
              <Check size={12} />
              {t('settings.profiles.active')}
            </span>
          </div>
          <div className="row full">
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {t('settings.general.savedProfilesReady', { total: profiles.length })}
            </div>
            <button
              type="button"
              onClick={() => {
                setInitialPickTargetId(null);
                setShowProfileManager(true);
              }}
              className="btn btn-sm ml-auto"
            >
              <RefreshCw size={13} />
              {t('settings.profiles.switchProfile')}
            </button>
          </div>
        </div>
      )}

      {/* Decision Model Configuration */}
      <DecisionModelCard />

      {/* Claude Code settings file — set apart as a danger zone rather than
          shown as one more ordinary card. frago registers its hook events into
          this file by merge-write; a hand edit that breaks the JSON stops
          Claude Code from starting and takes frago's hooks down with it. The
          red frame is the whole point: an ordinary card invited people to
          poke at it. */}
      {vscodeInstalled && (
        <section className="danger-zone">
          <div className="danger-zone-header">
            <AlertTriangle size={14} aria-hidden="true" />
            {t('settings.general.dangerZone')}
          </div>
          <div className="danger-zone-body">
            <div className="danger-zone-row">
              <div className="danger-zone-text">
                <p className="danger-zone-title">{t('settings.general.claudeSettingsFile')}</p>
                <p className="danger-zone-desc">{t('settings.general.claudeSettingsFileDesc')}</p>
                <p className="danger-zone-warning">{t('settings.general.claudeSettingsFileWarning')}</p>
              </div>
              <button
                type="button"
                onClick={handleOpenInVSCode}
                className="btn btn-sm btn-danger-outline shrink-0"
                title={t('settings.general.openInVSCode')}
              >
                <Code size={16} />
                {t('settings.general.edit')}
              </button>
            </div>
            <div className="danger-zone-path">~/.claude/settings.json</div>
          </div>
        </section>
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

      {/* Profile Manager Modal.
          hasCustomConfig unlocks "save the running configuration as a
          profile" — the button existed all along but nothing ever told the
          dialog a custom endpoint was in use, so it never appeared. */}
      <ProfileManager
        isOpen={showProfileManager}
        onClose={() => {
          setShowProfileManager(false);
          setInitialPickTargetId(null);
        }}
        onProfilesChanged={() => loadData()}
        hasCustomConfig={config.auth_method === 'custom'}
        initialPickTargetId={initialPickTargetId}
      />
    </div>
  );
}
