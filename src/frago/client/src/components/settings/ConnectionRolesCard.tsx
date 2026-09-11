/**
 * Connection Roles Card
 *
 * Which connection each role runs on. Four rows, in two pairs that are
 * genuinely different acts. Binding the main agent writes the connection into
 * each agent CLI's own configuration, while binding the worker is read at
 * launch and written nowhere. The light agent (the hook's review passes) and
 * the session observer (the session page's side panel) are served by
 * frago-core, which can only call a connection that carries its own key or
 * borrows the WorkBuddy login. Showing them side by side is what makes "my
 * agent stays on my subscription, my workers run somewhere else, the observer
 * runs on WorkBuddy" a thing you can see rather than a thing you have to
 * remember.
 *
 * The subscription is the first option on the two agent-CLI rows and is never
 * absent there — it is the state everything starts in and falls back to. The
 * two frago-core rows cannot use it, so they open on "unbound" instead, and
 * unbound means something different on each: the light agent keeps what it
 * always used, the observer does not run.
 *
 * Visually this is an ordinary settings row and deliberately nothing more: the
 * label and its explanation on the left, the picker on the right, the same
 * shape the language row and the capability switches already use. Three of this
 * page's standing rules bear on it — colour is reserved for states that need
 * someone to act (connections sitting where they were put need nobody, so no
 * row is tinted), every colour goes through a theme variable so the light theme
 * comes out right without a line of its own, and controls copy the class list of
 * the control they resemble rather than inventing one. The first version of
 * this card broke all three: two green dots for two ordinary rows, a colour
 * variable that does not exist, and a class name for a component the stylesheet
 * never defined, which is why the picker rendered as a bare browser-default
 * dropdown.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Layers } from 'lucide-react';
import { bindRole } from '@/api';
import type { ConnectionRole, ProfileItem, RoleBinding } from '@/api';

interface ConnectionRolesCardProps {
  connections: ProfileItem[];
  bindings: RoleBinding[];
  /** agent_type → display name, so the rows read "CodeBuddy Code", not "codebuddy". */
  coreNames: Record<string, string>;
  onManageProfiles: () => void;
  /** Reload after a binding lands: every row and the cards below read this data. */
  onBindingChanged: () => void;
}

const ROLE_ORDER: ConnectionRole[] = ['main', 'worker', 'lightagent', 'observer'];

/** The two roles frago-core asks the model for. */
const FRAGO_CORE_ROLES: ReadonlySet<ConnectionRole> = new Set<ConnectionRole>([
  'lightagent',
  'observer',
]);

const ROLE_TEXT: Record<ConnectionRole, { name: string; hint: string }> = {
  main: { name: 'settings.connections.mainRole', hint: 'settings.connections.mainRoleHint' },
  worker: { name: 'settings.connections.workerRole', hint: 'settings.connections.workerRoleHint' },
  lightagent: {
    name: 'settings.connections.lightagentRole',
    hint: 'settings.connections.lightagentRoleHint',
  },
  observer: {
    name: 'settings.connections.observerRole',
    hint: 'settings.connections.observerRoleHint',
  },
};

export default function ConnectionRolesCard({
  connections,
  bindings,
  coreNames,
  onManageProfiles,
  onBindingChanged,
}: ConnectionRolesCardProps) {
  const { t } = useTranslation();
  const [busyRole, setBusyRole] = useState<ConnectionRole | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleBind = async (role: ConnectionRole, profileId: string) => {
    setBusyRole(role);
    setError(null);
    try {
      const result = await bindRole(role, profileId);
      if (result.status === 'ok') {
        onBindingChanged();
      } else {
        // The backend's refusals are written to be read (a vendor CLI on main
        // says why it cannot go there), so they are shown as-is.
        setError(result.error || t('settings.connections.bindFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.connections.bindFailed'));
    } finally {
      setBusyRole(null);
    }
  };

  const label = (connection: ProfileItem) => {
    if (connection.kind === 'official') return t('settings.connections.officialName');
    if (connection.kind === 'workbuddy') return `${connection.name} · WorkBuddy`;
    const core = connection.agent_type ? coreNames[connection.agent_type] ?? connection.agent_type : null;
    return core ? `${connection.name} · ${core}` : connection.name;
  };

  /**
   * Why this connection cannot serve this role; null when it can. Listed and
   * disabled with the reason — an option that is simply gone reads as a bug.
   */
  const blockedReason = (role: ConnectionRole, connection: ProfileItem): string | null => {
    if (FRAGO_CORE_ROLES.has(role)) {
      // frago-core can call a key or the borrowed WorkBuddy login, and nothing
      // else; a vendor CLI's credential is that CLI's own login.
      return connection.kind === 'vendor_cli' ? t('settings.connections.notForFragoCore') : null;
    }
    // A borrowed WorkBuddy login has no agent CLI configuration to go into.
    if (connection.kind === 'workbuddy') return t('settings.connections.fragoCoreOnly');
    // A vendor CLI cannot serve the main role: frago holds no key to write into
    // another CLI's config for it.
    if (role === 'main' && connection.kind === 'vendor_cli') {
      return t('settings.connections.vendorNotForMain');
    }
    return null;
  };

  /** What this row is running on, in one line under the picker. */
  const detail = (binding: RoleBinding) => {
    const { connection } = binding;
    if (!connection) return null;
    if (binding.role === 'main' && binding.targets.length > 0) {
      const names = binding.targets.map((target) => coreNames[target] ?? target).join(', ');
      return `${t('settings.connections.writtenInto')}: ${names}`;
    }
    if (FRAGO_CORE_ROLES.has(binding.role)) {
      // frago-core asks the cheap tier, and the default model when there is none.
      const model = connection.haiku_model || connection.default_model || null;
      const how = connection.kind === 'workbuddy' ? t('settings.connections.borrowedLogin') : null;
      const tail = [model, how].filter(Boolean).join(' · ');
      if (binding.profile_id === null) {
        const head = t('settings.connections.followingDefault', { name: connection.name });
        return tail ? `${head} · ${tail}` : head;
      }
      return tail || null;
    }
    if (connection.agent_type) {
      const core = coreNames[connection.agent_type] ?? connection.agent_type;
      return connection.default_model
        ? `${connection.default_model} ${t('settings.connections.onCore')} ${core}`
        : core;
    }
    return connection.default_model ?? null;
  };

  return (
    <div className="bg-[var(--bg-card)] rounded-lg border border-[var(--border-color)] p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
        {t('settings.connections.title')}
      </h3>

      {/* One row per role: what it is on the left, the picker on the right —
          the shape every other settings row on this page already has. Nothing
          here carries an accent colour: every row is simply the state things
          are in, and the page reserves colour for the states that need someone
          to act. */}
      <div className="mb-4">
        {ROLE_ORDER.map((role, index) => {
          const binding = bindings.find((b) => b.role === role);
          if (!binding) return null;
          const fragoCore = FRAGO_CORE_ROLES.has(role);
          const rowDetail = detail(binding);
          const roleName = t(ROLE_TEXT[role].name);
          // The frago-core rows have no subscription to show; their empty value
          // is "unbound", and picking it unbinds.
          const value = fragoCore ? (binding.profile_id ?? '') : (binding.profile_id ?? 'official');
          const options = fragoCore ? connections.filter((c) => c.kind !== 'official') : connections;

          return (
            <div
              key={role}
              className={`flex items-center justify-between gap-4 py-2 ${
                index > 0 ? 'border-t border-[var(--border-color)] pt-3 mt-1' : ''
              }`}
            >
              <div className="min-w-0">
                <div className="text-sm text-[var(--text-primary)]">{roleName}</div>
                <div className="text-xs text-[var(--text-secondary)] mt-0.5">
                  {t(ROLE_TEXT[role].hint)}
                </div>
                {rowDetail && (
                  <div className="text-xs text-[var(--text-muted)] mt-0.5">{rowDetail}</div>
                )}
                {busyRole === role && (
                  <div className="text-xs text-[var(--text-muted)] mt-0.5">
                    {t('settings.connections.switching')}
                  </div>
                )}
              </div>
              <select
                className="shrink-0 max-w-[50%] px-3 py-1.5 rounded-md bg-[var(--bg-subtle)] border border-[var(--border-color)] text-[var(--text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]"
                value={value}
                disabled={busyRole !== null}
                onChange={(e) => handleBind(role, e.target.value)}
                aria-label={roleName}
              >
                {fragoCore && (
                  <option value="">
                    {role === 'lightagent'
                      ? t('settings.connections.followDefault')
                      : t('settings.connections.observerOff')}
                  </option>
                )}
                {options.map((connection) => {
                  const blocked = blockedReason(role, connection);
                  return (
                    <option key={connection.id} value={connection.id} disabled={blocked !== null}>
                      {label(connection)}
                      {blocked ? ` — ${blocked}` : ''}
                    </option>
                  );
                })}
              </select>
            </div>
          );
        })}
      </div>

      {error && (
        <p className="text-xs text-[var(--accent-error)] mb-3">{error}</p>
      )}

      <button
        type="button"
        onClick={onManageProfiles}
        className="btn btn-ghost btn-sm flex items-center gap-1"
      >
        <Layers size={16} />
        {t('settings.general.manageProfiles')}
      </button>
    </div>
  );
}
