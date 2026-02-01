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
    <div className="flex justify-center mt-4 mb-4">
      <div className="inline-flex rounded-full bg-[var(--bg-tertiary)] p-1">
        <button
          type="button"
          className={`px-4 py-1.5 text-sm font-medium rounded-full transition-all ${
            activeTab === 'local'
              ? 'bg-[var(--accent-primary)] text-[var(--text-on-accent)] shadow-sm'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
          }`}
          onClick={() => onTabChange('local')}
        >
          {t('recipes.localRecipes')} ({localCount})
        </button>
        <button
          type="button"
          className={`px-4 py-1.5 text-sm font-medium rounded-full transition-all ${
            activeTab === 'community'
              ? 'bg-[var(--accent-primary)] text-[var(--text-on-accent)] shadow-sm'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
          }`}
          onClick={() => onTabChange('community')}
        >
          {t('recipes.communityRecipes')} ({communityCount})
        </button>
      </div>
    </div>
  );
}
