import { useAppStore } from '@/stores/appStore';
import type { Theme } from '@/types/pywebview.d';

export default function Header() {
  const { config, setTheme } = useAppStore();

  const toggleTheme = () => {
    const newTheme: Theme = config?.theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
  };

  return (
    <header className="header">
      <div className="header-left">
        <span className="logo">
          frago
        </span>
      </div>
      <div className="header-right">
        <button
          className="btn btn-ghost"
          onClick={toggleTheme}
          title={config?.theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'}
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          {config?.theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </div>
    </header>
  );
}
