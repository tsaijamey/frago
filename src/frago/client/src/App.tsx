import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady, getApiMode, waitForApi } from '@/api';
import { getInitStatus } from '@/api/client';
import { useDataSync } from '@/hooks/useDataSync';
import { useHashRoute } from '@/hooks/useHashRoute';
import { useRecipeAppOpen } from '@/hooks/useRecipeAppOpen';

// Layout - New admin panel layout with sidebar
import MainLayout from '@/components/layout/MainLayout';
import PageHost from '@/components/layout/PageHost';

// UI
import Toast from '@/components/ui/Toast';
import ReconnectOverlay from '@/components/ui/ReconnectOverlay';

// Init wizard
import { InitWizardPage } from '@/components/init';

function App() {
  const { loadConfig, toasts } = useAppStore();
  const [apiReady, setApiReady] = useState(isApiReady());
  const [initCompleted, setInitCompleted] = useState<boolean | null>(null);

  // Subscribe to WebSocket data push for real-time updates
  useDataSync();

  // 地址栏 ↔ 当前页面双向对齐：刷新停在原处，后退键退得回去，链接发得出去。
  useHashRoute();

  // 配方跑完要给人看页面时，开在右侧、pin 在 recipes 下面，不再另开浏览器标签。
  useRecipeAppOpen();

  useEffect(() => {
    const initApi = async () => {
      const mode = getApiMode();
      console.log('API mode:', mode);

      if (mode === 'http') {
        // Web service mode - wait for API connection
        try {
          await waitForApi();
          setApiReady(true);
          loadConfig();

          // Check init status after API is ready
          try {
            const initStatus = await getInitStatus();
            setInitCompleted(initStatus.init_completed);
          } catch (err) {
            console.warn('Failed to check init status:', err);
            // If check fails, assume completed to avoid blocking
            setInitCompleted(true);
          }
        } catch (error) {
          console.error('Failed to connect to web service:', error);
        }
      } else {
        // pywebview mode - check if already ready
        if (isApiReady()) {
          setApiReady(true);
          loadConfig();
          return;
        }

        // Listen for pywebview ready event
        const handleReady = () => {
          console.log('pywebview ready');
          setApiReady(true);
          loadConfig();
        };

        window.addEventListener('pywebviewready', handleReady);
        return () => window.removeEventListener('pywebviewready', handleReady);
      }
    };

    initApi();
  }, [loadConfig]);

  // Handle init wizard completion
  const handleInitComplete = () => {
    setInitCompleted(true);
  };

  // Debug info
  useEffect(() => {
    console.log('App mounted, apiReady:', apiReady);
  }, [apiReady]);

  // Show init wizard page if not completed
  if (initCompleted === false) {
    return (
      <>
        <InitWizardPage onComplete={handleInitComplete} />
        <ReconnectOverlay />
      </>
    );
  }

  // Show loading while checking init status
  if (initCompleted === null) {
    return <ReconnectOverlay />; // 加载屏在 index.html 里，服务这时没起来就只有这张卡
  }

  // Show main app if init completed
  return (
    <>
      <MainLayout>
        <PageHost />
      </MainLayout>

      {/* Toast container */}
      {toasts.length > 0 && (
        <div className="toast-container">
          {toasts.map((toast) => (
            <Toast key={toast.id} {...toast} />
          ))}
        </div>
      )}

      {/* 本机服务不在时盖住整页——放在最后，保证盖在弹窗与 toast 之上 */}
      <ReconnectOverlay />
    </>
  );
}

export default App;
