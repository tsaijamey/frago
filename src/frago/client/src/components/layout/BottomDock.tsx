/**
 * BottomDock Component
 *
 * Floating bottom navigation dock, replacing the sidebar.
 * 4 items: live | tasks | recipe || config
 */

import { Radio, LayoutGrid, Settings } from 'lucide-react';
import { useAppStore, type PageType } from '@/stores/appStore';

interface DockItem {
  id: PageType;
  label: string;
  icon: React.ReactNode;
}

const DOCK_ITEMS: DockItem[] = [
  { id: 'live', label: 'live', icon: <Radio size={20} /> },
  { id: 'recipes', label: 'recipe', icon: <LayoutGrid size={20} /> },
];

const DOCK_CONFIG: DockItem = {
  id: 'settings',
  label: 'config',
  icon: <Settings size={20} />,
};

export default function BottomDock() {
  const { currentPage, switchPage } = useAppStore();

  const isActive = (id: PageType) => {
    if (id === 'live') return currentPage === 'live';
    if (id === 'recipes') return currentPage === 'recipes' || currentPage === 'recipe_detail';
    if (id === 'settings') return currentPage === 'settings';
    return false;
  };

  return (
    <div className="bottom-dock">
      <div className="dock-items">
        {DOCK_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`dock-item ${isActive(item.id) ? 'dock-item--active' : ''}`}
            onClick={() => switchPage(item.id)}
          >
            <span className="dock-item-icon">{item.icon}</span>
            <span className="dock-item-label">{item.label}</span>
          </button>
        ))}

        <div className="dock-separator" />

        <button
          className={`dock-item ${isActive(DOCK_CONFIG.id) ? 'dock-item--active' : ''}`}
          onClick={() => switchPage(DOCK_CONFIG.id)}
        >
          <span className="dock-item-icon">{DOCK_CONFIG.icon}</span>
          <span className="dock-item-label">{DOCK_CONFIG.label}</span>
        </button>
      </div>
    </div>
  );
}
