/**
 * QuickRecipes — shows top recipes sorted by recent usage.
 */

import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { BookOpen, ChevronRight, Play } from 'lucide-react';
import { runRecipe } from '@/api';
import type { QuickRecipeItem } from '@/api/client';

interface Props {
  recipes: QuickRecipeItem[];
}

export default function QuickRecipes({ recipes }: Props) {
  const { t } = useTranslation();
  const { switchPage, showToast } = useAppStore();

  if (recipes.length === 0) {
    return (
      <div className="dashboard-card">
        <h2 className="dashboard-section-title-only">
          {t('dashboard.quickRecipes')}
        </h2>
        <div className="dashboard-empty">{t('dashboard.noQuickRecipes')}</div>
      </div>
    );
  }

  const handleRun = async (name: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const result = await runRecipe(name);
      if (result.status === 'ok') {
        showToast(t('recipes.executedSuccess'), 'success');
      } else {
        showToast(result.error || t('recipes.executionFailed'), 'error');
      }
    } catch {
      showToast(t('recipes.failedToExecute'), 'error');
    }
  };

  return (
    <div className="dashboard-card">
      <div className="dashboard-section-header">
        <h2 className="dashboard-section-title">
          <BookOpen size={16} />
          {t('dashboard.quickRecipes')}
        </h2>
        <button
          type="button"
          onClick={() => switchPage('recipes')}
          className="dashboard-view-all-btn"
        >
          {t('dashboard.viewAll')} <ChevronRight size={14} />
        </button>
      </div>
      <div className="dashboard-activity-list">
        {recipes.map((recipe) => (
          <div
            key={recipe.name}
            className="dashboard-activity-item"
            onClick={() => switchPage('recipe_detail', recipe.name)}
          >
            <div className="dashboard-activity-content">
              <div className="dashboard-activity-title">{recipe.name}</div>
              <div className="dashboard-activity-time">
                {recipe.description || recipe.runtime || ''}
                {recipe.run_count > 0 && ` · ${recipe.run_count} ${t('dashboard.runs')}`}
              </div>
            </div>
            <button
              type="button"
              className="dashboard-quick-run-btn"
              onClick={(e) => handleRun(recipe.name, e)}
              title={t('recipes.run')}
            >
              <Play size={14} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
