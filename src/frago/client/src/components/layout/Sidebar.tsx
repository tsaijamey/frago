/**
 * Sidebar Component
 *
 * Left icon-rail navigation. Collapsed to a 52px rail showing only icons;
 * expands into a labeled panel on hover (overlay — content does not reflow).
 * Replaces the bottom dock with a desktop-conventional left navigation.
 * Items: sessions | recipe || config, with live status pinned to the bottom.
 */

import { MessageSquare, LayoutGrid, Settings } from 'lucide-react';
import { useAppStore, type PageType } from '@/stores/appStore';

export interface RailItem {
  id: PageType;
  label: string;
  icon: React.ReactNode;
}

export const NAV_ITEMS: RailItem[] = [
  { id: 'claude_sessions', label: 'sessions', icon: <MessageSquare size={20} /> },
  { id: 'recipes', label: 'recipes', icon: <LayoutGrid size={20} /> },
];

export const CONFIG_ITEM: RailItem = {
  id: 'settings',
  label: 'config',
  icon: <Settings size={20} />,
};

export function isNavItemActive(id: PageType, currentPage: PageType): boolean {
  if (id === 'claude_sessions') return currentPage === 'claude_sessions';
  if (id === 'recipes') return currentPage === 'recipes' || currentPage === 'recipe_detail';
  if (id === 'settings') return currentPage === 'settings';
  return false;
}

export default function Sidebar() {
  const { currentPage, switchPage, systemStatus } = useAppStore();
  const isRunning = systemStatus?.cpu_percent !== undefined;

  const isActive = (id: PageType) => isNavItemActive(id, currentPage);

  const renderItem = (item: RailItem) => (
    <button
      key={item.id}
      type="button"
      className={`rail-item ${isActive(item.id) ? 'rail-item--active' : ''}`}
      onClick={() => switchPage(item.id)}
      title={item.label}
    >
      <span className="rail-item-icon">{item.icon}</span>
      <span className="rail-item-label">{item.label}</span>
    </button>
  );

  return (
    <nav className="rail" aria-label="Primary">
      <div className="rail-inner">
        <div className="rail-nav">
          {NAV_ITEMS.map(renderItem)}
        </div>

        <div className="rail-spacer" />

        <div className="rail-nav">
          {renderItem(CONFIG_ITEM)}
        </div>

        <div className="rail-status">
          <span className={`rail-status-dot ${isRunning ? 'rail-status-dot--active' : ''}`} />
          <span className="rail-item-label rail-status-label">
            {isRunning ? '运行中' : '空闲'}
          </span>
        </div>
      </div>
    </nav>
  );
}
