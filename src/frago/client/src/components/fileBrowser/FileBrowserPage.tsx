/**
 * FileBrowserPage — 文件：本机的目录树，左边树形展开，右边看。
 *
 * 从前想看会话里提到的那份文件，得把路径复制出来，去系统的文件浏览器里粘一遍，再双击。
 * 这一页把那一趟搬进界面：左边按树形一层层展开目录（支持横向平移与拖拽调宽），右边选中
 * 哪一份就摆哪一份；常去的目录或常看的文件还能直接 pin 到左侧 Files 菜单下方当子菜单。
 *
 * **目录列表由服务端读**（`GET /api/files`）：浏览器读不了随便一个本机目录，这是绕不过
 * 去的一步；服务本来只监听本机，那一侧按绝对路径读，页面这侧只管摆。
 *
 * **预览不重做。** 图片、音视频、pdf 交给浏览器自己的标签；markdown 与代码取回来在页面
 * 里摆，跟界面主题走；html 交给服务端那条现成的 viewer 管线。这一页不自己写第二套查看器
 * ——两份实现迟早会摆出不一样的东西。
 *
 * **选中态是整块换底**（`bg-bg-active`），不是单边色条：这一栏里「你选的是哪一条」要一眼
 * 认出来，而左侧竖条那套写法全仓都在拆。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  CornerLeftUp,
  File as FileIcon,
  Folder,
  FolderOpen,
  Loader2,
  Pin,
  PinOff,
  RefreshCw,
} from 'lucide-react';
import * as api from '@/api';
// 主目录与工作目录那一条不走 `@/api` 的双模入口：它只有 HTTP 这一边有（pywebview 那边
// 没有对应的方法），会话页取默认目录时也是直接从这里进。
import { getSystemDirectories } from '@/api/client';
import PageHeader from '@/components/layout/PageHeader';
import type { FileEntry, FileListing, SystemDirectories } from '@/types/api';
import { humanSize } from '@/components/sessionWorkbench/FileViewer';
import { filePinLabel, normalizePinPath, parentDirOf, useFilePins } from '@/stores/filePins';
import FilePreview from './FilePreview';

const ICON = { size: 14, strokeWidth: 1.5 } as const;

const TREE_WIDTH_KEY = 'file-browser-tree-width';
const DEFAULT_TREE_WIDTH = 360;
const MIN_TREE_WIDTH = 260;
const MAX_TREE_WIDTH = 680;

function readTreeWidth(): number {
  try {
    const raw = localStorage.getItem(TREE_WIDTH_KEY);
    const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN;
    if (Number.isFinite(parsed)) {
      return Math.min(MAX_TREE_WIDTH, Math.max(MIN_TREE_WIDTH, parsed));
    }
  } catch {
    // 读不到就用默认宽度
  }
  return DEFAULT_TREE_WIDTH;
}

/** 修改时间压成 `09-24 16:31`。放在 tooltip 里备查，不挤占树节点的横向空间。 */
function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * 从当前目录往上的一条条。主目录底下的用 `~` 起头，主目录之外的从 `/` 起头。
 *
 * 家目录缩成 `~` 与浮窗、页头那几处同一个口径（`withTilde` 只缩显示，这里的每一节
 * 都要能点，所以自己按同一套规则切）。
 */
function crumbs(path: string, home: string | null): { label: string; path: string }[] {
  if (home && (path === home || path.startsWith(`${home}/`))) {
    const rest = path === home ? '' : path.slice(home.length + 1);
    const out = [{ label: '~', path: home }];
    let acc = home;
    for (const part of rest ? rest.split('/') : []) {
      acc += `/${part}`;
      out.push({ label: part, path: acc });
    }
    return out;
  }
  const out = [{ label: '/', path: '/' }];
  let acc = '';
  for (const part of path.split('/').filter(Boolean)) {
    acc += `/${part}`;
    out.push({ label: part, path: acc });
  }
  return out;
}

interface SelectedFile {
  path: string;
  name: string;
  size: number | null;
  modified: string;
}

export default function FileBrowserPage() {
  const { t } = useTranslation();

  const pins = useFilePins((s) => s.pins);
  const togglePin = useFilePins((s) => s.togglePin);
  const pendingTarget = useFilePins((s) => s.pendingTarget);
  const consumeTarget = useFilePins((s) => s.consumeTarget);
  const setActivePath = useFilePins((s) => s.setActivePath);

  const pinnedSet = useMemo(() => new Set(pins.map((p) => p.path)), [pins]);

  /**
   * 想去哪个根目录。null 表示「还没指过」——第一次由服务端回主目录。
   *
   * **服务端解析出来的那个路径不写回这里。** 写回来的话它就是这条请求的依赖，一次挂载
   * 会变成两次请求，中间那一下列表还会闪回「读这个目录…」——顺序反过来才对：这里存人
   * 指的那一个，摆出来用服务端回的那一个（`current`）。
   */
  const [dir, setDir] = useState<string | null>(() => {
    const target = useFilePins.getState().pendingTarget;
    if (!target) return null;
    return target.is_dir ? target.path : parentDirOf(target.path);
  });
  /** 服务端上一次解析出来的那个目录，给「重读这一颗按钮」用。 */
  const resolvedPath = useRef<string | null>(null);
  const [listing, setListing] = useState<FileListing | null>(null);
  /** 主目录与「这台机器上 frago 正在哪儿干活」，拿它俩摆在最上面当入口。 */
  const [systemDirs, setSystemDirs] = useState<SystemDirectories | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedFile | null>(() => {
    const target = useFilePins.getState().pendingTarget;
    if (!target || target.is_dir) return null;
    return {
      path: target.path,
      name: filePinLabel(target.path),
      size: null,
      modified: '',
    };
  });
  const [reloadKey, setReloadKey] = useState(0);
  const [copied, setCopied] = useState(false);
  const [copiedRowPath, setCopiedRowPath] = useState<string | null>(null);
  const copyRowTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** 树形展开的子目录集合与各子目录缓存的条目。 */
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(() => new Set());
  const [dirChildren, setDirChildren] = useState<Record<string, FileEntry[]>>({});
  const [loadingDirs, setLoadingDirs] = useState<Set<string>>(() => new Set());
  /** 树里最近点选的目录路径，供面包屑与「重读」定位。 */
  const [activeDir, setActiveDir] = useState<string | null>(null);
  const expandedDirsRef = useRef<Set<string>>(expandedDirs);
  expandedDirsRef.current = expandedDirs;

  /** 左栏宽度：支持拖拽调宽并跨会话记住。 */
  const [treeWidth, setTreeWidth] = useState<number>(readTreeWidth);

  useEffect(() => {
    let alive = true;
    getSystemDirectories()
      .then((dirs) => {
        if (alive) setSystemDirs(dirs);
      })
      .catch(() => {
        /* 取不到就少几个入口；服务端列目录时不认路径就自己回主目录，这一页照样能用 */
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    // 重读这一颗按钮不该把人弹回主目录：人没指新地方（`dir` 还是 null）时，问的是上一次
    // 服务端解析出来的那一个。用 ref 记它而不是记进状态，理由与上面那条注释同一个——
    // 进了状态就成了这条请求的依赖，重读会变成死循环。
    api
      .listDirectory(dir ?? resolvedPath.current ?? undefined)
      .then((body) => {
        if (!alive) return;
        resolvedPath.current = body.path;
        setListing(body);
        setSelected((prev) => {
          if (!prev) return null;
          const prefix = `${body.path.replace(/\/+$/, '')}/`;
          if (!prev.path.startsWith(prefix)) return prev;
          const rest = prev.path.slice(prefix.length);
          if (rest.includes('/')) return prev;
          const found = body.entries.find((e) => !e.is_dir && e.name === rest);
          return found
            ? { path: prev.path, name: found.name, size: found.size, modified: found.modified }
            : prev;
        });
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    // 重读时把当前展开着的子目录也一并重取，树上的子级才不会停在旧内容。
    if (reloadKey > 0 && expandedDirsRef.current.size > 0) {
      for (const subPath of expandedDirsRef.current) {
        api
          .listDirectory(subPath)
          .then((body) => {
            if (!alive) return;
            setDirChildren((prev) => ({ ...prev, [subPath]: body.entries }));
          })
          .catch(() => {
            /* 子目录重读失败不打断主树 */
          });
      }
    }

    return () => {
      alive = false;
    };
  }, [dir, reloadKey]);

  const go = useCallback((next: string) => {
    const clean = normalizePinPath(next);
    setSelected(null);
    setExpandedDirs(new Set());
    setActiveDir(clean);
    setDir(clean);
  }, []);

  // 从左侧菜单 Files 下方的 pin 子菜单点过来时，跳进对应目录或选中对应文件。
  useEffect(() => {
    if (!pendingTarget) return;
    consumeTarget(pendingTarget.seq);
    if (pendingTarget.is_dir) {
      setSelected(null);
      setExpandedDirs(new Set());
      setActiveDir(pendingTarget.path);
      setDir((prev) => (prev === pendingTarget.path ? prev : pendingTarget.path));
    } else {
      const parent = parentDirOf(pendingTarget.path);
      const name = filePinLabel(pendingTarget.path);
      setExpandedDirs(new Set());
      setActiveDir(parent);
      setDir((prev) => (prev === parent ? prev : parent));
      setSelected({
        path: pendingTarget.path,
        name,
        size: null,
        modified: '',
      });
    }
  }, [pendingTarget, consumeTarget]);

  const home = systemDirs?.home ?? null;
  // 人已经指了哪儿就用哪儿（面包屑立刻跟着走），还没指过就用服务端刚回的那一个。
  const current = dir ?? listing?.path ?? '';
  const focusedDir = activeDir && (activeDir === current || activeDir.startsWith(`${current.replace(/\/+$/, '')}/`))
    ? activeDir
    : current;

  useEffect(() => {
    const active = selected?.path ?? (focusedDir || null);
    setActivePath(active);
  }, [selected?.path, focusedDir, setActivePath]);

  const toggleDirectory = useCallback((path: string) => {
    setSelected(null);
    setActiveDir(path);
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
        return next;
      }
      next.add(path);
      return next;
    });

    setLoadingDirs((prev) => {
      const next = new Set(prev);
      next.add(path);
      return next;
    });

    api
      .listDirectory(path)
      .then((body) => {
        setDirChildren((prev) => ({ ...prev, [path]: body.entries }));
      })
      .catch(() => {
        /* 读不出的子目录保持空列表 */
      })
      .finally(() => {
        setLoadingDirs((prev) => {
          const next = new Set(prev);
          next.delete(path);
          return next;
        });
      });
  }, []);

  const places = useMemo(() => {
    const out: { key: string; label: string; path: string }[] = [];
    if (home) {
      out.push({ key: 'home', label: t('files.places.home'), path: home });
      out.push({ key: 'frago', label: t('files.places.frago'), path: `${home}/.frago` });
    }
    if (systemDirs?.cwd) {
      out.push({ key: 'work', label: t('files.places.working'), path: systemDirs.cwd });
    }
    return out;
  }, [home, systemDirs?.cwd, t]);

  const reveal = useCallback((path: string) => {
    void api.revealPath(path).catch(() => {
      /* 打不开（平台不支持、路径没了）：不打断人，右边那份内容还在 */
    });
  }, []);

  const copyPath = useCallback((path: string) => {
    void navigator.clipboard
      ?.writeText(path)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1_500);
      })
      .catch(() => {
        /* 剪贴板不给用就算了 */
      });
  }, []);

  const copyRowPath = useCallback((path: string) => {
    void navigator.clipboard
      ?.writeText(path)
      .then(() => {
        setCopiedRowPath(path);
        if (copyRowTimerRef.current) clearTimeout(copyRowTimerRef.current);
        copyRowTimerRef.current = setTimeout(() => {
          setCopiedRowPath((prev) => (prev === path ? null : prev));
        }, 1_500);
      })
      .catch(() => {
        /* 剪贴板不给用就算了 */
      });
  }, []);

  useEffect(() => {
    return () => {
      if (copyRowTimerRef.current) clearTimeout(copyRowTimerRef.current);
    };
  }, []);

  const startResize = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = treeWidth;

      const onMove = (moveEvent: MouseEvent) => {
        const next = Math.min(
          MAX_TREE_WIDTH,
          Math.max(MIN_TREE_WIDTH, startWidth + (moveEvent.clientX - startX))
        );
        setTreeWidth(next);
        try {
          localStorage.setItem(TREE_WIDTH_KEY, String(next));
        } catch {
          // 存不下只影响下次打开的初始宽度
        }
      };

      const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
      };

      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [treeWidth]
  );

  const trail = crumbs(current, home);
  const currentDirPinned = current ? pinnedSet.has(normalizePinPath(current)) : false;
  const selectedFilePinned = selected ? pinnedSet.has(normalizePinPath(selected.path)) : false;

  const renderTreeEntries = (parentPath: string, entries: FileEntry[], depth: number): React.ReactNode => {
    const cleanParent = parentPath.replace(/\/+$/, '');
    return entries.map((entry) => {
      const path = `${cleanParent}/${entry.name}`;
      const isExpanded = entry.is_dir && expandedDirs.has(path);
      const isDirLoading = entry.is_dir && loadingDirs.has(path);
      const active = !entry.is_dir && selected?.path === path;
      const isPinned = pinnedSet.has(path);
      const isRowCopied = copiedRowPath === path;
      const children = entry.is_dir ? dirChildren[path] : undefined;
      const modifiedText = shortTime(entry.modified);

      return (
        <div key={path}>
          <div
            className={`group flex min-w-full w-max items-center pr-2 transition-colors duration-150 ${
              active ? 'bg-bg-active font-medium text-text-primary' : 'text-text-secondary hover:bg-bg-hover'
            }`}
          >
            <button
              type="button"
              title={modifiedText ? `${path}\n${modifiedText}` : path}
              style={{ paddingLeft: `${8 + depth * 16}px` }}
              onClick={() => {
                if (entry.is_dir) {
                  toggleDirectory(path);
                } else {
                  setSelected({
                    path,
                    name: entry.name,
                    size: entry.size,
                    modified: entry.modified,
                  });
                }
              }}
              onDoubleClick={() => {
                if (!entry.is_dir) reveal(path);
              }}
              className="flex min-w-0 flex-1 items-center gap-1.5 py-[5px] pr-2 text-left text-[12px]"
            >
              <span className="inline-flex w-[12px] shrink-0 items-center justify-center text-text-muted">
                {entry.is_dir ? (
                  isDirLoading ? (
                    <Loader2 size={11} className="animate-spin" />
                  ) : isExpanded ? (
                    <ChevronDown size={12} />
                  ) : (
                    <ChevronRight size={12} />
                  )
                ) : null}
              </span>
              <span className="shrink-0 text-text-muted">
                {entry.is_dir ? (
                  isExpanded ? (
                    <FolderOpen {...ICON} />
                  ) : (
                    <Folder {...ICON} />
                  )
                ) : (
                  <FileIcon {...ICON} />
                )}
              </span>
              <span className="whitespace-nowrap">{entry.name}</span>
              <span className="min-w-[8px] flex-1" />
              {!entry.is_dir && entry.size !== null ? (
                <span className="shrink-0 font-mono text-[10.5px] text-text-dim">
                  {humanSize(entry.size)}
                </span>
              ) : null}
            </button>
            <button
              type="button"
              onClick={() => copyRowPath(path)}
              title={isRowCopied ? t('files.copied') : t('files.copyPath')}
              aria-label={`${t('files.copyPath')} ${entry.name}`}
              className={`inline-flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-[5px] transition-opacity ${
                isRowCopied
                  ? 'text-accent-primary opacity-100'
                  : 'text-text-muted opacity-0 hover:bg-bg-subtle hover:text-text-primary group-hover:opacity-100 focus-visible:opacity-100'
              }`}
            >
              {isRowCopied ? (
                <Check size={12} strokeWidth={1.5} className="text-accent-primary" />
              ) : (
                <Copy size={12} strokeWidth={1.5} />
              )}
            </button>
            <button
              type="button"
              onClick={() => togglePin({ path, is_dir: entry.is_dir })}
              title={isPinned ? t('files.unpin') : t('files.pin')}
              aria-label={`${isPinned ? t('files.unpin') : t('files.pin')} ${entry.name}`}
              className={`inline-flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-[5px] transition-opacity ${
                isPinned
                  ? 'text-text-primary opacity-100 hover:bg-bg-subtle'
                  : 'text-text-muted opacity-0 hover:bg-bg-subtle hover:text-text-primary group-hover:opacity-100 focus-visible:opacity-100'
              }`}
            >
              {isPinned ? <PinOff size={12} strokeWidth={1.5} /> : <Pin size={12} strokeWidth={1.5} />}
            </button>
          </div>
          {entry.is_dir && isExpanded && children ? (
            children.length > 0 ? (
              renderTreeEntries(path, children, depth + 1)
            ) : (
              <p
                style={{ paddingLeft: `${8 + (depth + 1) * 16 + 18}px` }}
                className="py-1 pr-3 text-[11px] text-text-dim whitespace-nowrap"
              >
                {t('files.empty')}
              </p>
            )
          ) : null}
        </div>
      );
    });
  };

  return (
    <>
      <PageHeader
        title={t('files.title')}
        meta={listing ? t('files.counting', { n: listing.entries.length }) : undefined}
        secondary={
          <button
            type="button"
            className="page-header-btn page-header-btn--icon page-header-btn--ghost"
            onClick={() => setReloadKey((k) => k + 1)}
            title={t('files.refresh')}
            aria-label={t('files.refresh')}
          >
            <RefreshCw size={14} strokeWidth={1.5} />
          </button>
        }
      />

      <div className="flex min-h-0 flex-1">
        {/* 左栏：去哪儿 · 现在在哪 · 树形目录（支持横向平移与拖拽调宽） */}
        <div
          style={{ width: `${treeWidth}px` }}
          className="relative flex shrink-0 flex-col border-r border-border-color bg-bg-secondary"
        >
          <div className="flex flex-wrap gap-1 border-b border-border-color px-2 py-2">
            {places.map((place) => (
              <button
                key={place.key}
                type="button"
                onClick={() => go(place.path)}
                title={place.path}
                className={`rounded-[6px] px-2 py-[3px] text-[11.5px] transition-colors duration-200 ${
                  current === place.path
                    ? 'bg-bg-active font-medium text-text-primary'
                    : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                }`}
              >
                {place.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1 border-b border-border-color px-2 py-1.5">
            <button
              type="button"
              onClick={() => {
                const cut = current.replace(/\/+$/, '').lastIndexOf('/');
                if (cut > 0) go(current.slice(0, cut));
                else if (home) go(home);
              }}
              title={t('files.up')}
              aria-label={t('files.up')}
              className="inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
            >
              <CornerLeftUp {...ICON} />
            </button>
            {/* 面包屑横向可平移滚动，深路径也能完整拖看。 */}
            <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
              {trail.map((node, i) => (
                <span key={node.path} className="flex shrink-0 items-center gap-0.5">
                  {i > 0 ? <ChevronRight size={11} className="text-text-dim" /> : null}
                  <button
                    type="button"
                    onClick={() => go(node.path)}
                    className={`rounded-[5px] px-1.5 py-[1px] font-mono text-[11.5px] ${
                      i === trail.length - 1
                        ? 'font-medium text-text-primary'
                        : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'
                    }`}
                  >
                    {node.label}
                  </button>
                </span>
              ))}
            </div>
            {current ? (
              <button
                type="button"
                onClick={() => togglePin({ path: current, is_dir: true })}
                title={currentDirPinned ? t('files.unpin') : t('files.pin')}
                aria-label={currentDirPinned ? t('files.unpin') : t('files.pin')}
                className={`inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] ${
                  currentDirPinned
                    ? 'text-text-primary hover:bg-bg-hover'
                    : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'
                }`}
              >
                {currentDirPinned ? <PinOff {...ICON} /> : <Pin {...ICON} />}
              </button>
            ) : null}
          </div>

          <div data-testid="file-tree-scroll" className="min-h-0 flex-1 overflow-auto py-1">
            {loading ? (
              <p className="flex items-center justify-center gap-2 py-8 text-[12px] text-text-muted">
                <Loader2 size={14} className="animate-spin" />
                {t('files.listing')}
              </p>
            ) : error ? (
              <p className="px-3 py-8 text-center text-[12px] leading-relaxed text-text-muted">
                <span className="block">{t('files.listFailed')}</span>
                <span className="mt-1 block text-text-dim">{error}</span>
              </p>
            ) : listing && listing.entries.length === 0 ? (
              <p className="px-3 py-8 text-center text-[12px] text-text-muted">{t('files.empty')}</p>
            ) : listing ? (
              <div className="min-w-full w-max">
                {renderTreeEntries(current, listing.entries, 0)}
              </div>
            ) : null}
          </div>

          <div
            role="separator"
            aria-orientation="vertical"
            onMouseDown={startResize}
            className="absolute top-0 right-0 bottom-0 w-[4px] cursor-col-resize hover:bg-border-strong"
          />
        </div>

        {/* 右栏：选中的那一份 */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-base">
          {selected ? (
            <>
              <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border-color bg-bg-primary px-3">
                <FileIcon size={14} className="shrink-0 text-text-muted" />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-secondary">
                  {selected.path}
                </span>
                <button
                  type="button"
                  onClick={() => togglePin({ path: selected.path, is_dir: false })}
                  title={selectedFilePinned ? t('files.unpin') : t('files.pin')}
                  aria-label={selectedFilePinned ? t('files.unpin') : t('files.pin')}
                  className={`inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] ${
                    selectedFilePinned
                      ? 'text-text-primary hover:bg-bg-hover'
                      : 'text-text-muted hover:bg-bg-hover hover:text-text-primary'
                  }`}
                >
                  {selectedFilePinned ? <PinOff size={14} /> : <Pin size={14} />}
                </button>
                <button
                  type="button"
                  onClick={() => copyPath(selected.path)}
                  title={t('files.copyPath')}
                  aria-label={t('files.copyPath')}
                  className="inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                >
                  {copied ? <Check size={14} className="text-accent-primary" /> : <Copy size={14} />}
                </button>
                <button
                  type="button"
                  onClick={() => reveal(selected.path)}
                  title={t('files.reveal')}
                  aria-label={t('files.reveal')}
                  className="inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                >
                  <FolderOpen size={14} />
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <FilePreview
                  key={selected.path}
                  path={selected.path}
                  name={selected.name}
                  size={selected.size}
                />
              </div>
            </>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-[12px] text-text-muted">
              <Folder size={28} strokeWidth={1.4} className="text-text-dim" />
              {t('files.noSelection')}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
