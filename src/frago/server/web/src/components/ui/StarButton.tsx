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
 */

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Star, Loader2 } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';

export default function StarButton() {
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
