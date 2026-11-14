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

  // 「你在看哪一半」是这一页最重的一档选择，所以走全站统一的分段胶囊（C6）：
  // 一整片浅底托盘 + 选中那一颗浮起来，不刷品牌绿——品牌绿留给动作。
  // 计数内嵌在胶囊右侧，与状态文字同一片底。
  const tabs = [
    { id: 'local' as const, label: t('recipes.localRecipes'), count: localCount },
    { id: 'community' as const, label: t('recipes.communityRecipes'), count: communityCount },
  ];

  return (
    <div
      className="ui-seg-group tdp-seg-group"
      role="tablist"
      aria-label={t('recipes.title')}
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`ui-seg-pill ${activeTab === tab.id ? 'ui-seg-pill--active' : ''}`}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
          <span className="ui-seg-count">{tab.count}</span>
        </button>
      ))}
    </div>
  );
}
