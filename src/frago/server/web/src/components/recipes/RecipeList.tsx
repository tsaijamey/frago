import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';
import type { RecipeItem } from '@/types/pywebview';
import { Package, Search, X, ChevronDown, ChevronRight } from 'lucide-react';

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

interface RecipeCardProps {
  recipe: RecipeItem;
  onClick: () => void;
}

function RecipeCard({ recipe, onClick }: RecipeCardProps) {
  return (
    <div className="card cursor-pointer" onClick={onClick}>
      <div>
        {/* Line 1: Name */}
        <div className="font-medium text-[var(--text-primary)] truncate">
          {recipe.name}
        </div>
        {/* Line 2: Source + Runtime */}
        <div className="flex items-center gap-2 mt-1 text-xs">
          {recipe.source && (
            <span className={`px-2 py-0.5 rounded ${getSourceClasses(recipe.source)}`}>
              {recipe.source}
            </span>
          )}
          {recipe.runtime && (
            <span className="text-[var(--text-muted)]">{recipe.runtime}</span>
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
  );
}

interface CollapsibleSectionProps {
  title: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  colorClass: string;
  tip: string;
  children: React.ReactNode;
}

function CollapsibleSection({
  title,
  count,
  expanded,
  onToggle,
  colorClass,
  tip,
  children,
}: CollapsibleSectionProps) {
  return (
    <div className="mb-4">
      <button
        type="button"
        className="flex flex-col items-start w-full text-left py-2 px-1 hover:bg-[var(--bg-hover)] rounded transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center gap-2">
          {expanded ? (
            <ChevronDown size={16} className="text-[var(--text-muted)]" />
          ) : (
            <ChevronRight size={16} className="text-[var(--text-muted)]" />
          )}
          <span className={`font-medium ${colorClass}`}>{title}</span>
          <span className="text-xs text-[var(--text-muted)]">({count})</span>
        </div>
        <div className="text-xs text-[var(--text-muted)] ml-6 mt-0.5">{tip}</div>
      </button>
      {expanded && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-2">
          {children}
        </div>
      )}
    </div>
  );
}

export default function RecipeList() {
  const { t } = useTranslation();
  const { recipes, loadRecipes, switchPage } = useAppStore();
  const [search, setSearch] = useState('');
  const [atomicExpanded, setAtomicExpanded] = useState(true);
  const [workflowExpanded, setWorkflowExpanded] = useState(true);

  useEffect(() => {
    loadRecipes();
  }, [loadRecipes]);

  // Filter and group recipes
  const { atomicRecipes, workflowRecipes } = useMemo(() => {
    let filtered = recipes;
    if (search.trim()) {
      const query = search.toLowerCase();
      filtered = recipes.filter(
        (recipe) =>
          recipe.name.toLowerCase().includes(query) ||
          recipe.tags.some((tag) => tag.toLowerCase().includes(query))
      );
    }
    return {
      atomicRecipes: filtered.filter((r) => r.category === 'atomic'),
      workflowRecipes: filtered.filter((r) => r.category === 'workflow'),
    };
  }, [recipes, search]);

  if (recipes.length === 0) {
    return (
      <EmptyState
        Icon={Package}
        title={t('recipes.noRecipes')}
        description={t('recipes.noRecipesDescription')}
      />
    );
  }

  const noResults = atomicRecipes.length === 0 && workflowRecipes.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Search box */}
      <div className="search-box">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          className="search-input"
          placeholder={t('recipes.searchByNameOrTag')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label={t('recipes.searchPlaceholder')}
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
      {noResults ? (
        <div className="flex-1 flex items-center justify-center text-[var(--text-muted)]">
          {t('recipes.noResults')}
        </div>
      ) : (
        <div className="page-scroll">
          {workflowRecipes.length > 0 && (
            <CollapsibleSection
              title={t('recipes.workflow')}
              count={workflowRecipes.length}
              expanded={workflowExpanded}
              onToggle={() => setWorkflowExpanded(!workflowExpanded)}
              colorClass="text-[var(--accent-success)]"
              tip={t('recipes.workflowTip')}
            >
              {workflowRecipes.map((recipe) => (
                <RecipeCard
                  key={recipe.name}
                  recipe={recipe}
                  onClick={() => switchPage('recipe_detail', recipe.name)}
                />
              ))}
            </CollapsibleSection>
          )}
          {atomicRecipes.length > 0 && (
            <CollapsibleSection
              title={t('recipes.atomic')}
              count={atomicRecipes.length}
              expanded={atomicExpanded}
              onToggle={() => setAtomicExpanded(!atomicExpanded)}
              colorClass="text-[var(--accent-warning)]"
              tip={t('recipes.atomicTip')}
            >
              {atomicRecipes.map((recipe) => (
                <RecipeCard
                  key={recipe.name}
                  recipe={recipe}
                  onClick={() => switchPage('recipe_detail', recipe.name)}
                />
              ))}
            </CollapsibleSection>
          )}
        </div>
      )}
    </div>
  );
}
