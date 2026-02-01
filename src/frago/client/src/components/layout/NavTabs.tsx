import { useAppStore, type PageType } from '@/stores/appStore';
import { LayoutDashboard, ListTodo, BookOpen, Zap, Settings } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

// Note: This BottomNav is deprecated - use Sidebar instead for new admin panel layout
const tabs: { id: PageType; label: string; icon: LucideIcon }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'tasks', label: 'Tasks', icon: ListTodo },
  { id: 'recipes', label: 'Recipes', icon: BookOpen },
  { id: 'skills', label: 'Skills', icon: Zap },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export default function BottomNav() {
  const { currentPage, switchPage } = useAppStore();

  // Determine which tab the current page belongs to
  const activeTab = (() => {
    if (currentPage === 'task_detail') return 'tasks';
    if (currentPage === 'recipe_detail') return 'recipes';
    return currentPage;
  })();

  return (
    <nav className="bottom-nav">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            className={`bottom-nav-item ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => switchPage(tab.id)}
          >
            <Icon />
            <span>{tab.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
