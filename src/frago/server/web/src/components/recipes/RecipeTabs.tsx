/**
 * Recipe Tab Navigation Component
 *
 * Provides tab switching between Local and Community recipes.
 */

import { useTranslation } from 'react-i18next';

interface RecipeTabsProps {
  activeTab: 'local' | 'community';
  onTabChange: (tab: 'local' | 'community') => void;
  localCount: number;
  communityCount: number;
}

export default function RecipeTabs({
  activeTab,
  onTabChange,
  localCount,
  communityCount,
}: RecipeTabsProps) {
  const { t } = useTranslation();

  return (
    <div className="flex border-b border-[var(--border-color)] mb-4">
      <button
        type="button"
        className={`px-4 py-2 text-sm font-medium transition-colors ${
          activeTab === 'local'
            ? 'text-[var(--accent-primary)] border-b-2 border-[var(--accent-primary)]'
            : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
        }`}
        onClick={() => onTabChange('local')}
      >
        {t('recipes.localRecipes')} ({localCount})
      </button>
      <button
        type="button"
        className={`px-4 py-2 text-sm font-medium transition-colors ${
          activeTab === 'community'
            ? 'text-[var(--accent-primary)] border-b-2 border-[var(--accent-primary)]'
            : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
        }`}
        onClick={() => onTabChange('community')}
      >
        {t('recipes.communityRecipes')} ({communityCount})
      </button>
    </div>
  );
}
