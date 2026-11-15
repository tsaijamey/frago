/**
 * FileBrowserPage — 文件：本机的目录树，左边树形展开，右边看。
 *
 * 页头提供 Home / data / cwd 预设根切换与 Show hidden 开关；
 * 下方左右分栏 `.files-split`（默认 300px 可拖拽目录树 `.files-tree-col` + `1fr` 预览区 `.files-preview-col`），
 * 树顶提供关键词过滤与目录优先排序，右侧顶部显示可点面包屑 `.files-crumbs` 与语法着色/元信息预览。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  CornerLeftUp,
  Eye,
  EyeOff,
  File as FileIcon,
  Folder,
  FolderOpen,
  Loader2,
  Pin,
  PinOff,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import * as api from '@/api';
import { getSystemDirectories } from '@/api/client';
import PageHeader from '@/components/layout/PageHeader';
import EmptyState from '@/components/ui/EmptyState';
import type { FileEntry, FileListing, SystemDirectories } from '@/types/api';
import { humanSize } from '@/components/sessionWorkbench/FileViewer';
import { filePinLabel, normalizePinPath, parentDirOf, useFilePins } from '@/stores/filePins';
import FilePreview from './FilePreview';

const ICON = { size: 14, strokeWidth: 1.5 } as const;

/**
 * 目录在前、文件在后；每一类里非隐藏在前、隐藏在后。
 */
function orderEntries(entries: FileEntry[]): FileEntry[] {
  const rank = (entry: FileEntry) => (entry.is_dir ? 0 : 1) + (entry.name.startsWith('.') ? 2 : 0);
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => rank(a.entry) - rank(b.entry) || a.index - b.index)
    .map(({ entry }) => entry);
}

const TREE_WIDTH_KEY = 'file-browser-tree-width';
const DEFAULT_TREE_WIDTH = 300;
const MIN_TREE_WIDTH = 240;
const MAX_TREE_WIDTH = 640;

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

/** 修改时间压成 `09-24 16:31`。 */
function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * 从当前目录往上的一条条。主目录底下的用 `~` 起头，主目录之外的从 `/` 起头。
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
  const { t, i18n } = useTranslation();
  const isZh = i18n.language?.startsWith('zh');

  const pins = useFilePins((s) => s.pins);
  const togglePin = useFilePins((s) => s.togglePin);
  const pendingTarget = useFilePins((s) => s.pendingTarget);
  const consumeTarget = useFilePins((s) => s.consumeTarget);
  const setActivePath = useFilePins((s) => s.setActivePath);

  const pinnedSet = useMemo(() => new Set(pins.map((p) => p.path)), [pins]);

  const [dir, setDir] = useState<string | null>(() => {
    const target = useFilePins.getState().pendingTarget;
    if (!target) return null;
    return target.is_dir ? target.path : parentDirOf(target.path);
  });
  const resolvedPath = useRef<string | null>(null);
  const [listing, setListing] = useState<FileListing | null>(null);
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
  const [query, setQuery] = useState('');
  const [showHidden, setShowHidden] = useState(false);

  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(() => new Set());
  const [dirChildren, setDirChildren] = useState<Record<string, FileEntry[]>>({});
  const [loadingDirs, setLoadingDirs] = useState<Set<string>>(() => new Set());
  const [activeDir, setActiveDir] = useState<string | null>(null);
  const expandedDirsRef = useRef<Set<string>>(expandedDirs);
  expandedDirsRef.current = expandedDirs;

  const [treeWidth, setTreeWidth] = useState<number>(readTreeWidth);

  useEffect(() => {
    let alive = true;
    getSystemDirectories()
      .then((dirs) => {
        if (alive) setSystemDirs(dirs);
      })
      .catch(() => {
        /* 取不到就少几个入口；服务端列目录时不认路径就自己回主目录 */
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
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
  const current = dir ?? listing?.path ?? '';
  const focusedDir =
    activeDir && (activeDir === current || activeDir.startsWith(`${current.replace(/\/+$/, '')}/`))
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
      /* 打不开时不打断人 */
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
        /* 剪贴板不可用 */
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
        /* 剪贴板不可用 */
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

  const visibleEntries = useMemo(() => {
    if (!listing) return [];
    const q = query.trim().toLowerCase();
    return listing.entries.filter((entry) => {
      if (!showHidden && !q && entry.name.startsWith('.')) return false;
      if (q) return entry.is_dir || entry.name.toLowerCase().includes(q);
      return true;
    });
  }, [listing, showHidden, query]);

  const renderTreeEntries = (parentPath: string, entries: FileEntry[], depth: number): React.ReactNode => {
    const cleanParent = parentPath.replace(/\/+$/, '');
    const q = query.trim().toLowerCase();
    const filtered = entries.filter((entry) => {
      if (!showHidden && !q && entry.name.startsWith('.')) return false;
      if (q) return entry.is_dir || entry.name.toLowerCase().includes(q);
      return true;
    });
    const ordered = orderEntries(filtered);
    return ordered.map((entry) => {
      const path = `${cleanParent}/${entry.name}`;
      const isExpanded = entry.is_dir && expandedDirs.has(path);
      const isDirLoading = entry.is_dir && loadingDirs.has(path);
      const active = !entry.is_dir && selected?.path === path;
      const isPinned = pinnedSet.has(path);
      const isRowCopied = copiedRowPath === path;
      const children = entry.is_dir ? dirChildren[path] : undefined;
      const modifiedText = shortTime(entry.modified);
      const hidden = entry.name.startsWith('.');

      return (
        <div key={path}>
          <div
            className={`group files-row ${active ? 'on font-medium' : ''} ${hidden ? 'hidden-item' : ''}`}
          >
            <button
              type="button"
              title={modifiedText ? `${path}\n${modifiedText}` : path}
              style={{ paddingLeft: `${depth * 16}px` }}
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
              className="flex min-w-0 flex-1 items-center gap-1.5 py-[1px] text-left text-[12.5px]"
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
              <span className={`shrink-0 ${hidden ? 'text-text-dim' : 'text-text-muted'}`}>
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
              <span className={`truncate ${hidden ? 'text-text-dim' : ''}`}>{entry.name}</span>
              <span className="min-w-[6px] flex-1" />
              {!entry.is_dir && entry.size !== null ? (
                <span className="shrink-0 font-mono text-[11px] text-text-dim">
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
                style={{ paddingLeft: `${18 + (depth + 1) * 16}px` }}
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
        meta={listing ? t('files.counting', { n: visibleEntries.length }) : undefined}
        secondary={
          <>
            {places.length > 0 && (
              <div className="ui-seg-group" role="group" aria-label={t('files.places.label')}>
                {places.map((place) => (
                  <button
                    key={place.key}
                    type="button"
                    onClick={() => go(place.path)}
                    title={place.path}
                    aria-pressed={current === place.path}
                    className={`ui-seg-pill ${current === place.path ? 'ui-seg-pill--active' : ''}`}
                    data-testid={`files-place-${place.key}`}
                  >
                    {place.label}
                  </button>
                ))}
              </div>
            )}
            <button
              type="button"
              className={`page-header-btn ${showHidden ? 'page-header-btn--pressed' : ''}`}
              onClick={() => setShowHidden((v) => !v)}
              aria-pressed={showHidden}
              data-testid="files-show-hidden"
            >
              {showHidden ? <Eye size={13} strokeWidth={1.5} /> : <EyeOff size={13} strokeWidth={1.5} />}
              <span>
                {t('files.showHidden', {
                  defaultValue: isZh ? '显示隐藏文件' : 'Show hidden',
                })}
              </span>
            </button>
            <button
              type="button"
              className="page-header-btn page-header-btn--icon page-header-btn--ghost"
              onClick={() => setReloadKey((k) => k + 1)}
              title={t('files.refresh')}
              aria-label={t('files.refresh')}
            >
              <RefreshCw size={14} strokeWidth={1.5} />
            </button>
          </>
        }
      />

      <div
        className="files-split"
        style={{ gridTemplateColumns: `${treeWidth}px minmax(0, 1fr)` }}
      >
        {/* 左栏：关键词过滤 · 向上与 Pin · 目录树（目录优先） */}
        <div className="files-tree-col relative">
          <div className="files-tree-top">
            <div className="ui-search-box !h-7 !w-full">
              <Search size={13} className="ui-search-box-icon" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('files.searchPlaceholder', { defaultValue: 'Search files...' })}
                aria-label={t('files.searchPlaceholder', { defaultValue: 'Search files...' })}
              />
              {query && (
                <button
                  type="button"
                  className="ui-search-box-clear"
                  onClick={() => setQuery('')}
                  aria-label={t('common.clear')}
                >
                  <X size={13} />
                </button>
              )}
            </div>
            <div className="flex items-center gap-1">
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
              <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-text-muted" title={current}>
                {home && current.startsWith(home)
                  ? `~${current.slice(home.length) || ''}`
                  : current || '/'}
              </span>
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
          </div>

          <div data-testid="file-tree-scroll" className="files-list">
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
            ) : listing && visibleEntries.length === 0 ? (
              <p className="px-3 py-8 text-center text-[12px] text-text-muted">{t('files.empty')}</p>
            ) : listing ? (
              renderTreeEntries(current, listing.entries, 0)
            ) : null}
          </div>

          <div
            role="separator"
            aria-orientation="vertical"
            onMouseDown={startResize}
            className="absolute top-0 right-0 bottom-0 w-[4px] cursor-col-resize hover:bg-border-strong"
          />
        </div>

        {/* 右栏：可点面包屑 + 选中文件预览 */}
        <div className="files-preview-col">
          {current ? (
            <div className="files-crumbs" aria-label={t('files.breadcrumbs', { defaultValue: 'Breadcrumbs' })}>
              {trail.map((node, i) => (
                <span key={node.path} className="flex shrink-0 items-center gap-1">
                  {i > 0 ? <ChevronRight size={11} className="text-text-dim" /> : null}
                  <button
                    type="button"
                    onClick={() => go(node.path)}
                    className={
                      i === trail.length - 1
                        ? 'font-medium text-text-primary'
                        : 'text-text-muted'
                    }
                  >
                    {node.label}
                  </button>
                </span>
              ))}
            </div>
          ) : null}

          {selected ? (
            <>
              <div className="flex h-10 shrink-0 items-center gap-2 border-b border-border-color bg-bg-primary px-3.5">
                <FileIcon size={14} className="shrink-0 text-text-muted" />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-secondary">
                  {selected.path}
                </span>
                {selected.size !== null && (
                  <span className="shrink-0 font-mono text-[11px] text-text-dim">
                    {humanSize(selected.size)}
                  </span>
                )}
                {selected.modified && (
                  <span className="shrink-0 font-mono text-[11px] text-text-dim">
                    {shortTime(selected.modified)}
                  </span>
                )}
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
              <div className="files-preview-body !p-0">
                <FilePreview
                  key={selected.path}
                  path={selected.path}
                  name={selected.name}
                  size={selected.size}
                />
              </div>
            </>
          ) : (
            <EmptyState Icon={Folder} title={t('files.noSelection')} />
          )}
        </div>
      </div>
    </>
  );
}
