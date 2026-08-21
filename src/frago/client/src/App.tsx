import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady, getApiMode, waitForApi } from '@/api';
import { getInitStatus } from '@/api/client';
import { useDataSync } from '@/hooks/useDataSync';

// Layout - New admin panel layout with sidebar
import MainLayout from '@/components/layout/MainLayout';

// Pages
import SessionWorkbenchPage from '@/components/sessionWorkbench/SessionWorkbenchPage';
import RecipeList from '@/components/recipes/RecipeList';
import RecipeDetail from '@/components/recipes/RecipeDetail';
import DataRepoPage from '@/components/dataRepo/DataRepoPage';
import SkillList from '@/components/skills/SkillList';
import SettingsPage from '@/components/settings/SettingsPage';
import NewTaskPage from '@/components/newTask/NewTaskPage';
import { WorkspacePage } from '@/components/workspace';
import { GuidePage } from '@/components/guide';

// UI
import Toast from '@/components/ui/Toast';

// Init wizard
import { InitWizardPage } from '@/components/init';

function App() {
  const { currentPage, loadConfig, toasts } = useAppStore();
  const [apiReady, setApiReady] = useState(isApiReady());
  const [initCompleted, setInitCompleted] = useState<boolean | null>(null);

  // Subscribe to WebSocket data push for real-time updates
  useDataSync();

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

  // Render content based on current page
  // Default page is 'live' (timeline, set in appStore)
  const renderPage = () => {
    switch (currentPage) {
      case 'session_workbench':
        return <SessionWorkbenchPage />;
      case 'recipes':
        return <RecipeList />;
      case 'recipe_detail':
        return <RecipeDetail />;
      case 'data_repo':
        return <DataRepoPage />;
      case 'skills':
        return <SkillList />;
      case 'guide':
        return <GuidePage />;
      case 'settings':
        return <SettingsPage />;
      case 'newTask':
        return <NewTaskPage />;
      case 'workspace':
      case 'project_detail':
        return <WorkspacePage />;
      default:
        return <SessionWorkbenchPage />;
    }
  };

  // Show init wizard page if not completed
  if (initCompleted === false) {
    return <InitWizardPage onComplete={handleInitComplete} />;
  }

  // Show loading while checking init status
  if (initCompleted === null) {
    return null; // Loading handled by index.html
  }

  // Show main app if init completed
  return (
    <>
      <MainLayout>{renderPage()}</MainLayout>

      {/* Toast container */}
      {toasts.length > 0 && (
        <div className="toast-container">
          {toasts.map((toast) => (
            <Toast key={toast.id} {...toast} />
          ))}
        </div>
      )}
    </>
  );
}

export default App;
