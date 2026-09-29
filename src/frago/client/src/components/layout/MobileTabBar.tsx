/**
 * MobileTabBar Component
 *
 * Bottom tab bar shown only on phone-tier viewports (≤640px), where the left
 * icon rail is hidden. Labels are always visible (no hover dependency), each
 * tab is ≥44px tall, and the bar pads for the iOS home-indicator safe area.
 * Reuses the nav item definitions from Sidebar to avoid duplication.
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { NAV_ITEMS, isNavItemActive, type RailItem } from './Sidebar';

// settings 现在就排在 NAV_ITEMS 里（跟在 data 后面），这里不再另外接一项。
// 标签跟侧栏取同一个 i18n 键，与页标题同名。
const TAB_ITEMS: RailItem[] = NAV_ITEMS;

export default function MobileTabBar() {
  const { t } = useTranslation();
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
          <span className="tabbar-item-label">{t(item.labelKey)}</span>
        </button>
      ))}
    </nav>
  );
}
