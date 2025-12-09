import { useAppStore, type PageType } from '@/stores/appStore';

const tabs: { id: PageType; label: string }[] = [
  { id: 'tips', label: 'Tips' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'recipes', label: 'Recipes' },
  { id: 'skills', label: 'Skills' },
  { id: 'settings', label: 'Settings' },
];

export default function NavTabs() {
  const { currentPage, switchPage } = useAppStore();

  // 判断当前页面属于哪个 tab
  const activeTab = (() => {
    if (currentPage === 'task_detail') return 'tasks';
    if (currentPage === 'recipe_detail') return 'recipes';
    return currentPage;
  })();

  return (
    <nav className="nav-tabs">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`nav-tab ${activeTab === tab.id ? 'active' : ''}`}
          onClick={() => switchPage(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
