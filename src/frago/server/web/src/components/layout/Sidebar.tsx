/**
 * Collapsible Sidebar Component
 *
 * Professional dark-themed admin panel sidebar with:
 * - 5 menu items: Dashboard, Tasks, Recipes, Skills, Settings
 * - Collapse/expand functionality with localStorage persistence
 * - Responsive breakpoints for narrow viewports
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type PageType } from '@/stores/appStore';
import { Sun, Moon } from 'lucide-react';

// Menu item configuration
interface MenuItem {
  id: PageType;
  labelKey: string; // Translation key for the label
  icon: JSX.Element;
}

// Icons for menu items (inline SVG for simplicity)
const DashboardIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="3" width="7" height="7" />
    <rect x="14" y="3" width="7" height="7" />
    <rect x="14" y="14" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" />
  </svg>
);

const TasksIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </svg>
);

const RecipesIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    <line x1="8" y1="7" x2="16" y2="7" />
    <line x1="8" y1="11" x2="14" y2="11" />
  </svg>
);

const SkillsIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
);

const ConsoleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="4 17 10 11 4 5" />
    <line x1="12" y1="19" x2="20" y2="19" />
  </svg>
);

const SyncIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12a9 9 0 0 1-9 9m9-9a9 9 0 0 0-9-9m9 9H3m9 9a9 9 0 0 1-9-9m9 9c1.66 0 3-4.03 3-9s-1.34-9-3-9m0 18c-1.66 0-3-4.03-3-9s1.34-9 3-9m-9 9a9 9 0 0 1 9-9" />
  </svg>
);

const SecretsIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
  </svg>
);

const SettingsIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const WorkspaceIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
  </svg>
);

const CollapseIcon = ({ collapsed }: { collapsed: boolean }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={`collapse-icon ${collapsed ? 'collapsed' : ''}`}
  >
    <polyline points="15 18 9 12 15 6" />
  </svg>
);

// Menu items configuration
const menuItems: MenuItem[] = [
  { id: 'dashboard', labelKey: 'sidebar.dashboard', icon: <DashboardIcon /> },
  { id: 'console', labelKey: 'sidebar.console', icon: <ConsoleIcon /> },
  { id: 'tasks', labelKey: 'sidebar.tasks', icon: <TasksIcon /> },
  { id: 'recipes', labelKey: 'sidebar.recipes', icon: <RecipesIcon /> },
  { id: 'skills', labelKey: 'sidebar.skills', icon: <SkillsIcon /> },
  { id: 'workspace', labelKey: 'sidebar.workspace', icon: <WorkspaceIcon /> },
  { id: 'sync', labelKey: 'sidebar.sync', icon: <SyncIcon /> },
  { id: 'secrets', labelKey: 'sidebar.secrets', icon: <SecretsIcon /> },
  { id: 'settings', labelKey: 'sidebar.settings', icon: <SettingsIcon /> },
];

// Responsive breakpoint for auto-collapse
const NARROW_VIEWPORT_WIDTH = 768;

export default function Sidebar() {
  const { t } = useTranslation();
  const { currentPage, sidebarCollapsed, switchPage, toggleSidebar, setSidebarCollapsed, config, setTheme } = useAppStore();

  // Handle responsive behavior - auto-collapse on narrow viewports
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < NARROW_VIEWPORT_WIDTH) {
        setSidebarCollapsed(true);
      }
    };

    // Check on mount
    handleResize();

    // Listen for resize
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [setSidebarCollapsed]);

  // Determine if a menu item is active (handle detail pages)
  const isActive = (pageId: PageType): boolean => {
    if (currentPage === pageId) return true;
    if (pageId === 'tasks' && currentPage === 'task_detail') return true;
    if (pageId === 'recipes' && currentPage === 'recipe_detail') return true;
    if (pageId === 'workspace' && currentPage === 'project_detail') return true;
    return false;
  };

  return (
    <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
      {/* Logo / Header */}
      <div className="sidebar-header">
        <div className="sidebar-logo">F</div>
        {!sidebarCollapsed && <span className="sidebar-title">frago</span>}
      </div>

      {/* Navigation Menu */}
      <nav className="sidebar-nav">
        {menuItems.map((item) => {
          const active = isActive(item.id);
          const label = t(item.labelKey);
          return (
            <button
              type="button"
              key={item.id}
              onClick={() => switchPage(item.id)}
              title={sidebarCollapsed ? label : undefined}
              className={`sidebar-menu-item ${active ? 'active' : ''}`}
            >
              <span className="sidebar-menu-icon">{item.icon}</span>
              {!sidebarCollapsed && (
                <span className="sidebar-menu-label">{label}</span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Footer: Theme Toggle + Collapse Button */}
      <div className="sidebar-footer">
        <button
          type="button"
          onClick={() => setTheme(config?.theme === 'dark' ? 'light' : 'dark')}
          title={config?.theme === 'dark' ? t('sidebar.theme.switchToLight') : t('sidebar.theme.switchToDark')}
          className="sidebar-footer-btn"
        >
          {config?.theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <button
          type="button"
          onClick={toggleSidebar}
          title={sidebarCollapsed ? t('sidebar.collapse.expand') : t('sidebar.collapse.collapse')}
          className="sidebar-footer-btn"
        >
          <CollapseIcon collapsed={sidebarCollapsed} />
        </button>
      </div>
    </aside>
  );
}
