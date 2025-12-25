/**
 * Appearance Settings Component
 * Behavior settings for the application
 */

import { useAppStore } from '@/stores/appStore';

export default function AppearanceSettings() {
  const { config, updateConfig } = useAppStore();

  if (!config) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        Loading configuration...
      </div>
    );
  }

  const handleToggle = (key: keyof typeof config, value: boolean) => {
    updateConfig({ [key]: value });
  };

  return (
    <div className="space-y-4">
      {/* Behavior settings */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          Behavior
        </h2>

        {/* Show system status */}
        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">Show System Status</div>
            <div className="text-sm text-[var(--text-muted)]">
              Display CPU and memory usage in status bar
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.show_system_status}
              onChange={(e) =>
                handleToggle('show_system_status', e.target.checked)
              }
              className="sr-only peer"
              aria-label="Show System Status"
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>

        {/* Exit confirmation */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">Exit Confirmation</div>
            <div className="text-sm text-[var(--text-muted)]">
              Show confirmation dialog when closing window
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.confirm_on_exit}
              onChange={(e) => handleToggle('confirm_on_exit', e.target.checked)}
              className="sr-only peer"
              aria-label="Exit Confirmation"
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>

        {/* Auto scroll */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">Auto Scroll Output</div>
            <div className="text-sm text-[var(--text-muted)]">
              Automatically scroll to bottom when new content appears
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.auto_scroll_output}
              onChange={(e) =>
                handleToggle('auto_scroll_output', e.target.checked)
              }
              className="sr-only peer"
              aria-label="Auto Scroll Output"
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>
      </div>
    </div>
  );
}
