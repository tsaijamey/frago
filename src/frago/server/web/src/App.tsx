import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady, getApiMode, waitForApi } from '@/api';

// Layout - New admin panel layout with sidebar
import MainLayout from '@/components/layout/MainLayout';

// Pages
import DashboardPage from '@/components/dashboard/DashboardPage';
import TaskList from '@/components/tasks/TaskList';
import TaskDetail from '@/components/tasks/TaskDetail';
import RecipeList from '@/components/recipes/RecipeList';
import RecipeDetail from '@/components/recipes/RecipeDetail';
import SkillList from '@/components/skills/SkillList';
import SyncPage from '@/components/sync/SyncPage';
import SecretsPage from '@/components/secrets/SecretsPage';
import SettingsPage from '@/components/settings/SettingsPage';

// UI
import Toast from '@/components/ui/Toast';

function App() {
  const { currentPage, loadConfig, toasts } = useAppStore();
  const [apiReady, setApiReady] = useState(isApiReady());

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

  // Debug info
  useEffect(() => {
    console.log('App mounted, apiReady:', apiReady);
  }, [apiReady]);

  // Render content based on current page
  // Default page is 'tasks' per spec (set in appStore)
  const renderPage = () => {
    switch (currentPage) {
      case 'dashboard':
        return <DashboardPage />;
      case 'tasks':
        return <TaskList />;
      case 'task_detail':
        return <TaskDetail />;
      case 'recipes':
        return <RecipeList />;
      case 'recipe_detail':
        return <RecipeDetail />;
      case 'skills':
        return <SkillList />;
      case 'sync':
        return <SyncPage />;
      case 'secrets':
        return <SecretsPage />;
      case 'settings':
        return <SettingsPage />;
      default:
        return <TaskList />;
    }
  };

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
