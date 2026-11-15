/**
 * Recipe Tab Navigation Component
 *
 * Provides secondary source switching (Local vs Community) inside the Catalog view.
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

  const tabs = [
    { id: 'local' as const, label: t('recipes.localRecipes'), count: localCount },
    { id: 'community' as const, label: t('recipes.communityRecipes'), count: communityCount },
  ];

  return (
    <div
      className="ui-seg-group tdp-seg-group"
      role="tablist"
      aria-label={t('recipes.catalogSourceAria', { defaultValue: 'Recipe catalog source' })}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`ui-seg-pill ${activeTab === tab.id ? 'ui-seg-pill--active' : ''}`}
          onClick={() => onTabChange(tab.id)}
          data-testid={`recipe-source-${tab.id}`}
        >
          {tab.label}
          <span className="ui-seg-count">{tab.count}</span>
        </button>
      ))}
    </div>
  );
}
