/**
 * About Settings Component
 * Display Frago version information and technology stack
 */

export default function AboutSettings() {
  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-[var(--accent-primary)] mb-4">
        About
      </h2>

      <div className="space-y-4 text-sm text-[var(--text-secondary)]">
        <div>
          <h3 className="font-medium text-[var(--text-primary)] mb-2">
            Frago
          </h3>
          <p className="text-[var(--text-muted)]">
            AI-powered multi-runtime automation framework
          </p>
        </div>

        <div className="border-t border-[var(--border-color)] pt-4">
          <h3 className="font-medium text-[var(--text-primary)] mb-2">
            Technology Stack
          </h3>
          <ul className="space-y-1 text-[var(--text-muted)]">
            <li>• Frontend: React + TypeScript + TailwindCSS + Vite</li>
            <li>• Backend: Python + pywebview + Pydantic</li>
            <li>• Automation: Chrome CDP + Websocket</li>
          </ul>
        </div>

        <div className="border-t border-[var(--border-color)] pt-4">
          <p className="text-[var(--text-muted)]">
            © 2024 Frago. All rights reserved.
          </p>
        </div>
      </div>
    </div>
  );
}
