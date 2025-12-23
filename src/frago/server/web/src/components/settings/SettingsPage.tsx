// Settings component
import GeneralSettings from './GeneralSettings';
import SyncSettings from './SyncSettings';
import SecretsSettings from './SecretsSettings';
import AppearanceSettings from './AppearanceSettings';
import AboutSettings from './AboutSettings';

export default function SettingsPage() {
  return (
    <div className="h-full overflow-auto">
      <div className="page-scroll p-4 max-w-2xl mx-auto space-y-6">
        {/* Page title */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Settings</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Configure Frago features
          </p>
        </div>

        {/* General configuration */}
        <section>
          <GeneralSettings />
        </section>

        {/* Multi-device sync */}
        <section>
          <SyncSettings />
        </section>

        {/* Secrets management */}
        <section>
          <SecretsSettings />
        </section>

        {/* Appearance settings */}
        <section>
          <AppearanceSettings />
        </section>

        {/* About */}
        <section>
          <AboutSettings />
        </section>
      </div>
    </div>
  );
}
