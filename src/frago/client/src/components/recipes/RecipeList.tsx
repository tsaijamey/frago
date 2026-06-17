import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import EmptyState from '@/components/ui/EmptyState';
import RecipeTabs from './RecipeTabs';
import CommunityRecipeList from './CommunityRecipeList';
import type { RecipeItem } from '@/types/pywebview';
import { Package, Search, X, ChevronDown, ChevronRight, Workflow, Box, LayoutGrid, List } from 'lucide-react';

interface RecipeCardProps {
  recipe: RecipeItem;
  onClick: () => void;
  view?: 'grid' | 'list';
}

function RecipeCard({ recipe, onClick, view = 'grid' }: RecipeCardProps) {
  const { t } = useTranslation();
  const prettyName = recipe.name.replace(/_/g, ' ');
  const Icon = recipe.category === 'workflow' ? Workflow : Box;
  const techMeta = [recipe.source, recipe.runtime].filter(Boolean).join(' · ');
  const isList = view === 'list';
  const tagLimit = isList ? 3 : 4;
  const visibleTags = recipe.tags.slice(0, tagLimit);
  const extraTags = recipe.tags.length - visibleTags.length;

  const categoryChip = (
    <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
      recipe.category === 'atomic'
        ? 'bg-[var(--status-running-bg)] text-[var(--accent-warning)]'
        : 'bg-[var(--status-completed-bg)] text-[var(--accent-success)]'
    }`}>
      {recipe.category === 'atomic' ? t('recipes.atomic') : t('recipes.workflow')}
    </span>
  );

  // Compact single-row layout for list view
  if (isList) {
    return (
      <div
        className="cursor-pointer flex items-center gap-3 px-3 py-2.5 rounded-lg border border-[var(--border-color)] bg-[var(--bg-card)] hover:border-[var(--border-accent)] hover:bg-[var(--bg-elevated)] transition-colors"
        onClick={onClick}
      >
        <div className="rc-icon" style={{ width: 32, height: 32 }}>
          <Icon size={16} />
        </div>
        <div className="flex items-center gap-2 min-w-0 w-1/3 shrink-0">
          <span className="font-medium text-[var(--text-primary)] capitalize truncate">{prettyName}</span>
          {categoryChip}
        </div>
        <p className="text-sm text-[var(--text-secondary)] truncate flex-1 min-w-0">
          {recipe.description || recipe.name}
        </p>
        <div className="hidden lg:flex items-center gap-1 shrink-0">
          {visibleTags.map((tag) => (
            <span key={tag} className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded">
              {tag}
            </span>
          ))}
          {extraTags > 0 && <span className="text-xs text-[var(--text-muted)]">+{extraTags}</span>}
        </div>
      </div>
    );
  }

  return (
    <div className="card cursor-pointer flex items-start gap-3" onClick={onClick}>
      <div className="rc-icon">
        <Icon size={18} />
      </div>
      <div className="flex-1 min-w-0">
        {/* Title row — human name + category, technical id demoted below */}
        <div className="flex items-center gap-2">
          <span className="font-medium text-[var(--text-primary)] capitalize truncate">
            {prettyName}
          </span>
          {categoryChip}
        </div>
        <div className="text-xs text-[var(--text-muted)] font-mono truncate mt-0.5">
          {recipe.name}{techMeta && ` · ${techMeta}`}
        </div>
        {recipe.description && (
          <p className="text-sm text-[var(--text-secondary)] mt-2 line-clamp-2">
            {recipe.description}
          </p>
        )}
        {visibleTags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {visibleTags.map((tag) => (
              <span
                key={tag}
                className="text-xs bg-[var(--bg-subtle)] text-[var(--text-muted)] px-2 py-0.5 rounded max-w-full truncate"
              >
                {tag}
              </span>
            ))}
            {extraTags > 0 && (
              <span className="text-xs text-[var(--text-muted)] px-1 py-0.5">+{extraTags}</span>
            )}
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
  containerClass: string;
  children: React.ReactNode;
}

function CollapsibleSection({
  title,
  count,
  expanded,
  onToggle,
  colorClass,
  tip,
  containerClass,
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
        <div className={`${containerClass} mt-2`}>
          {children}
        </div>
      )}
    </div>
  );
}

export default function RecipeList() {
  const { t } = useTranslation();
  const { recipes, loadRecipes, communityRecipes, loadCommunityRecipes, switchPage } = useAppStore();
  const [search, setSearch] = useState('');
  const [atomicExpanded, setAtomicExpanded] = useState(true);
  const [workflowExpanded, setWorkflowExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<'local' | 'community'>('local');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(() => {
    try {
      return (localStorage.getItem('recipeView') as 'grid' | 'list') || 'grid';
    } catch {
      return 'grid';
    }
  });

  const setView = (mode: 'grid' | 'list') => {
    setViewMode(mode);
    try {
      localStorage.setItem('recipeView', mode);
    } catch {
      // localStorage unavailable
    }
  };

  const sectionContainerClass = viewMode === 'grid'
    ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3'
    : 'flex flex-col gap-2';

  useEffect(() => {
    loadRecipes();
  }, [loadRecipes]);

  useEffect(() => {
    loadCommunityRecipes();
  }, [loadCommunityRecipes]);

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

  const noResults = atomicRecipes.length === 0 && workflowRecipes.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Page header — consistent with Sessions / Settings */}
      <div className="cs-header" style={{ padding: 'var(--spacing-md) var(--spacing-md) 0' }}>
        <div>
          <h1 className="cs-title">{t('recipes.title')}</h1>
          <p className="cs-subtitle">{t('recipes.pageDesc')}</p>
        </div>
      </div>

      {/* Tab Navigation */}
      <RecipeTabs
        activeTab={activeTab}
        onTabChange={setActiveTab}
        localCount={recipes.length}
        communityCount={communityRecipes.length}
      />

      {/* Community Tab Content */}
      {activeTab === 'community' ? (
        <CommunityRecipeList />
      ) : (
        <>
          {/* Local Tab Content */}
          {recipes.length === 0 ? (
            <EmptyState
              Icon={Package}
              title={t('recipes.noRecipes')}
              description={t('recipes.noRecipesDescription')}
            />
          ) : (
            <>
              {/* Search box + view toggle */}
              <div className="flex items-center gap-2">
                <div className="search-box flex-1">
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
                <div className="rl-view-toggle">
                  <button
                    type="button"
                    className={`rl-view-btn ${viewMode === 'grid' ? 'active' : ''}`}
                    onClick={() => setView('grid')}
                    aria-label={t('recipes.gridView')}
                    title={t('recipes.gridView')}
                  >
                    <LayoutGrid size={16} />
                  </button>
                  <button
                    type="button"
                    className={`rl-view-btn ${viewMode === 'list' ? 'active' : ''}`}
                    onClick={() => setView('list')}
                    aria-label={t('recipes.listView')}
                    title={t('recipes.listView')}
                  >
                    <List size={16} />
                  </button>
                </div>
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
                      containerClass={sectionContainerClass}
                    >
                      {workflowRecipes.map((recipe) => (
                        <RecipeCard
                          key={recipe.name}
                          recipe={recipe}
                          view={viewMode}
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
                      containerClass={sectionContainerClass}
                    >
                      {atomicRecipes.map((recipe) => (
                        <RecipeCard
                          key={recipe.name}
                          recipe={recipe}
                          view={viewMode}
                          onClick={() => switchPage('recipe_detail', recipe.name)}
                        />
                      ))}
                    </CollapsibleSection>
                  )}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
