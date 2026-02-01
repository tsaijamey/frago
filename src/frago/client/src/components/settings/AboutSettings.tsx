/**
 * About Settings Component
 * Display Frago version information
 */

export default function AboutSettings() {
  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
        About
      </h2>

      <div className="space-y-3 text-sm text-[var(--text-muted)]">
        <p>
          <span className="font-medium text-[var(--text-primary)]">frago</span> is a multi-runtime infrastructure framework for AI Agents.
        </p>
        <p className="pt-2 border-t border-[var(--border-color)]">
          © 2025 frago · AGPL-3.0
        </p>
      </div>
    </div>
  );
}
