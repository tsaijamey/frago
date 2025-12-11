import { useEffect, useState, useMemo } from 'react';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';
import type { RecipeItem } from '@/types/pywebview.d';
import { Package, Search, X } from 'lucide-react';

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
  const [search, setSearch] = useState('');

  useEffect(() => {
    loadRecipes();
  }, [loadRecipes]);

  // 过滤配方
  const filteredRecipes = useMemo(() => {
    if (!search.trim()) return recipes;
    const query = search.toLowerCase();
    return recipes.filter(
      (recipe) =>
        recipe.name.toLowerCase().includes(query) ||
        recipe.tags.some((tag) => tag.toLowerCase().includes(query))
    );
  }, [recipes, search]);

  if (recipes.length === 0) {
    return (
      <EmptyState
        Icon={Package}
        title="暂无配方"
        description="使用 frago recipe create 创建新配方"
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* 搜索框 */}
      <div className="search-box">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          className="search-input"
          placeholder="搜索名称或标签..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button
            className="search-clear"
            onClick={() => setSearch('')}
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* 配方列表 */}
      {filteredRecipes.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-[var(--text-muted)]">
          无匹配结果
        </div>
      ) : (
        <div className="page-scroll flex flex-col gap-2">
          {filteredRecipes.map((recipe) => (
            <div
              key={recipe.name}
              className="card cursor-pointer"
              onClick={() => switchPage('recipe_detail', recipe.name)}
            >
              <div>
                {/* 第1行：名称 */}
                <div className="font-medium text-[var(--text-primary)] truncate">
                  {recipe.name}
                </div>
                {/* 第2行：类型 + 来源 + 语言类型 */}
                <div className="flex items-center gap-2 mt-1 text-xs">
                  <span
                    className="px-2 py-0.5 rounded"
                    style={{
                      backgroundColor: recipe.category === 'atomic'
                        ? 'var(--status-running-bg)'
                        : 'var(--status-completed-bg)',
                      color: recipe.category === 'atomic'
                        ? 'var(--accent-warning)'
                        : 'var(--accent-success)',
                    }}
                  >
                    {recipe.category === 'atomic' ? 'Atomic' : 'Workflow'}
                  </span>
                  {recipe.source && (
                    <span
                      className="px-2 py-0.5 rounded"
                      style={{
                        backgroundColor: 'var(--bg-subtle)',
                        color: getSourceColor(recipe.source),
                      }}
                    >
                      {recipe.source}
                    </span>
                  )}
                  {recipe.runtime && (
                    <span className="text-[var(--text-muted)]">
                      {recipe.runtime}
                    </span>
                  )}
                </div>
                {/* 第3行：描述 */}
                {recipe.description && (
                  <p className="text-sm text-[var(--text-secondary)] mt-1">
                    {recipe.description}
                  </p>
                )}
                {/* 第4行：标签 */}
                {recipe.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {recipe.tags.map((tag) => (
                      <span
                        key={tag}
                        className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded max-w-full truncate"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
