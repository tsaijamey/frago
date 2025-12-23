/**
 * Collapsible Sidebar Component
 *
 * Professional dark-themed admin panel sidebar with:
 * - 5 menu items: Dashboard, Tasks, Recipes, Skills, Settings
 * - Collapse/expand functionality with localStorage persistence
 * - Responsive breakpoints for narrow viewports
 */

import { useEffect } from 'react';
import { useAppStore, type PageType } from '@/stores/appStore';

// Menu item configuration
interface MenuItem {
  id: PageType;
  label: string;
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

const SettingsIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
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
    style={{ transform: collapsed ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }}
  >
    <polyline points="15 18 9 12 15 6" />
  </svg>
);

// Menu items configuration
const menuItems: MenuItem[] = [
  { id: 'dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
  { id: 'tasks', label: 'Tasks', icon: <TasksIcon /> },
  { id: 'recipes', label: 'Recipes', icon: <RecipesIcon /> },
  { id: 'skills', label: 'Skills', icon: <SkillsIcon /> },
  { id: 'settings', label: 'Settings', icon: <SettingsIcon /> },
];

// Responsive breakpoint for auto-collapse
const NARROW_VIEWPORT_WIDTH = 768;

export default function Sidebar() {
  const { currentPage, sidebarCollapsed, switchPage, toggleSidebar, setSidebarCollapsed } = useAppStore();

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
    return false;
  };

  return (
    <aside
      className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}
      style={{
        width: sidebarCollapsed ? 'var(--sidebar-collapsed-width)' : 'var(--sidebar-width)',
        minWidth: sidebarCollapsed ? 'var(--sidebar-collapsed-width)' : 'var(--sidebar-width)',
        height: '100%',
        background: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border-color)',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.2s ease, min-width 0.2s ease',
        overflow: 'hidden',
      }}
    >
      {/* Logo / Header */}
      <div
        style={{
          padding: sidebarCollapsed ? '16px 12px' : '16px 20px',
          borderBottom: '1px solid var(--border-color)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          minHeight: '56px',
        }}
      >
        <div
          style={{
            width: '32px',
            height: '32px',
            background: 'var(--accent-primary)',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-on-accent)',
            fontWeight: 700,
            fontSize: '14px',
            flexShrink: 0,
          }}
        >
          F
        </div>
        {!sidebarCollapsed && (
          <span
            style={{
              fontWeight: 600,
              fontSize: '16px',
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
            }}
          >
            Frago
          </span>
        )}
      </div>

      {/* Navigation Menu */}
      <nav
        style={{
          flex: 1,
          padding: '12px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}
      >
        {menuItems.map((item) => {
          const active = isActive(item.id);
          return (
            <button
              key={item.id}
              onClick={() => switchPage(item.id)}
              title={sidebarCollapsed ? item.label : undefined}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: sidebarCollapsed ? '12px' : '12px 16px',
                justifyContent: sidebarCollapsed ? 'center' : 'flex-start',
                background: active ? 'var(--bg-tertiary)' : 'transparent',
                border: 'none',
                borderRadius: '8px',
                color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                width: '100%',
              }}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.background = 'var(--bg-tertiary)';
                  e.currentTarget.style.color = 'var(--text-primary)';
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.color = 'var(--text-secondary)';
                }
              }}
            >
              <span style={{ flexShrink: 0 }}>{item.icon}</span>
              {!sidebarCollapsed && (
                <span
                  style={{
                    fontSize: '14px',
                    fontWeight: active ? 500 : 400,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {item.label}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Collapse Toggle Button */}
      <div
        style={{
          padding: '12px 8px',
          borderTop: '1px solid var(--border-color)',
        }}
      >
        <button
          onClick={toggleSidebar}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: sidebarCollapsed ? 'center' : 'flex-start',
            gap: '12px',
            padding: sidebarCollapsed ? '12px' : '12px 16px',
            width: '100%',
            background: 'transparent',
            border: 'none',
            borderRadius: '8px',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--bg-tertiary)';
            e.currentTarget.style.color = 'var(--text-secondary)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'transparent';
            e.currentTarget.style.color = 'var(--text-muted)';
          }}
        >
          <CollapseIcon collapsed={sidebarCollapsed} />
          {!sidebarCollapsed && (
            <span style={{ fontSize: '13px' }}>Collapse</span>
          )}
        </button>
      </div>
    </aside>
  );
}
