import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { isApiReady } from '@/api/pywebview';

// Layout
import BottomNav from '@/components/layout/NavTabs';
import StatusBar from '@/components/layout/StatusBar';

// Pages
import TipsPage from '@/components/tips/TipsPage';
import TaskList from '@/components/tasks/TaskList';
import TaskDetail from '@/components/tasks/TaskDetail';
import RecipeList from '@/components/recipes/RecipeList';
import RecipeDetail from '@/components/recipes/RecipeDetail';
import SkillList from '@/components/skills/SkillList';
import SettingsPage from '@/components/settings/SettingsPage';

// UI
import Toast from '@/components/ui/Toast';

function App() {
  const { currentPage, loadConfig, toasts } = useAppStore();
  const [apiReady, setApiReady] = useState(isApiReady());

  useEffect(() => {
    // 检查 API 是否已就绪
    if (isApiReady()) {
      setApiReady(true);
      loadConfig();
      return;
    }

    // 监听 pywebview 就绪事件
    const handleReady = () => {
      console.log('pywebview ready');
      setApiReady(true);
      loadConfig();
    };

    window.addEventListener('pywebviewready', handleReady);
    return () => window.removeEventListener('pywebviewready', handleReady);
  }, [loadConfig]);

  // 调试信息
  useEffect(() => {
    console.log('App mounted, apiReady:', apiReady);
  }, [apiReady]);

  // 根据当前页面渲染内容
  const renderPage = () => {
    switch (currentPage) {
      case 'tips':
        return <TipsPage />;
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
      case 'settings':
        return <SettingsPage />;
      default:
        return <TipsPage />;
    }
  };

  return (
    <>
      <main className="main-content">{renderPage()}</main>
      <BottomNav />
      <StatusBar />

      {/* Toast 容器 */}
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
