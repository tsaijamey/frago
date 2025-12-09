import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady } from '@/api/pywebview';

/**
 * 配置 Hook
 *
 * 自动加载配置并监听 pywebview 就绪事件
 */
export function useConfig() {
  const { config, loadConfig, updateConfig, setTheme } = useAppStore();

  useEffect(() => {
    if (isApiReady()) {
      loadConfig();
    } else {
      const handleReady = () => {
        loadConfig();
      };
      window.addEventListener('pywebviewready', handleReady);
      return () => window.removeEventListener('pywebviewready', handleReady);
    }
  }, [loadConfig]);

  return {
    config,
    updateConfig,
    setTheme,
    isLoaded: config !== null,
  };
}
