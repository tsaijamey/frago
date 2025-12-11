import { useAppStore, type PageType } from '@/stores/appStore';
import { Lightbulb, ListTodo, BookOpen, Zap, Settings } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

const tabs: { id: PageType; label: string; icon: LucideIcon }[] = [
  { id: 'tips', label: 'Tips', icon: Lightbulb },
  { id: 'tasks', label: 'Tasks', icon: ListTodo },
  { id: 'recipes', label: 'Recipes', icon: BookOpen },
  { id: 'skills', label: 'Skills', icon: Zap },
  { id: 'settings', label: 'Settings', icon: Settings },
];

export default function BottomNav() {
  const { currentPage, switchPage } = useAppStore();

  // 判断当前页面属于哪个 tab
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
