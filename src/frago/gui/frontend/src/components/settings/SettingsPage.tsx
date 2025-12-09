import { useAppStore } from '@/stores/appStore';
import type { Theme } from '@/types/pywebview.d';

export default function SettingsPage() {
  const { config, updateConfig, setTheme } = useAppStore();

  if (!config) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        正在加载配置...
      </div>
    );
  }

  const handleThemeChange = (theme: Theme) => {
    setTheme(theme);
  };

  const handleToggle = (key: keyof typeof config, value: boolean) => {
    updateConfig({ [key]: value });
  };

  const handleFontSizeChange = (size: number) => {
    updateConfig({ font_size: size });
  };

  return (
    <div className="flex flex-col gap-4 max-w-xl">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">
        设置
      </h1>

      {/* 外观设置 */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          外观
        </h2>

        {/* 主题切换 */}
        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">主题</div>
            <div className="text-sm text-[var(--text-muted)]">
              选择深色或浅色外观
            </div>
          </div>
          <div className="flex gap-2">
            <button
              className={`btn ${
                config.theme === 'dark' ? 'btn-primary' : 'btn-ghost'
              }`}
              onClick={() => handleThemeChange('dark')}
            >
              🌙 深色
            </button>
            <button
              className={`btn ${
                config.theme === 'light' ? 'btn-primary' : 'btn-ghost'
              }`}
              onClick={() => handleThemeChange('light')}
            >
              ☀️ 浅色
            </button>
          </div>
        </div>

        {/* 字体大小 */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">字体大小</div>
            <div className="text-sm text-[var(--text-muted)]">
              调整界面文字大小
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

      {/* 行为设置 */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          行为
        </h2>

        {/* 显示系统状态 */}
        <div className="flex items-center justify-between py-2">
          <div>
            <div className="text-[var(--text-primary)]">显示系统状态</div>
            <div className="text-sm text-[var(--text-muted)]">
              在状态栏显示 CPU 和内存使用情况
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
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>

        {/* 退出确认 */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">退出确认</div>
            <div className="text-sm text-[var(--text-muted)]">
              关闭窗口时显示确认对话框
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={config.confirm_on_exit}
              onChange={(e) => handleToggle('confirm_on_exit', e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>

        {/* 自动滚动 */}
        <div className="flex items-center justify-between py-2 border-t border-[var(--border-color)]">
          <div>
            <div className="text-[var(--text-primary)]">自动滚动输出</div>
            <div className="text-sm text-[var(--text-muted)]">
              新内容时自动滚动到底部
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
            />
            <div className="w-11 h-6 bg-[var(--bg-subtle)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-[var(--accent-primary)]"></div>
          </label>
        </div>
      </div>

      {/* 关于 */}
      <div className="card">
        <h2 className="font-medium mb-4 text-[var(--accent-primary)]">
          关于
        </h2>
        <div className="text-sm text-[var(--text-secondary)]">
          <p>Frago - AI 驱动的浏览器自动化框架</p>
          <p className="mt-2 text-[var(--text-muted)]">
            前端技术栈: React + TypeScript + TailwindCSS
          </p>
        </div>
      </div>
    </div>
  );
}
