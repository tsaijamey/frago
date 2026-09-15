/**
 * 事务清单——`frago todo` 里那些事务，界面上第一次看得见。
 *
 * 这些事务不走配方，也不进任何数据库，就是 `~/.frago/todo/` 下的一堆 JSON 文件，
 * 所以它进不了配方那套展示体系，只能自己开一页。
 *
 * 顺序照搬服务端（分类名次在前，同分类里优先级高的在前，再按早建的在前），跟 `frago todo list` 一模一样
 * ——人在命令行看到的第一条和在这里看到的第一条必须是同一件，否则两边对不上账。
 *
 * 一次把全部事务拉回来，筛选在本地做。事务总共几十件，一次拉完的代价可以忽略，
 * 换来的是点筛选条不用等网络，而且「还没了结的」（待办 + 在做）这种跨档位的筛法
 * 才做得出来——服务端那边一次只认一档。
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ListChecks, Loader2, Plus, RefreshCw, Search, Tags, X } from 'lucide-react';
import * as api from '@/api';
import type { TodoCategory, TodoItem, TodoListResponse } from '@/api';
import { usePageStore } from '@/stores/pageStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmptyState from '@/components/ui/EmptyState';
import TodoDetail from './TodoDetail';
import TodoCategoryEditor from './TodoCategoryEditor';
import {
  PRIORITY_TONE,
  STATUS_FILTERS,
  STATUS_TONE,
  UNCATEGORIZED,
  countFor,
  countStatuses,
  effectiveCategory,
  matchesCategory,
  matchesFilter,
  type CategoryFilter,
  type StatusFilter,
} from './todoMeta';

/** 隔多久自己去取一次。事务是人在另一头手动改的，秒级刷新没有意义。 */
const REFRESH_MS = 20_000;

interface TodoRowProps {
  todo: TodoItem;
  categories: TodoCategory[];
  selected: boolean;
  onClick: () => void;
}

function TodoRow({ todo, categories, selected, onClick }: TodoRowProps) {
  const { t } = useTranslation();
  const line = todo.summary || todo.context || '';
  const categoryId = effectiveCategory(todo.category, categories);
  const categoryName = categories.find((c) => c.id === categoryId)?.name;

  return (
    <button
      type="button"
      className={`td-row ${selected ? 'td-row--selected' : ''}`}
      onClick={onClick}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="td-row-head">
        <span className={`td-chip ${STATUS_TONE[todo.status].className}`}>
          {t(`todos.status.${todo.status}`)}
        </span>
        <span className={`td-chip td-chip--category ${categoryName ? '' : 'td-chip--uncategorized'}`}>
          {categoryName ?? t('todos.category.none')}
        </span>
        {todo.priority !== 'normal' && (
          <span className={`td-chip ${PRIORITY_TONE[todo.priority].className}`}>
            {t(`todos.priority.${todo.priority}`)}
          </span>
        )}
        <span className="td-row-title">{todo.title}</span>
      </div>
      {line && <p className="td-row-line">{line}</p>}
      <div className="td-row-meta">
        <span>{todo.created}</span>
        {todo.tags.slice(0, 4).map((tag) => (
          <span key={tag} className="td-tag">
            {tag}
          </span>
        ))}
        {todo.steps.length > 0 && (
          <span>{t('todos.stepCount', { n: todo.steps.length })}</span>
        )}
      </div>
    </button>
  );
}

export default function TodoPage() {
  const { t } = useTranslation();
  const currentTodoId = usePageStore((s) => s.currentTodoId);
  const switchPage = usePageStore((s) => s.switchPage);

  const [body, setBody] = useState<TodoListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<StatusFilter>('active');
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');
  const [search, setSearch] = useState('');
  const [editingCategories, setEditingCategories] = useState(false);

  // 「添一件」那一路。人只填 draft 这一句话，标题、背景、完成判据由 agent 补——所以
  // 这里没有表单，只有一个输入框和一次等待。
  const [composerOpen, setComposerOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [composing, setComposing] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composed, setComposed] = useState<api.TodoComposeResponse | null>(null);

  const { refresh } = useAutoRefresh(
    async () => {
      setRefreshing(true);
      try {
        setBody(await api.getTodos());
        setError(null);
      } catch (e) {
        // 取不到就说取不到，NEVER 拿上一份旧清单顶着：一份停在半小时前的待办
        // 看起来和刚取回的一模一样，人会照着它做判断。
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRefreshing(false);
      }
    },
    { intervalMs: REFRESH_MS }
  );

  // 用 useMemo 兜住空清单：`?? []` 每次渲染都会造一个新数组，下面那个 useMemo 就
  // 等于没缓存，每次渲染重筛一遍。
  const todos = useMemo(() => body?.todos ?? [], [body]);
  const categories = useMemo(() => body?.categories ?? [], [body]);

  // 分类筛选若指着一个刚被删掉的分类，退回「全部」——否则人看到一张空清单，筛选条上
  // 却没有一个按钮是亮的，找不到是谁把事务藏起来了。
  const activeCategory =
    categoryFilter === 'all' || categoryFilter === UNCATEGORIZED || categories.some((c) => c.id === categoryFilter)
      ? categoryFilter
      : 'all';

  // 状态那排的计数只按分类筛过，分类那排的计数只按状态筛过：各自点来点去，自己那排的数不跳。
  const inCategory = useMemo(
    () => todos.filter((todo) => matchesCategory(todo.category, activeCategory, categories)),
    [todos, activeCategory, categories]
  );
  const counts = useMemo(() => countStatuses(inCategory), [inCategory]);
  const categoryCounts = useMemo(() => {
    const out: Record<string, number> = { all: 0, [UNCATEGORIZED]: 0 };
    for (const todo of todos) {
      if (!matchesFilter(todo.status, filter)) continue;
      const key = effectiveCategory(todo.category, categories) ?? UNCATEGORIZED;
      out[key] = (out[key] ?? 0) + 1;
      out.all += 1;
    }
    return out;
  }, [todos, filter, categories]);
  // 分类清单编辑器里「删之前说清影响几件」用的是原始引用数，含已删分类的 id。
  const usage = useMemo(() => {
    const out: Record<string, number> = {};
    for (const todo of todos) if (todo.category) out[todo.category] = (out[todo.category] ?? 0) + 1;
    return out;
  }, [todos]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return inCategory.filter((todo) => {
      if (!matchesFilter(todo.status, filter)) return false;
      if (!q) return true;
      return [todo.title, todo.summary ?? '', todo.context ?? '', todo.id, ...todo.tags]
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [inCategory, filter, search]);

  /**
   * 把那句话交给 agent，等它把事务建出来。
   *
   * 建完就跳到那条上：人写完一句话之后想看的是"它替我写成了什么样"，而不是回到
   * 一份多了一行的清单里自己找。agent 的说法留在输入区上方——它可能没有新建，而是
   * 按规矩把这句话追加到了已有的那条上，那种时候人必须看得见。
   */
  const submitDraft = async () => {
    const text = draft.trim();
    if (!text || composing) return;

    setComposing(true);
    setComposeError(null);
    setComposed(null);
    try {
      const result = await api.composeTodo(text);
      setComposed(result);
      setDraft('');
      await refresh();
      if (result.todo_id) switchPage('todo_detail', result.todo_id);
    } catch (e) {
      setComposeError(e instanceof Error ? e.message : String(e));
    } finally {
      setComposing(false);
    }
  };

  // 深链进来时，地址里那件可能正好被当前这一档筛掉了。以清单里找得到的为准，找
  // 不到就等下一次取回——事务全在一份清单里，不必为一件再跑一趟。
  const selected = currentTodoId ? todos.find((todo) => todo.id === currentTodoId) ?? null : null;
  const missing = Boolean(currentTodoId) && body !== null && selected === null;

  return (
    <div className="td-page">
      <div className="cs-header" style={{ padding: '20px 20px 0' }}>
        <div>
          <h1 className="cs-title">{t('todos.title')}</h1>
          <p className="cs-subtitle">{t('todos.pageDesc')}</p>
        </div>
        <div className="td-head-actions">
          <button
            type="button"
            className={`td-add ${composerOpen ? 'td-add--open' : ''}`}
            onClick={() => setComposerOpen((open) => !open)}
            aria-expanded={composerOpen}
          >
            <Plus size={14} />
            {t('todos.compose.button')}
          </button>
          <button
            type="button"
            className={`cs-refresh ${editingCategories ? 'td-cat-toggle--open' : ''}`}
            onClick={() => setEditingCategories((open) => !open)}
            aria-expanded={editingCategories}
            disabled={body === null}
          >
            <Tags size={14} />
            {t('todos.category.edit')}
          </button>
          <button type="button" className="cs-refresh" onClick={refresh} disabled={refreshing}>
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            {t('common.refresh')}
          </button>
        </div>
      </div>

      {composerOpen && (
        <div className="td-composer">
          <textarea
            className="td-composer-input"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // 事务描述常常要换行，所以回车留给换行，提交走 Cmd/Ctrl+Enter。
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void submitDraft();
              }
            }}
            placeholder={t('todos.compose.placeholder')}
            disabled={composing}
            aria-label={t('todos.compose.button')}
          />
          <div className="td-composer-foot">
            <span className="td-composer-hint">{t('todos.compose.hint')}</span>
            <button
              type="button"
              className="td-composer-submit"
              onClick={() => void submitDraft()}
              disabled={composing || draft.trim() === ''}
            >
              {composing && <Loader2 size={14} className="animate-spin" />}
              {composing ? t('todos.compose.working') : t('todos.compose.submit')}
            </button>
          </div>

          {composeError && <div className="td-error">{t('todos.compose.failed', { message: composeError })}</div>}

          {composed && (
            <div className="td-composer-result">
              <p className="td-composer-verdict">
                {composed.todo_id
                  ? t(composed.created ? 'todos.compose.created' : 'todos.compose.appended', {
                      id: composed.todo_id,
                    })
                  : t('todos.compose.nothingCreated')}
              </p>
              {/* 它替人敲了什么，得摆在明面上——看不见执行了什么的按钮，没人敢按第二次。 */}
              {composed.command && (
                <code className="td-composer-command">{composed.command.join(' ')}</code>
              )}
              {composed.message && <p className="td-composer-message">{composed.message}</p>}
            </div>
          )}
        </div>
      )}

      {editingCategories && body !== null && (
        <TodoCategoryEditor
          categories={categories}
          usage={usage}
          onCancel={() => setEditingCategories(false)}
          onSaved={() => {
            setEditingCategories(false);
            void refresh();
          }}
        />
      )}

      <div className="td-toolbar">
        <div className="td-filters">
          {STATUS_FILTERS.map((name) => (
            <button
              key={name}
              type="button"
              className={`td-filter ${filter === name ? 'td-filter--active' : ''}`}
              onClick={() => setFilter(name)}
            >
              {t(`todos.filter.${name}`)}
              <span className="td-filter-count">{countFor(name, counts)}</span>
            </button>
          ))}
        </div>
        <div className="td-filters" role="group" aria-label={t('todos.category.label')}>
          {['all', ...categories.map((c) => c.id), UNCATEGORIZED].map((id) => (
            <button
              key={id}
              type="button"
              className={`td-filter ${activeCategory === id ? 'td-filter--active' : ''}`}
              onClick={() => setCategoryFilter(id)}
            >
              {id === 'all'
                ? t('todos.category.all')
                : id === UNCATEGORIZED
                  ? t('todos.category.none')
                  : categories.find((c) => c.id === id)?.name}
              <span className="td-filter-count">{categoryCounts[id] ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="search-box td-search">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            className="search-input"
            placeholder={t('todos.searchPlaceholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label={t('todos.searchPlaceholder')}
          />
          {search && (
            <button
              type="button"
              className="search-clear"
              onClick={() => setSearch('')}
              aria-label={t('common.clear')}
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {error && <div className="td-error">{t('todos.loadFailed', { message: error })}</div>}
      {missing && <div className="td-error">{t('todos.notFound', { id: currentTodoId })}</div>}

      <div className="td-split">
        <div className="td-list-pane">
          {body === null && !error ? (
            <div className="td-hint">{t('common.loading')}</div>
          ) : visible.length === 0 ? (
            <EmptyState
              Icon={ListChecks}
              title={t('todos.empty')}
              description={t('todos.emptyDesc')}
            />
          ) : (
            visible.map((todo) => (
              <TodoRow
                key={todo.id}
                todo={todo}
                categories={categories}
                selected={todo.id === currentTodoId}
                onClick={() =>
                  todo.id === currentTodoId
                    ? switchPage('todos')
                    : switchPage('todo_detail', todo.id)
                }
              />
            ))
          )}
        </div>

        {selected && (
          <div className="td-detail-pane">
            <TodoDetail todo={selected} categories={categories} onClose={() => switchPage('todos')} />
          </div>
        )}
      </div>
    </div>
  );
}
