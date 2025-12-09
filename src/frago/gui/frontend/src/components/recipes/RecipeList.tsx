import { useEffect } from 'react';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';
import type { RecipeItem } from '@/types/pywebview.d';

// 获取分类图标
function getCategoryIcon(category: RecipeItem['category']): string {
  return category === 'atomic' ? '⚡' : '🔗';
}

// 获取来源标签颜色
function getSourceColor(source: RecipeItem['source']): string {
  switch (source) {
    case 'User':
      return 'var(--accent-primary)';
    case 'Project':
      return 'var(--accent-success)';
    case 'System':
      return 'var(--accent-warning)';
    default:
      return 'var(--text-muted)';
  }
}

export default function RecipeList() {
  const { recipes, loadRecipes, switchPage } = useAppStore();

  useEffect(() => {
    loadRecipes();
  }, [loadRecipes]);

  if (recipes.length === 0) {
    return (
      <EmptyState
        icon="📦"
        title="暂无配方"
        description="使用 frago recipe create 创建新配方"
      />
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {recipes.map((recipe) => (
        <div
          key={recipe.name}
          className="card cursor-pointer"
          onClick={() => switchPage('recipe_detail', recipe.name)}
        >
          <div className="flex items-start gap-3">
            <span className="text-xl">{getCategoryIcon(recipe.category)}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-[var(--text-primary)]">
                  {recipe.name}
                </span>
                {recipe.source && (
                  <span
                    className="text-xs px-2 py-0.5 rounded"
                    style={{
                      backgroundColor: 'var(--bg-subtle)',
                      color: getSourceColor(recipe.source),
                    }}
                  >
                    {recipe.source}
                  </span>
                )}
                {recipe.runtime && (
                  <span className="text-xs text-[var(--text-muted)]">
                    {recipe.runtime}
                  </span>
                )}
              </div>
              {recipe.description && (
                <p className="text-sm text-[var(--text-secondary)] mt-1">
                  {recipe.description}
                </p>
              )}
              {recipe.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {recipe.tags.map((tag) => (
                    <span
                      key={tag}
                      className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
