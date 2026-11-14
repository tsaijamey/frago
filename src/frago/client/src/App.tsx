import { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady, getApiMode, waitForApi } from '@/api';
import { getInitStatus } from '@/api/client';
import { RECONNECTED_EVENT } from '@/api/connection';
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

  const bootstrapHttpApp = useCallback(async () => {
    try {
      await waitForApi();
      setApiReady(true);
      await loadConfig();

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
  }, [loadConfig]);

  useEffect(() => {
    const mode = getApiMode();
    console.log('API mode:', mode);

    if (mode === 'http') {
      void bootstrapHttpApp();
      return;
    }

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
  }, [bootstrapHttpApp, loadConfig]);

  // 若首屏打开时本地服务尚未启动（initCompleted 仍为 null），待终端唤醒服务并触发
  // RECONNECTED_EVENT 后自动完成首屏初始化，无需用户手动按 F5 刷新页面。
  useEffect(() => {
    if (initCompleted !== null || getApiMode() !== 'http') return;
    const onReconnected = () => {
      void bootstrapHttpApp();
    };
    window.addEventListener(RECONNECTED_EVENT, onReconnected);
    return () => window.removeEventListener(RECONNECTED_EVENT, onReconnected);
  }, [bootstrapHttpApp, initCompleted]);

  // Handle init wizard completion
  const handleInitComplete = () => {
    setInitCompleted(true);
  };

  // Debug info
  useEffect(() => {
    console.log('App mounted, apiReady:', apiReady);
  }, [apiReady]);

  // Show init wizard page inside MainLayout if not completed (matching #setup prototype)
  if (initCompleted === false) {
    return (
      <>
        <MainLayout>
          <InitWizardPage onComplete={handleInitComplete} />
        </MainLayout>
        {toasts.length > 0 && (
          <div className="toast-container">
            {toasts.map((toast) => (
              <Toast key={toast.id} {...toast} />
            ))}
          </div>
        )}
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
        <PageHost onOpenInitWizard={() => setInitCompleted(false)} />
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
