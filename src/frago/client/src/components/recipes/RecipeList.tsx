import { useEffect, useState, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import { useRecipeFolders, suggestFolderId } from '@/stores/recipeFolders';
import EmptyState from '@/components/ui/EmptyState';
import RecipeTabs from './RecipeTabs';
import CommunityRecipeList from './CommunityRecipeList';
import RecipeForgeModal from './RecipeForgeModal';
import RecipeFolderTile from './RecipeFolderTile';
import FolderNameModal from './FolderNameModal';
import { recipeTitle } from './recipeTitle';
import type { RecipeItem } from '@/types/pywebview';
import type { RecipeFolder } from '@/types/api';
import {
  Package, Search, X, ChevronDown, ChevronRight, LayoutGrid, List, Wand2,
  FolderPlus, MoreHorizontal, CheckSquare, Square,
} from 'lucide-react';

/** 拖动时装配方名的那个格式。自己的格式，不占 text/plain，免得拖进别处变成一串字。 */
const DRAG_TYPE = 'application/x-frago-recipes';

interface RecipeCardProps {
  recipe: RecipeItem;
  onClick: () => void;
  view?: 'grid' | 'list';
  /** 正在挑选状态：整页的卡都长出勾选框，点卡片变成选中而不是进详情。 */
  selecting: boolean;
  selected: boolean;
  onToggleSelect: () => void;
  /** 开这张卡的「…」菜单。菜单画在外层，卡片只管报告位置。 */
  onOpenMenu: (anchor: DOMRect) => void;
  onDragStartRecipe: (e: React.DragEvent) => void;
  /** 另一张卡被拖到这张上松手了：手机上这一下就是建一个新文件夹。 */
  onDropRecipes: (names: string[]) => void;
}

/**
 * 一张配方卡（网格）或一行（清单）。
 *
 * 不再挂分类徽章和分类图标：配方已经按「工作流 / 原子」分成两段，段标题说过一次，
 * 每张卡再说一遍就是噪音；两种图标满屏重复，也不帮人认出任何一张。字号层级倒过来
 * 的问题一并改掉——名字比描述大，眼睛先落在名字上。
 *
 * 显示的名字优先用作者写的 `title`，没写才回落到把 `name` 里的下划线换成空格。作者
 * 写过的名字不再套 capitalize：那条规则是为「下划线换空格」那种凑出来的名字准备
 * 的，套在人自己起的名字上等于替他改写。
 */
function RecipeCard({
  recipe,
  onClick,
  view = 'grid',
  selecting,
  selected,
  onToggleSelect,
  onOpenMenu,
  onDragStartRecipe,
  onDropRecipes,
}: RecipeCardProps) {
  const { i18n } = useTranslation();
  const [over, setOver] = useState(false);
  const named = Object.keys(recipe.title ?? {}).length > 0;
  const shownName = recipeTitle(recipe, i18n.language);
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

  const title = (
    <span className={`rl-card-title ${named ? 'rl-card-title--named' : ''}`}>{shownName}</span>
  );

  const activate = () => (selecting ? onToggleSelect() : onClick());

  const takeDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setOver(false);
    const raw = e.dataTransfer.getData(DRAG_TYPE);
    if (!raw) return;
    try {
      const names = (JSON.parse(raw) as string[]).filter((n) => n !== recipe.name);
      if (names.length) onDropRecipes(names);
    } catch {
      // 拖进来的不是配方卡，当没发生过。
    }
  };

  if (isList) {
    return (
      <div className={`rl-row-wrap ${selected ? 'rl-picked' : ''}`}>
        <button type="button" className="rl-row" onClick={activate} draggable
          onDragStart={onDragStartRecipe}>
          {selecting && (
            <span className="rl-pick" aria-hidden="true">
              {selected ? <CheckSquare size={14} /> : <Square size={14} />}
            </span>
          )}
          <span className="rl-row-name">
            {title}
            <span className="rl-card-id">{recipe.name}</span>
          </span>
          <span className="rl-row-desc">{recipe.description || recipe.name}</span>
          {tags}
        </button>
        <button
          type="button"
          className="rl-card-menu"
          onClick={(e) => {
            e.stopPropagation();
            onOpenMenu(e.currentTarget.getBoundingClientRect());
          }}
          aria-label={recipe.name}
        >
          <MoreHorizontal size={14} />
        </button>
      </div>
    );
  }

  return (
    <div
      className={`rl-card-wrap ${selected ? 'rl-picked' : ''} ${over ? 'rl-card-wrap--over' : ''}`}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={takeDrop}
    >
      <button
        type="button"
        className="rl-card"
        onClick={activate}
        draggable
        onDragStart={onDragStartRecipe}
      >
        {selecting && (
          <span className="rl-pick" aria-hidden="true">
            {selected ? <CheckSquare size={14} /> : <Square size={14} />}
          </span>
        )}
        {title}
        <span className="rl-card-id">
          {recipe.name}
          {techMeta && ` · ${techMeta}`}
        </span>
        {recipe.description && <span className="rl-card-desc">{recipe.description}</span>}
        {tags}
      </button>
      <button
        type="button"
        className="rl-card-menu"
        onClick={(e) => {
          e.stopPropagation();
          onOpenMenu(e.currentTarget.getBoundingClientRect());
        }}
        aria-label={recipe.name}
      >
        <MoreHorizontal size={14} />
      </button>
    </div>
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
  const { t, i18n } = useTranslation();
  const { recipes, loadRecipes, communityRecipes, loadCommunityRecipes, switchPage } = useAppStore();
  const folderStore = useRecipeFolders();
  const [search, setSearch] = useState('');
  // 两个标签页各记各的搜索词：搜索框挪到共用的工具栏里之后，切过去再切回来，
  // 各自打过的字还在，跟以前两个标签页各有一个搜索框时一样。
  const [communitySearch, setCommunitySearch] = useState('');
  const [atomicExpanded, setAtomicExpanded] = useState(true);
  const [workflowExpanded, setWorkflowExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<'local' | 'community'>('local');
  const [forgeOpen, setForgeOpen] = useState(false);

  // ── 文件夹这一摊 ────────────────────────────────────────────────────
  // 打开的那个文件夹就地展开，不换页：往文件夹里摆东西通常一口气摆好几张，每开
  // 一个就跳走一次会把这件事拆得很碎。
  const [openFolder, setOpenFolder] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [menu, setMenu] = useState<{ names: string[]; x: number; y: number } | null>(null);
  // 建文件夹：手里拿着哪几张配方，建完当场放进去。空数组就是从工具栏建一个空的。
  const [creating, setCreating] = useState<string[] | null>(null);
  const [renaming, setRenaming] = useState<RecipeFolder | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

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

  const loadFolders = folderStore.load;
  useEffect(() => {
    loadFolders();
  }, [loadFolders]);

  // 菜单开着时点别处就关掉。菜单是浮在整页上的，不关的话它会一直跟着页面滚。
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menu]);

  const byName = useMemo(
    () => new Map(recipes.map((r) => [r.name, r])),
    [recipes],
  );

  // Filter and group recipes
  const { atomicRecipes, workflowRecipes } = useMemo(() => {
    let list = recipes;
    if (search.trim()) {
      const query = search.toLowerCase();
      list = recipes.filter(
        (recipe) =>
          recipe.name.toLowerCase().includes(query) ||
          recipeTitle(recipe, i18n.language).toLowerCase().includes(query) ||
          recipe.tags.some((tag) => tag.toLowerCase().includes(query))
      );
    }
    // 摆进文件夹的配方不在下面两段里重复出现——手机上也是这样，进了文件夹的图标
    // 就不再留在桌面上。搜索时例外：人在找东西，藏在文件夹里反而找不着。
    const loose = search.trim() ? list : list.filter((r) => !r.folder);
    return {
      atomicRecipes: loose.filter((r) => r.category === 'atomic'),
      workflowRecipes: loose.filter((r) => r.category === 'workflow'),
    };
  }, [recipes, search, i18n.language]);

  const noResults = atomicRecipes.length === 0 && workflowRecipes.length === 0
    && (search.trim() ? true : folderStore.folders.length === 0);

  // ── 动作 ────────────────────────────────────────────────────────────

  const dragPayload = (name: string): string[] =>
    picked.includes(name) && picked.length > 1 ? picked : [name];

  const startDrag = (e: React.DragEvent, name: string) => {
    const names = dragPayload(name);
    e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(names));
    e.dataTransfer.effectAllowed = 'move';
  };

  const doAssign = async (names: string[], folder: string | null) => {
    const ok = await folderStore.assign(names, folder);
    if (ok) {
      await loadRecipes();
      setPicked([]);
      setSelecting(false);
    }
    setMenu(null);
  };

  const doCreate = async (nameZh: string, nameEn: string) => {
    const taken = folderStore.folders.map((f) => f.id);
    const ok = await folderStore.create({
      id: suggestFolderId(nameEn || nameZh, taken),
      name_zh: nameZh,
      name_en: nameEn,
      recipes: creating ?? [],
    });
    if (ok) {
      await loadRecipes();
      setCreating(null);
      setPicked([]);
      setSelecting(false);
    }
  };

  const doRename = async (nameZh: string, nameEn: string) => {
    if (!renaming) return;
    const ok = await folderStore.rename(renaming.id, nameZh, nameEn);
    if (ok) setRenaming(null);
  };

  const doRemoveFolder = async (folder: RecipeFolder) => {
    const ok = await folderStore.remove(folder.id);
    if (ok) {
      await loadRecipes();
      if (openFolder === folder.id) setOpenFolder(null);
    }
  };

  const togglePick = (name: string) =>
    setPicked((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]));

  const cardProps = (recipe: RecipeItem) => ({
    selecting,
    selected: picked.includes(recipe.name),
    onToggleSelect: () => togglePick(recipe.name),
    onOpenMenu: (anchor: DOMRect) =>
      setMenu({ names: dragPayload(recipe.name), x: anchor.left, y: anchor.bottom + 4 }),
    onDragStartRecipe: (e: React.DragEvent) => startDrag(e, recipe.name),
    onDropRecipes: (names: string[]) => setCreating([...names, recipe.name]),
  });

  // 工具栏从左到右按层级排：来源切换（决定整页看什么）→ 搜索（在这一页里找）→
  // 行尾的网格/清单切换（只管怎么摆，仅本地页有）。搜索框贴着来源切换左对齐，
  // 两个标签页之间切来切去它不挪位置。和原来一样，清单为空时不摆搜索框。
  const isCommunity = activeTab === 'community';
  const showSearch = isCommunity ? communityRecipes.length > 0 : recipes.length > 0;
  const searchValue = isCommunity ? communitySearch : search;
  const setSearchValue = isCommunity ? setCommunitySearch : setSearch;
  const searchPlaceholder = isCommunity ? t('recipes.searchCommunity') : t('recipes.searchByNameOrTag');

  const openFolderRow = folderStore.folders.find((f) => f.id === openFolder) ?? null;
  const openFolderItems = openFolderRow
    ? openFolderRow.recipes.map((n) => byName.get(n)).filter((r): r is RecipeItem => Boolean(r))
    : [];

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
        {/* 建文件夹的第二个入口。第一个是把一张卡拖到另一张上——那个手感好但看不
            见，第一次用的人找不到它，所以这里摆一个明摆着的。两个入口通同一张表。 */}
        {!isCommunity && recipes.length > 0 && (
          <>
            <button
              type="button"
              className="rl-tool-btn"
              onClick={() => setCreating(picked)}
              title={t('recipes.folder.create')}
            >
              <FolderPlus size={15} />
              <span>{t('recipes.folder.create')}</span>
            </button>
            <button
              type="button"
              className={`rl-tool-btn ${selecting ? 'rl-tool-btn--active' : ''}`}
              onClick={() => {
                setSelecting(!selecting);
                setPicked([]);
              }}
              aria-pressed={selecting}
              title={t('recipes.folder.select')}
            >
              <CheckSquare size={15} />
              <span>{t('recipes.folder.select')}</span>
            </button>
          </>
        )}
        {/* 网格 / 清单只是「本地这一页怎么摆」的偏好，比来源切换低一级：
            放在行尾、画得更轻；社区页没有它时，它左边的东西一个都不挪。 */}
        {!isCommunity && recipes.length > 0 && (
          <div className="rl-view-toggle" role="group">
            <button
              type="button"
              className={`rl-view-btn ${viewMode === 'grid' ? 'rl-view-btn--active' : ''}`}
              onClick={() => setView('grid')}
              aria-label={t('recipes.gridView')}
              aria-pressed={viewMode === 'grid'}
              title={t('recipes.gridView')}
            >
              <LayoutGrid size={15} />
            </button>
            <button
              type="button"
              className={`rl-view-btn ${viewMode === 'list' ? 'rl-view-btn--active' : ''}`}
              onClick={() => setView('list')}
              aria-label={t('recipes.listView')}
              aria-pressed={viewMode === 'list'}
              title={t('recipes.listView')}
            >
              <List size={15} />
            </button>
          </div>
        )}
      </div>

      {/* 挑中几张之后的那一条。它只在挑选状态下出现，说清挑了几张、下一步能做什么。 */}
      {!isCommunity && selecting && picked.length > 0 && (
        <div className="rl-pickbar">
          <span className="rl-pickbar-count">{t('recipes.folder.picked', { count: picked.length })}</span>
          {folderStore.folders.map((f) => (
            <button
              key={f.id}
              type="button"
              className="rl-pickbar-btn"
              onClick={() => doAssign(picked, f.id)}
            >
              {f.name[i18n.language.startsWith('zh') ? 'zh-CN' : 'en'] || f.name['zh-CN'] || f.id}
            </button>
          ))}
          <button type="button" className="rl-pickbar-btn" onClick={() => setCreating(picked)}>
            <FolderPlus size={13} />
            {t('recipes.folder.create')}
          </button>
          <button type="button" className="rl-pickbar-btn" onClick={() => doAssign(picked, null)}>
            {t('recipes.folder.takeOut')}
          </button>
          <button type="button" className="rl-pickbar-clear" onClick={() => setPicked([])}>
            {t('common.clear')}
          </button>
        </div>
      )}

      {folderStore.error && (
        <div className="rl-folder-banner" role="alert">
          {folderStore.error}
          <button type="button" onClick={folderStore.clearError} aria-label={t('common.close')}>
            <X size={13} />
          </button>
        </div>
      )}
      {folderStore.trouble && (
        <div className="rl-folder-banner" role="alert">
          {t('recipes.folder.trouble', { detail: folderStore.trouble })}
        </div>
      )}

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
                  {/* 文件夹。一个都没有时这一段整个不出现——界面跟从前一样平铺一屏
                      图标，直到主人亲手建第一个。搜索时也不出现：人在找东西。 */}
                  {!search.trim() && folderStore.folders.length > 0 && (
                    <section className="rl-section">
                      <div className="rl-folders">
                        {folderStore.folders.map((f) => (
                          <RecipeFolderTile
                            key={f.id}
                            folder={f}
                            items={f.recipes
                              .map((n) => byName.get(n))
                              .filter((r): r is RecipeItem => Boolean(r))}
                            open={openFolder === f.id}
                            onToggle={() => setOpenFolder(openFolder === f.id ? null : f.id)}
                            onDropRecipes={(names) => doAssign(names, f.id)}
                            onRename={() => setRenaming(f)}
                            onRemove={() => doRemoveFolder(f)}
                          />
                        ))}
                      </div>
                      {openFolderRow && (
                        <div className={`rl-folder-open ${sectionContainerClass}`}>
                          {openFolderItems.length === 0 ? (
                            <p className="rl-folder-empty">{t('recipes.folder.empty')}</p>
                          ) : (
                            openFolderItems.map((recipe) => (
                              <RecipeCard
                                key={recipe.name}
                                recipe={recipe}
                                view={viewMode}
                                onClick={() => switchPage('recipe_detail', recipe.name)}
                                {...cardProps(recipe)}
                              />
                            ))
                          )}
                        </div>
                      )}
                    </section>
                  )}

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
                          {...cardProps(recipe)}
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
                          {...cardProps(recipe)}
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

      {/* 卡片上的「…」菜单：挑一个文件夹、或者建一个、或者拿出来。这是不靠拖拽的
          那条路——多选、键盘、触控板都走它。 */}
      {menu && (
        <div
          ref={menuRef}
          className="rl-menu"
          style={{ left: menu.x, top: menu.y }}
          role="menu"
        >
          <span className="rl-menu-head">{t('recipes.folder.moveTo')}</span>
          {folderStore.folders.map((f) => (
            <button
              key={f.id}
              type="button"
              className="rl-menu-item"
              role="menuitem"
              onClick={() => doAssign(menu.names, f.id)}
            >
              {f.name[i18n.language.startsWith('zh') ? 'zh-CN' : 'en'] || f.name['zh-CN'] || f.id}
            </button>
          ))}
          <button
            type="button"
            className="rl-menu-item"
            role="menuitem"
            onClick={() => {
              setCreating(menu.names);
              setMenu(null);
            }}
          >
            <FolderPlus size={13} />
            {t('recipes.folder.create')}
          </button>
          {menu.names.some((n) => byName.get(n)?.folder) && (
            <button
              type="button"
              className="rl-menu-item"
              role="menuitem"
              onClick={() => doAssign(menu.names, null)}
            >
              {t('recipes.folder.takeOut')}
            </button>
          )}
        </div>
      )}

      {creating !== null && (
        <FolderNameModal
          withCount={creating.length}
          error={folderStore.error}
          onSubmit={doCreate}
          onClose={() => {
            setCreating(null);
            folderStore.clearError();
          }}
        />
      )}
      {renaming && (
        <FolderNameModal
          initialZh={renaming.name['zh-CN'] ?? ''}
          initialEn={renaming.name.en ?? ''}
          error={folderStore.error}
          onSubmit={doRename}
          onClose={() => {
            setRenaming(null);
            folderStore.clearError();
          }}
        />
      )}
    </div>
  );
}
