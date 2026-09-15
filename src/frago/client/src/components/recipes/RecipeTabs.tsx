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

  // 与事务页、定时任务页的状态筛选同一个分段控件：选中那一档整块浮起来，不刷品牌绿——
  // 这是「你在看哪一半」，属于页面的操作面；品牌绿留给动作与活跃状态。
  // 放在工具栏最左，跟搜索框同一行，不再单独居中占一行。
  const tabs = [
    { id: 'local' as const, label: t('recipes.localRecipes'), count: localCount },
    { id: 'community' as const, label: t('recipes.communityRecipes'), count: communityCount },
  ];

  return (
    <div className="td-filters tdp-segmented" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={`td-filter ${activeTab === tab.id ? 'td-filter--active' : ''}`}
          onClick={() => onTabChange(tab.id)}
        >
          {tab.label}
          <span className="td-filter-count">{tab.count}</span>
        </button>
      ))}
    </div>
  );
}
