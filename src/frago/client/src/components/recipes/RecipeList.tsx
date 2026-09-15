import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmptyState from '@/components/ui/EmptyState';
import RecipeTabs from './RecipeTabs';
import CommunityRecipeList from './CommunityRecipeList';
import RecipeForgeModal from './RecipeForgeModal';
import type { RecipeItem } from '@/types/pywebview';
import { Package, Search, X, ChevronDown, ChevronRight, LayoutGrid, List, Wand2 } from 'lucide-react';

interface RecipeCardProps {
  recipe: RecipeItem;
  onClick: () => void;
  view?: 'grid' | 'list';
}

/**
 * 一张配方卡（网格）或一行（清单）。
 *
 * 不再挂分类徽章和分类图标：配方已经按「工作流 / 原子」分成两段，段标题说过一次，
 * 每张卡再说一遍就是噪音；两种图标满屏重复，也不帮人认出任何一张。字号层级倒过来
 * 的问题一并改掉——名字比描述大，眼睛先落在名字上。
 */
function RecipeCard({ recipe, onClick, view = 'grid' }: RecipeCardProps) {
  const prettyName = recipe.name.replace(/_/g, ' ');
  const techMeta = [recipe.source, recipe.runtime].filter(Boolean).join(' · ');
  const isList = view === 'list';
  const tagLimit = isList ? 3 : 4;
  const visibleTags = recipe.tags.slice(0, tagLimit);
  const extraTags = recipe.tags.length - visibleTags.length;

  const tags = visibleTags.length > 0 && (
    <span className="rl-tags">
      {visibleTags.map((tag) => (
        <span key={tag} className="rl-tag">
          {tag}
        </span>
      ))}
      {extraTags > 0 && <span className="rl-tag-more">+{extraTags}</span>}
    </span>
  );

  if (isList) {
    return (
      <button type="button" className="rl-row" onClick={onClick}>
        <span className="rl-row-name">
          <span className="rl-card-title">{prettyName}</span>
          <span className="rl-card-id">{recipe.name}</span>
        </span>
        <span className="rl-row-desc">{recipe.description || recipe.name}</span>
        {tags}
      </button>
    );
  }

  return (
    <button type="button" className="rl-card" onClick={onClick}>
      <span className="rl-card-title">{prettyName}</span>
      <span className="rl-card-id">
        {recipe.name}
        {techMeta && ` · ${techMeta}`}
      </span>
      {recipe.description && <span className="rl-card-desc">{recipe.description}</span>}
      {tags}
    </button>
  );
}

interface CollapsibleSectionProps {
  title: string;
  count: number;
  expanded: boolean;
  onToggle: () => void;
  tip: string;
  containerClass: string;
  children: React.ReactNode;
}

function CollapsibleSection({
  title,
  count,
  expanded,
  onToggle,
  tip,
  containerClass,
  children,
}: CollapsibleSectionProps) {
  return (
    <section className="rl-section">
      {/* 段标题与事务页的分组标题同一副样子：名字、计数、一句灰色说明排在同一行。 */}
      <button type="button" className="rl-section-head" onClick={onToggle} aria-expanded={expanded}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="rl-section-title">{title}</span>
        <span className="rl-section-count">{count}</span>
        <span className="rl-section-tip">{tip}</span>
      </button>
      {expanded && <div className={containerClass}>{children}</div>}
    </section>
  );
}

export default function RecipeList() {
  const { t } = useTranslation();
  const { recipes, loadRecipes, communityRecipes, loadCommunityRecipes, switchPage } = useAppStore();
  const [search, setSearch] = useState('');
  // 两个标签页各记各的搜索词：搜索框挪到共用的工具栏里之后，切过去再切回来，
  // 各自打过的字还在，跟以前两个标签页各有一个搜索框时一样。
  const [communitySearch, setCommunitySearch] = useState('');
  const [atomicExpanded, setAtomicExpanded] = useState(true);
  const [workflowExpanded, setWorkflowExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<'local' | 'community'>('local');
  const [forgeOpen, setForgeOpen] = useState(false);
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

  const sectionContainerClass = viewMode === 'grid' ? 'rl-grid' : 'rl-rows';

  // 配方是在本机文件系统上加加减减的，界面开着的时候它随时会变。服务端有一条
  // `data_recipes` 的推送通道，但至今没有任何地方真的推过——所以这里自己去取。
  useAutoRefresh(loadRecipes, { intervalMs: 30_000 });

  // 社区配方走的是 GitHub 接口，没登录时一小时只有 60 次配额。定时重取会在人什么
  // 都没做的情况下把配额烧光，所以它只在进页面时取这一次。
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

  // 工具栏右侧：本地页是「搜索 + 网格/清单切换」，社区页只有搜索。和原来一样，
  // 清单为空时不摆搜索框——没东西可搜。
  const isCommunity = activeTab === 'community';
  const showSearch = isCommunity ? communityRecipes.length > 0 : recipes.length > 0;
  const searchValue = isCommunity ? communitySearch : search;
  const setSearchValue = isCommunity ? setCommunitySearch : setSearch;
  const searchPlaceholder = isCommunity ? t('recipes.searchCommunity') : t('recipes.searchByNameOrTag');

  return (
    <div className="flex flex-col h-full tdp rl-page">
      <div className="cs-header tdp-header">
        <div className="min-w-0">
          <h1 className="cs-title">{t('recipes.title')}</h1>
          <p className="cs-subtitle">{t('recipes.pageDesc')}</p>
        </div>
        {/* 创建配方：过去只能在命令行下开发配方，这个入口把它搬进图形界面——
            人写需求，然后在虚拟桌面那扇窗口里看着配方被做出来。 */}
        <div className="td-head-actions">
          <button type="button" className="td-add" onClick={() => setForgeOpen(true)}>
            <Wand2 size={14} />
            {t('recipes.forge.button')}
          </button>
        </div>
      </div>
      {forgeOpen && <RecipeForgeModal onClose={() => setForgeOpen(false)} />}

      <div className="td-toolbar tdp-toolbar">
        <RecipeTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          localCount={recipes.length}
          communityCount={communityRecipes.length}
        />
        {showSearch && (
          <div className="search-box td-search">
            <Search size={16} className="search-icon" />
            <input
              type="text"
              className="search-input"
              placeholder={searchPlaceholder}
              value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)}
              aria-label={isCommunity ? t('recipes.searchCommunity') : t('recipes.searchPlaceholder')}
            />
            {searchValue && (
              <button
                type="button"
                className="search-clear"
                onClick={() => setSearchValue('')}
                aria-label="Clear search"
              >
                <X size={14} />
              </button>
            )}
          </div>
        )}
        {!isCommunity && recipes.length > 0 && (
          <div className="tdp-segmented rl-view-toggle" role="group">
            <button
              type="button"
              className={`td-filter ${viewMode === 'grid' ? 'td-filter--active' : ''}`}
              onClick={() => setView('grid')}
              aria-label={t('recipes.gridView')}
              aria-pressed={viewMode === 'grid'}
              title={t('recipes.gridView')}
            >
              <LayoutGrid size={14} />
            </button>
            <button
              type="button"
              className={`td-filter ${viewMode === 'list' ? 'td-filter--active' : ''}`}
              onClick={() => setView('list')}
              aria-label={t('recipes.listView')}
              aria-pressed={viewMode === 'list'}
              title={t('recipes.listView')}
            >
              <List size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Community Tab Content */}
      {isCommunity ? (
        <CommunityRecipeList search={communitySearch} />
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
