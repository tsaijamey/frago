import { useEffect, useState, useMemo } from 'react';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';
import type { RecipeItem } from '@/types/pywebview.d';
import { Package, Search, X } from 'lucide-react';

// Get source tag classes
function getSourceClasses(source: RecipeItem['source']): string {
  switch (source) {
    case 'User':
      return 'bg-[var(--bg-subtle)] text-[var(--accent-primary)]';
    case 'Project':
      return 'bg-[var(--bg-subtle)] text-[var(--accent-success)]';
    case 'System':
      return 'bg-[var(--bg-subtle)] text-[var(--accent-warning)]';
    default:
      return 'bg-[var(--bg-subtle)] text-[var(--text-muted)]';
  }
}

export default function RecipeList() {
  const { recipes, loadRecipes, switchPage } = useAppStore();
  const [search, setSearch] = useState('');

  useEffect(() => {
    loadRecipes();
  }, [loadRecipes]);

  // Filter recipes
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
        title="No Recipes"
        description="Use frago recipe create to create a new recipe"
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search box */}
      <div className="search-box">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          className="search-input"
          placeholder="Search by name or tag..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search recipes"
        />
        {search && (
          <button
            type="button"
            className="search-clear"
            onClick={() => setSearch('')}
            aria-label="Clear search"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Recipe list */}
      {filteredRecipes.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-[var(--text-muted)]">
          No matching results
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
                {/* Line 1: Name */}
                <div className="font-medium text-[var(--text-primary)] truncate">
                  {recipe.name}
                </div>
                {/* Line 2: Type + Source + Language Type */}
                <div className="flex items-center gap-2 mt-1 text-xs">
                  <span
                    className={`px-2 py-0.5 rounded ${
                      recipe.category === 'atomic'
                        ? 'bg-[var(--status-running-bg)] text-[var(--accent-warning)]'
                        : 'bg-[var(--status-completed-bg)] text-[var(--accent-success)]'
                    }`}
                  >
                    {recipe.category === 'atomic' ? 'Atomic' : 'Workflow'}
                  </span>
                  {recipe.source && (
                    <span
                      className={`px-2 py-0.5 rounded ${getSourceClasses(recipe.source)}`}
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
                {/* Line 3: Description */}
                {recipe.description && (
                  <p className="text-sm text-[var(--text-secondary)] mt-1">
                    {recipe.description}
                  </p>
                )}
                {/* Line 4: Tags */}
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
