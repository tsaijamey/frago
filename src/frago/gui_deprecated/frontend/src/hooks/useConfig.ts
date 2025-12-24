import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady } from '@/api';

/**
 * Config Hook
 *
 * Automatically load config and listen to pywebview ready events
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
