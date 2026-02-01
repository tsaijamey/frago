/**
 * GitHub Star Button Component
 *
 * Displays a star icon that allows users to star the frago repository.
 * Hidden after user has starred (we don't want to encourage unstar).
 *
 * States:
 * - Not configured: Gray star with tooltip
 * - Not starred: Outline star, clickable
 * - Starred: Hidden (component returns null)
 * - Loading: Spinning animation
 *
 * Modes:
 * - Default (footer): Icon-only button in sidebar footer
 * - asMenuItem: Full menu item with icon and label
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Star, Loader2 } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';

interface StarButtonProps {
  /** Render as a menu item instead of footer button */
  asMenuItem?: boolean;
  /** Sidebar collapsed state (used in asMenuItem mode) */
  sidebarCollapsed?: boolean;
}

export default function StarButton({ asMenuItem = false, sidebarCollapsed = false }: StarButtonProps) {
  const { t } = useTranslation();
  const { githubStarStatus, checkGitHubStar, toggleGitHubStar } = useAppStore();
  const { isStarred, ghConfigured, isLoading } = githubStarStatus;

  // Check star status on mount
  useEffect(() => {
    checkGitHubStar();
  }, [checkGitHubStar]);

  // Hide button if user has already starred
  if (isStarred === true) {
    return null;
  }

  const handleClick = () => {
    if (!ghConfigured || isLoading) return;
    toggleGitHubStar();
  };

  // Determine tooltip text
  const getTooltip = () => {
    if (!ghConfigured) return t('sidebar.star.notConfigured');
    if (isLoading) return t('sidebar.star.loading');
    return t('sidebar.star.star');
  };

  const label = t('sidebar.star.star');

  // Render as menu item
  if (asMenuItem) {
    const menuItemClasses = [
      'sidebar-menu-item',
      'star-menu-item',
      !ghConfigured ? 'disabled' : '',
    ]
      .filter(Boolean)
      .join(' ');

    return (
      <button
        type="button"
        onClick={handleClick}
        title={sidebarCollapsed ? getTooltip() : undefined}
        className={menuItemClasses}
        disabled={!ghConfigured || isLoading}
        aria-label={getTooltip()}
      >
        <span className="sidebar-menu-icon">
          {isLoading ? (
            <Loader2 size={20} className="animate-spin" />
          ) : (
            <Star size={20} />
          )}
        </span>
        {!sidebarCollapsed && (
          <span className="sidebar-menu-label">{label}</span>
        )}
      </button>
    );
  }

  // Render as footer button (original behavior)
  const buttonClasses = [
    'sidebar-footer-btn',
    'star-btn',
    !ghConfigured ? 'disabled' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <button
      type="button"
      onClick={handleClick}
      title={getTooltip()}
      className={buttonClasses}
      disabled={!ghConfigured || isLoading}
      aria-label={getTooltip()}
    >
      {isLoading ? (
        <Loader2 size={16} className="animate-spin" />
      ) : (
        <Star size={16} />
      )}
    </button>
  );
}
