import { useCallback, useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady, getApiMode, waitForApi } from '@/api';
import { getInitStatus } from '@/api/client';
import { RECONNECTED_EVENT, useConnectionStore } from '@/api/connection';
import { useDataSync } from '@/hooks/useDataSync';
import { useHashRoute } from '@/hooks/useHashRoute';
import { useRecipeAppOpen } from '@/hooks/useRecipeAppOpen';
import { FILE_PINS_SYNC_TICK_KEY, useFilePins } from '@/stores/filePins';
import { RECIPE_APP_PINS_SYNC_TICK_KEY, useRecipeAppPins } from '@/stores/recipeAppPins';

// Layout - New admin panel layout with sidebar
import MainLayout from '@/components/layout/MainLayout';
import PageHost from '@/components/layout/PageHost';

// UI
import { ToastContainer } from '@/components/ui/Toast';
import ReconnectOverlay from '@/components/ui/ReconnectOverlay';

// Init wizard
import { InitWizardPage } from '@/components/init';

function App() {
  const { loadConfig } = useAppStore();
  const [apiReady, setApiReady] = useState(isApiReady());
  const [initCompleted, setInitCompleted] = useState<boolean | null>(null);
  const reachable = useConnectionStore((state) => state.reachable);

  // 首屏加载屏等首屏初始化落定或断连遮罩接管后再撤，避免服务缓慢时露出黑底空窗。
  useEffect(() => {
    const readyToReveal =
      initCompleted !== null || !reachable || (getApiMode() !== 'http' && apiReady);
    if (!readyToReveal) return;
    const hide = (window as unknown as { fragoHideLoading?: () => void }).fragoHideLoading;
    if (typeof hide === 'function') {
      hide();
    }
  }, [initCompleted, reachable, apiReady]);

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
      void useFilePins.getState().load();
      void useRecipeAppPins.getState().load();

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

  useEffect(() => {
    if (getApiMode() !== 'http') return;
    const syncAll = () => {
      void useFilePins.getState().load();
      void useRecipeAppPins.getState().load();
    };
    const onVisibility = () => {
      if (!document.hidden) syncAll();
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === FILE_PINS_SYNC_TICK_KEY) {
        void useFilePins.getState().load();
      } else if (e.key === RECIPE_APP_PINS_SYNC_TICK_KEY) {
        void useRecipeAppPins.getState().load();
      }
    };
    window.addEventListener('focus', syncAll);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('storage', onStorage);
    window.addEventListener(RECONNECTED_EVENT, syncAll);
    return () => {
      window.removeEventListener('focus', syncAll);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(RECONNECTED_EVENT, syncAll);
    };
  }, []);

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
        <ToastContainer />
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

      <ToastContainer />

      {/* 本机服务不在时盖住整页——放在最后，保证盖在弹窗与 toast 之上 */}
      <ReconnectOverlay />
    </>
  );
}

export default App;
