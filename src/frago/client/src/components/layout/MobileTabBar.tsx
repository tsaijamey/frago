/**
 * MobileTabBar Component
 *
 * Bottom tab bar shown only on phone-tier viewports (≤640px), where the left
 * icon rail is hidden. Labels are always visible (no hover dependency), each
 * tab is ≥44px tall, and the bar pads for the iOS home-indicator safe area.
 * Reuses the nav item definitions from Sidebar to avoid duplication.
 */

import { useAppStore } from '@/stores/appStore';
import { NAV_ITEMS, CONFIG_ITEM, isNavItemActive, type RailItem } from './Sidebar';

const TAB_ITEMS: RailItem[] = [...NAV_ITEMS, CONFIG_ITEM];

export default function MobileTabBar() {
  const { currentPage, switchPage } = useAppStore();

  return (
    <nav className="tabbar" aria-label="Primary">
      {TAB_ITEMS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`tabbar-item ${isNavItemActive(item.id, currentPage) ? 'tabbar-item--active' : ''}`}
          onClick={() => switchPage(item.id)}
        >
          <span className="tabbar-item-icon">{item.icon}</span>
          <span className="tabbar-item-label">{item.label}</span>
        </button>
      ))}
    </nav>
  );
}
