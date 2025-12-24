/**
 * Appearance Settings Component
 * Theme switching and font size adjustment
 */

import { useAppStore } from '@/stores/appStore';
import type { Theme } from '@/types/pywebview.d';
import { Moon, Sun } from 'lucide-react';

export default function AppearanceSettings() {
  const { config, updateConfig, setTheme } = useAppStore();

  if (!config) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        Loading configuration...
      </div>
    );
  }

  const handleThemeChange = (theme: Theme) => {
    setTheme(theme);
  };

  const handleFontSizeChange = (size: number) => {
    updateConfig({ font_size: size });
  };

  const handleToggle = (key: keyof typeof config, value: boolean) => {
    updateConfig({ [key]: value });
  };

  return (
    <div className="space-y-4">
      {/* Appearance settings */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          Appearance
        </h2>

        {/* Theme switch */}
        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">Theme</div>
            <div className="text-sm text-[var(--text-muted)]">
              Choose dark or light appearance
            </div>
          </div>
          <div className="flex gap-2">
            <button
              className={`btn ${
                config.theme === 'dark' ? 'btn-primary' : 'btn-ghost'
              }`}
              onClick={() => handleThemeChange('dark')}
            >
              <Moon size={16} /> Dark
            </button>
            <button
              className={`btn ${
                config.theme === 'light' ? 'btn-primary' : 'btn-ghost'
              }`}
              onClick={() => handleThemeChange('light')}
            >
              <Sun size={16} /> Light
            </button>
          </div>
        </div>

        {/* Font size */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">Font Size</div>
            <div className="text-sm text-[var(--text-muted)]">
              Adjust interface text size
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn btn-ghost"
              onClick={() =>
                handleFontSizeChange(Math.max(10, config.font_size - 1))
              }
              disabled={config.font_size <= 10}
            >
              -
            </button>
            <span className="w-8 text-center">{config.font_size}</span>
            <button
              className="btn btn-ghost"
              onClick={() =>
                handleFontSizeChange(Math.min(24, config.font_size + 1))
              }
              disabled={config.font_size >= 24}
            >
              +
            </button>
          </div>
        </div>
      </div>

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
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-success)]"></div>
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
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-success)]"></div>
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
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-success)]"></div>
          </label>
        </div>
      </div>
    </div>
  );
}
