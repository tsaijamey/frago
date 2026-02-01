// Settings component
import GeneralSettings from './GeneralSettings';
import AppearanceSettings from './AppearanceSettings';
import AboutSettings from './AboutSettings';
import { InitSettings } from './InitSettings';

interface SettingsPageProps {
  onOpenInitWizard?: () => void;
}

export default function SettingsPage({ onOpenInitWizard }: SettingsPageProps) {
  return (
    <div className="h-full overflow-auto">
      <div className="page-scroll p-4 max-w-2xl mx-auto space-y-6">
        {/* Page title */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Settings</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Configure frago features
          </p>
        </div>

        {/* Initialization status */}
        <section>
          <InitSettings onOpenWizard={onOpenInitWizard || (() => {})} />
        </section>

        {/* General configuration */}
        <section>
          <GeneralSettings />
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
