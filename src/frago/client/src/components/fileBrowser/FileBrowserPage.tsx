/**
 * FileBrowserPage — 文件：本机的目录树，左边列，右边看。
 *
 * 从前想看会话里提到的那份文件，得把路径复制出来，去系统的文件浏览器里粘一遍，再双击。
 * 这一页把那一趟搬进界面：左边一条目录一条目录地走，右边选中哪一份就摆哪一份。
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
  ChevronRight,
  Copy,
  Check,
  CornerLeftUp,
  File as FileIcon,
  Folder,
  FolderOpen,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import * as api from '@/api';
// 主目录与工作目录那一条不走 `@/api` 的双模入口：它只有 HTTP 这一边有（pywebview 那边
// 没有对应的方法），会话页取默认目录时也是直接从这里进。
import { getSystemDirectories } from '@/api/client';
import PageHeader from '@/components/layout/PageHeader';
import type { FileEntry, FileListing, SystemDirectories } from '@/types/api';
import { humanSize } from '@/components/sessionWorkbench/FileViewer';
import FilePreview from './FilePreview';

const ICON = { size: 14, strokeWidth: 1.5 } as const;

/** 修改时间压成 `09-24 16:31`。带年份的那一档在这一栏里放不下，人多数时候也不看。 */
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

export default function FileBrowserPage() {
  const { t } = useTranslation();

  /**
   * 想去哪个目录。null 表示「还没指过」——第一次由服务端回主目录。
   *
   * **服务端解析出来的那个路径不写回这里。** 写回来的话它就是这条请求的依赖，一次挂载
   * 会变成两次请求，中间那一下列表还会闪回「读这个目录…」——顺序反过来才对：这里存人
   * 指的那一个，摆出来用服务端回的那一个（`current`）。
   */
  const [dir, setDir] = useState<string | null>(null);
  /** 服务端上一次解析出来的那个目录，给「重读这一颗按钮」用。 */
  const resolvedPath = useRef<string | null>(null);
  const [listing, setListing] = useState<FileListing | null>(null);
  /** 主目录与「这台机器上 frago 正在哪儿干活」，拿它俩摆在最上面当入口。 */
  const [systemDirs, setSystemDirs] = useState<SystemDirectories | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<FileEntry | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [copied, setCopied] = useState(false);

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
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [dir, reloadKey]);

  const go = useCallback((next: string) => {
    setSelected(null);
    setDir(next);
  }, []);

  const home = systemDirs?.home ?? null;
  // 人已经指了哪儿就用哪儿（面包屑立刻跟着走），还没指过就用服务端刚回的那一个。
  const current = dir ?? listing?.path ?? '';

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

  const trail = crumbs(current, home);

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
        {/* 左栏：去哪儿 · 现在在哪 · 这儿有什么 */}
        <div className="flex w-[320px] shrink-0 flex-col border-r border-border-color bg-bg-secondary">
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
            {/* 面包屑在窄栏里会很长，横向滚而不是折行：折行会让路径读起来断成两截。 */}
            <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
          </div>

          <div className="min-h-0 flex-1 overflow-auto py-1">
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
            ) : (
              listing?.entries.map((entry) => {
                const path = `${current.replace(/\/+$/, '')}/${entry.name}`;
                const active = !entry.is_dir && selected?.name === entry.name;
                return (
                  <button
                    key={entry.name}
                    type="button"
                    title={`${path}\n${entry.modified}`}
                    onClick={() => {
                      if (entry.is_dir) go(path);
                      else setSelected(entry);
                    }}
                    onDoubleClick={() => {
                      if (!entry.is_dir) reveal(path);
                    }}
                    className={`flex w-full items-center gap-2 px-3 py-[5px] text-left text-[12px] transition-colors duration-150 ${
                      active
                        ? 'bg-bg-active font-medium text-text-primary'
                        : 'text-text-secondary hover:bg-bg-hover'
                    }`}
                  >
                    <span className="shrink-0 text-text-muted">
                      {entry.is_dir ? <Folder {...ICON} /> : <FileIcon {...ICON} />}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{entry.name}</span>
                    <span className="shrink-0 font-mono text-[10.5px] text-text-dim">
                      {entry.is_dir ? '' : entry.size === null ? '' : humanSize(entry.size)}
                    </span>
                    <span className="shrink-0 font-mono text-[10.5px] text-text-dim">
                      {shortTime(entry.modified)}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* 右栏：选中的那一份 */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-bg-base">
          {selected ? (
            <>
              <div className="flex h-11 shrink-0 items-center gap-2 border-b border-border-color bg-bg-primary px-3">
                <FileIcon size={14} className="shrink-0 text-text-muted" />
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-secondary">
                  {`${current.replace(/\/+$/, '')}/${selected.name}`}
                </span>
                <button
                  type="button"
                  onClick={() => copyPath(`${current.replace(/\/+$/, '')}/${selected.name}`)}
                  title={t('files.copyPath')}
                  aria-label={t('files.copyPath')}
                  className="inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                >
                  {copied ? <Check size={14} className="text-accent-primary" /> : <Copy size={14} />}
                </button>
                <button
                  type="button"
                  onClick={() => reveal(`${current.replace(/\/+$/, '')}/${selected.name}`)}
                  title={t('files.reveal')}
                  aria-label={t('files.reveal')}
                  className="inline-flex h-[24px] w-[24px] shrink-0 items-center justify-center rounded-[6px] text-text-muted hover:bg-bg-hover hover:text-text-primary"
                >
                  <FolderOpen size={14} />
                </button>
              </div>
              <div className="min-h-0 flex-1">
                <FilePreview
                  key={`${current}/${selected.name}`}
                  path={`${current.replace(/\/+$/, '')}/${selected.name}`}
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
