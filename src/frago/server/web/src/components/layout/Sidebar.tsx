/**
 * Collapsible Sidebar Component
 *
 * Professional dark-themed admin panel sidebar with:
 * - Primary items (Tasks, Recipes) always visible
 * - Secondary items under collapsible "More" section
 * - Collapse/expand functionality with localStorage persistence
 * - Responsive breakpoints for narrow viewports
 * - T039-T042: Simplified navigation with visited section tracking
 */

import { useEffect, useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type PageType } from '@/stores/appStore';
import { Sun, Moon, ChevronDown, ChevronRight, Wifi, WifiOff, Github } from 'lucide-react';
import { useWebSocket } from '@/hooks/useWebSocket';
import { getApiMode } from '@/api';
import StarButton from '@/components/ui/StarButton';
import PixelLogo from './PixelLogo';

// Menu item configuration
interface MenuItem {
  id: PageType;
  labelKey: string; // Translation key for the label
  icon: JSX.Element;
}

// Navigation preferences stored in localStorage
interface NavPreferences {
  moreExpanded: boolean;
  visitedSections: PageType[];
}

const NAV_PREFS_KEY = 'frago-nav-preferences';

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

// ConsoleIcon removed - Console functionality merged into Task Detail

const SyncIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12a9 9 0 0 1-9 9m9-9a9 9 0 0 0-9-9m9 9H3m9 9a9 9 0 0 1-9-9m9 9c1.66 0 3-4.03 3-9s-1.34-9-3-9m0 18c-1.66 0-3-4.03-3-9s1.34-9 3-9m-9 9a9 9 0 0 1 9-9" />
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

const GuideIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
    <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
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

// New Task icon (plus)
const NewTaskIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

// T039: Primary menu items (always visible)
const primaryMenuItems: MenuItem[] = [
  { id: 'tasks', labelKey: 'sidebar.tasks', icon: <TasksIcon /> },
  { id: 'recipes', labelKey: 'sidebar.recipes', icon: <RecipesIcon /> },
];

// T039: Secondary menu items (under "More" section)
// Note: Console removed - functionality merged into Task Detail with real-time streaming
const secondaryMenuItems: MenuItem[] = [
  { id: 'dashboard', labelKey: 'sidebar.dashboard', icon: <DashboardIcon /> },
  { id: 'skills', labelKey: 'sidebar.skills', icon: <SkillsIcon /> },
];

// Footer tool items (icon-only buttons in sidebar footer)
const footerToolItems: MenuItem[] = [
  { id: 'guide', labelKey: 'sidebar.guide', icon: <GuideIcon /> },
  { id: 'workspace', labelKey: 'sidebar.workspace', icon: <WorkspaceIcon /> },
  { id: 'sync', labelKey: 'sidebar.sync', icon: <SyncIcon /> },
  { id: 'settings', labelKey: 'sidebar.settings', icon: <SettingsIcon /> },
];

// Responsive breakpoint for auto-collapse
const NARROW_VIEWPORT_WIDTH = 768;

// T041: Load navigation preferences from localStorage
function loadNavPreferences(): NavPreferences {
  try {
    const stored = localStorage.getItem(NAV_PREFS_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch {
    // Ignore parse errors
  }
  return { moreExpanded: false, visitedSections: [] };
}

// T041: Save navigation preferences to localStorage
function saveNavPreferences(prefs: NavPreferences): void {
  try {
    localStorage.setItem(NAV_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    // Ignore storage errors
  }
}

export default function Sidebar() {
  const { t } = useTranslation();
  const { currentPage, sidebarCollapsed, switchPage, toggleSidebar, setSidebarCollapsed, config, setTheme, systemStatus, loadSystemStatus, versionInfo } = useAppStore();
  const { isConnected } = useWebSocket({ autoConnect: true });
  const apiMode = getApiMode();

  // T040, T041: More section state with localStorage persistence
  const [moreExpanded, setMoreExpanded] = useState(() => loadNavPreferences().moreExpanded);
  // T042: Track visited advanced sections
  const [visitedSections, setVisitedSections] = useState<PageType[]>(() => loadNavPreferences().visitedSections);

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

  // T041: Persist navigation preferences when they change
  useEffect(() => {
    saveNavPreferences({ moreExpanded, visitedSections });
  }, [moreExpanded, visitedSections]);

  // Load system status periodically
  useEffect(() => {
    loadSystemStatus();
    const interval = setInterval(loadSystemStatus, 15000);
    return () => clearInterval(interval);
  }, [loadSystemStatus]);

  // Determine if a menu item is active (handle detail pages)
  const isActive = (pageId: PageType): boolean => {
    if (currentPage === pageId) return true;
    if (pageId === 'tasks' && currentPage === 'task_detail') return true;
    if (pageId === 'recipes' && currentPage === 'recipe_detail') return true;
    if (pageId === 'workspace' && currentPage === 'project_detail') return true;
    return false;
  };

  // T042: Track when user visits an advanced section
  const handleNavClick = useCallback((pageId: PageType) => {
    // Track visit for secondary items (not footer items - they stay in footer)
    const isSecondary = secondaryMenuItems.some(item => item.id === pageId);
    if (isSecondary && !visitedSections.includes(pageId)) {
      setVisitedSections(prev => [...prev, pageId]);
    }
    switchPage(pageId);
  }, [visitedSections, switchPage]);

  // Check if a footer tool item is active
  const isFooterItemActive = (pageId: PageType): boolean => {
    return isActive(pageId);
  };

  // T040: Toggle More section
  const handleToggleMore = () => {
    setMoreExpanded(prev => !prev);
  };

  // T042: Check if secondary item should be "promoted" (always visible because visited)
  const isPromotedItem = (pageId: PageType): boolean => {
    return visitedSections.includes(pageId);
  };

  // T042: Get items to show in "promoted" section (visited secondary items)
  const promotedItems = secondaryMenuItems.filter(item => isPromotedItem(item.id));
  // Items remaining in More section (not visited)
  const moreItems = secondaryMenuItems.filter(item => !isPromotedItem(item.id));

  // Check if any secondary item is currently active (to auto-expand More)
  const secondaryItemActive = secondaryMenuItems.some(item => isActive(item.id));
  const effectiveMoreExpanded = moreExpanded || (secondaryItemActive && !visitedSections.includes(currentPage as PageType));

  // Render a menu item button
  const renderMenuItem = (item: MenuItem) => {
    const active = isActive(item.id);
    const label = t(item.labelKey);
    return (
      <button
        type="button"
        key={item.id}
        onClick={() => handleNavClick(item.id)}
        title={sidebarCollapsed ? label : undefined}
        className={`sidebar-menu-item ${active ? 'active' : ''}`}
      >
        <span className="sidebar-menu-icon">{item.icon}</span>
        {!sidebarCollapsed && (
          <span className="sidebar-menu-label">{label}</span>
        )}
      </button>
    );
  };

  return (
    <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
      {/* Logo / Header */}
      <div className="sidebar-header">
        {sidebarCollapsed ? (
          <span className="sidebar-logo-collapsed">F</span>
        ) : (
          <PixelLogo height={26} />
        )}
      </div>

      {/* Navigation Menu */}
      <nav className="sidebar-nav">
        {/* New Task button (like claude.ai's "New chat" - no highlight) */}
        <button
          type="button"
          onClick={() => switchPage('newTask')}
          title={sidebarCollapsed ? t('sidebar.newTask') : undefined}
          className="sidebar-menu-item sidebar-new-task"
        >
          <span className="sidebar-menu-icon"><NewTaskIcon /></span>
          {!sidebarCollapsed && (
            <span className="sidebar-menu-label">{t('sidebar.newTask')}</span>
          )}
        </button>

        {/* T039: Primary Items (always visible) */}
        {primaryMenuItems.map(renderMenuItem)}

        {/* T042: Promoted Items (visited secondary items, always visible) */}
        {promotedItems.map(renderMenuItem)}

        {/* T040: More Section (collapsible) */}
        {moreItems.length > 0 && (
          <>
            {/* More Toggle Button */}
            <button
              type="button"
              onClick={handleToggleMore}
              className="sidebar-more-toggle"
              aria-expanded={effectiveMoreExpanded ? true : false}
              aria-label={t('sidebar.more.toggle')}
              title={sidebarCollapsed ? t('sidebar.more.label') : undefined}
            >
              <span className="sidebar-more-icon">
                {effectiveMoreExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </span>
              {!sidebarCollapsed && (
                <span className="sidebar-more-label">{t('sidebar.more.label')}</span>
              )}
            </button>

            {/* More Items (collapsible) */}
            {effectiveMoreExpanded && (
              <div className="sidebar-more-content">
                {moreItems.map(renderMenuItem)}
              </div>
            )}
          </>
        )}

        {/* StarButton as last menu item */}
        <StarButton asMenuItem sidebarCollapsed={sidebarCollapsed} />
      </nav>

      {/* Status Section */}
      <div className="sidebar-status">
        {/* Server connection (only in HTTP mode) */}
        {apiMode !== 'pywebview' && (
          <div className="sidebar-status-item" title={isConnected ? t('status.connected') : t('status.disconnected')}>
            {isConnected ? (
              <Wifi size={12} className="status-icon status-on" />
            ) : (
              <WifiOff size={12} className="status-icon status-off" />
            )}
            {!sidebarCollapsed && (
              <span className={isConnected ? 'status-on' : 'status-off'}>Server</span>
            )}
          </div>
        )}
        {/* CPU/Memory (if enabled and not collapsed) */}
        {config?.show_system_status && systemStatus && !sidebarCollapsed && (
          <>
            <div className="sidebar-status-item sidebar-status-bar-item">
              <span className="sidebar-status-label">CPU</span>
              <div className="sidebar-status-bar">
                <div
                  className="sidebar-status-bar-fill"
                  style={{ width: `${Math.min(systemStatus.cpu_percent, 100)}%` }}
                />
              </div>
              <span className="sidebar-status-value">{systemStatus.cpu_percent.toFixed(0)}%</span>
            </div>
            <div className="sidebar-status-item sidebar-status-bar-item">
              <span className="sidebar-status-label">Mem</span>
              <div className="sidebar-status-bar">
                <div
                  className="sidebar-status-bar-fill"
                  style={{ width: `${Math.min(systemStatus.memory_percent, 100)}%` }}
                />
              </div>
              <span className="sidebar-status-value">{systemStatus.memory_percent.toFixed(0)}%</span>
            </div>
          </>
        )}
        {/* Chrome status */}
        <div className="sidebar-status-item" title={systemStatus?.chrome_connected ? 'Chrome Ready' : 'Chrome Off'}>
          <span className={systemStatus?.chrome_connected ? 'status-on' : ''}>
            {sidebarCollapsed ? 'C' : `Chrome: ${systemStatus?.chrome_connected ? 'On' : 'Off'}`}
          </span>
        </div>
        {/* Version with GitHub link */}
        {!sidebarCollapsed && versionInfo?.current_version && (
          <div className="sidebar-status-item sidebar-version">
            <a
              href="https://github.com/tsaijamey/frago"
              target="_blank"
              rel="noopener noreferrer"
              className="sidebar-github-link"
              title="View on GitHub"
            >
              <Github size={12} />
            </a>
            <span>v{versionInfo.current_version}</span>
          </div>
        )}
      </div>

      {/* Footer: Theme Toggle + Tool Items + Collapse Button */}
      <div className="sidebar-footer">
        {/* Theme Toggle */}
        <button
          type="button"
          onClick={() => setTheme(config?.theme === 'dark' ? 'light' : 'dark')}
          title={config?.theme === 'dark' ? t('sidebar.theme.switchToLight') : t('sidebar.theme.switchToDark')}
          className="sidebar-footer-btn"
        >
          {config?.theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        {/* Footer Tool Items */}
        {footerToolItems.map(item => (
          <button
            key={item.id}
            type="button"
            onClick={() => handleNavClick(item.id)}
            title={t(item.labelKey)}
            className={`sidebar-footer-btn ${isFooterItemActive(item.id) ? 'active' : ''}`}
          >
            <span className="sidebar-footer-icon">{item.icon}</span>
          </button>
        ))}

        {/* Collapse Button */}
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
