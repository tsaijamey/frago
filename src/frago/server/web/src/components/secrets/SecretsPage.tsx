/**
 * Secrets Page Component
 * Standalone page for environment variables configuration
 */

import SecretsSettings from '@/components/settings/SecretsSettings';

// Shield icon for security notice
const ShieldIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0">
    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
  </svg>
);

export default function SecretsPage() {
  return (
    <div className="h-full overflow-auto">
      <div className="page-scroll p-4 max-w-2xl mx-auto space-y-6">
        {/* Page title */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Secrets</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Manage environment variables for recipes and integrations
          </p>
        </div>

        {/* Security notice */}
        <div className="flex gap-3 p-4 rounded-lg border border-[var(--border-color)] bg-[var(--bg-tertiary)]">
          <div className="text-[var(--accent-primary)] mt-0.5">
            <ShieldIcon />
          </div>
          <div className="text-sm text-[var(--text-secondary)] leading-relaxed">
            <p>
              Your secrets are stored locally on this device and never leave your machine.
              They are accessed only by recipes you run — frago does not manage or transmit them.
              By default, secrets are excluded from sync even if you have configured a private repository.
            </p>
          </div>
        </div>

        {/* Secrets settings content */}
        <section>
          <SecretsSettings />
        </section>
      </div>
    </div>
  );
}
