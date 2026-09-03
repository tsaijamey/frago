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

  // 选中那一档抬起来（换成浮起的表面 + 一档字重），不是刷成一块实心品牌绿。
  // 这是"你在看哪一半"，属于页面的操作面；品牌绿留给动作与活跃状态。
  const seg = (on: boolean) =>
    `px-3 h-7 text-[13px] rounded-[6px] transition-colors duration-200 ${
      on
        ? 'bg-[var(--bg-elevated)] text-[var(--text-primary)] font-medium shadow-[var(--shadow-sm),0_0_0_1px_var(--border-color)]'
        : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
    }`;

  return (
    <div className="mb-5 flex justify-center">
      <div className="inline-flex gap-0.5 rounded-[8px] bg-[var(--bg-subtle)] p-0.5">
        <button type="button" className={seg(activeTab === 'local')} onClick={() => onTabChange('local')}>
          {t('recipes.localRecipes')} ({localCount})
        </button>
        <button
          type="button"
          className={seg(activeTab === 'community')}
          onClick={() => onTabChange('community')}
        >
          {t('recipes.communityRecipes')} ({communityCount})
        </button>
      </div>
    </div>
  );
}
