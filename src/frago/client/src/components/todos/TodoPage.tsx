/**
 * 事务清单——`frago todo` 里那些事务，界面上第一次看得见。
 *
 * 这些事务不走配方，也不进任何数据库，就是 `~/.frago/todo/` 下的一堆 JSON 文件，
 * 所以它进不了配方那套展示体系，只能自己开一页。
 *
 * 顺序照搬服务端（优先级高的在前，同级早建的在前），跟 `frago todo list` 一模一样
 * ——人在命令行看到的第一条和在这里看到的第一条必须是同一件，否则两边对不上账。
 *
 * 一次把全部事务拉回来，筛选在本地做。事务总共几十件，一次拉完的代价可以忽略，
 * 换来的是点筛选条不用等网络，而且「还没了结的」（待办 + 在做）这种跨档位的筛法
 * 才做得出来——服务端那边一次只认一档。
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ListChecks, RefreshCw, Search, X } from 'lucide-react';
import * as api from '@/api';
import type { TodoItem, TodoListResponse } from '@/api';
import { usePageStore } from '@/stores/pageStore';
import { useAutoRefresh } from '@/hooks/useAutoRefresh';
import EmptyState from '@/components/ui/EmptyState';
import TodoDetail from './TodoDetail';
import {
  PRIORITY_TONE,
  STATUS_FILTERS,
  STATUS_TONE,
  countFor,
  matchesFilter,
  type StatusFilter,
} from './todoMeta';

/** 隔多久自己去取一次。事务是人在另一头手动改的，秒级刷新没有意义。 */
const REFRESH_MS = 20_000;

interface TodoRowProps {
  todo: TodoItem;
  selected: boolean;
  onClick: () => void;
}

function TodoRow({ todo, selected, onClick }: TodoRowProps) {
  const { t } = useTranslation();
  const line = todo.summary || todo.context || '';

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
  const [search, setSearch] = useState('');

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
  const counts = body?.counts ?? {};

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return todos.filter((todo) => {
      if (!matchesFilter(todo.status, filter)) return false;
      if (!q) return true;
      return [todo.title, todo.summary ?? '', todo.context ?? '', todo.id, ...todo.tags]
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [todos, filter, search]);

  // 深链进来时，地址里那件可能正好被当前这一档筛掉了。以清单里找得到的为准，找
  // 不到就等下一次取回——事务全在一份清单里，不必为一件再跑一趟。
  const selected = currentTodoId ? todos.find((todo) => todo.id === currentTodoId) ?? null : null;
  const missing = Boolean(currentTodoId) && body !== null && selected === null;

  return (
    <div className="td-page">
      <div className="cs-header" style={{ padding: 'var(--spacing-md) var(--spacing-md) 0' }}>
        <div>
          <h1 className="cs-title">{t('todos.title')}</h1>
          <p className="cs-subtitle">{t('todos.pageDesc')}</p>
        </div>
        <button type="button" className="cs-refresh" onClick={refresh} disabled={refreshing}>
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          {t('common.refresh')}
        </button>
      </div>

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
            <TodoDetail todo={selected} onClose={() => switchPage('todos')} />
          </div>
        )}
      </div>
    </div>
  );
}
