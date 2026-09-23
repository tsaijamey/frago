/**
 * NewSessionModal — 从浏览器起一场会话，并且**由人来挑用哪个客户端**。
 *
 * 建出来的是一场**普通会话**，不是什么网页专用的东西：它跟着各家自己的规矩起，记录写到
 * 各家自己该去的地方，下一次扫描它就是左栏里一行普通会话——同一个详情面板、同一条发送
 * 路径、同一份数据。
 *
 * ## 对话框在问三件事，标题就得是这三句问话
 *
 * 从前三块的标题是「用哪个客户端」「起始目录」「第一句话」——每一句都在说这一格**装的
 * 是什么**，没有一句在说**人该据此拿什么主意**。第一次打开的人于是要自己去猜：client 是
 * 谁？为什么非要挑个目录？下面那个框是必填的吗？三格并排、字重相同、没有分隔，看上去
 * 像三道无来由的填空题。
 *
 * 现在三块的标题是三句并列的问话——「交给哪个 agent 跑」「在哪个项目里干活」「想让它做
 * 什么」——各自跟一句灰字说清挑错了会怎样，块与块之间拿一道分隔线断开。人从上往下读一
 * 遍就知道自己在做什么决定，不必先理解 frago 的内部构造。
 *
 * ## 客户端怎么挑：为什么是一排可换行的按钮，而不是下拉框
 *
 * 从前这里只会起 claude。人本机装着 codex、装着 opencode，一个都挑不到——不是有意的
 * 取舍，是这条路上根本没有"挑一家"这个概念。
 *
 * 补的时候要先想清楚一件事：**将来这个数字会长。** 所以三个候选形态各自摆一摆：
 *
 * - 下拉框。省地方，但把"本机现在有几家可用"这件事藏进了一次点击。这恰恰是人第一次
 *   打开这个对话框最想知道的一句话。
 * - 一排单选按钮。看得见，但没装的那几家要么占着位置、要么整个消失；后者会让人以为
 *   frago 不支持它。
 * - **一排可换行的按钮，能挑的在前，用不了的折在一句话后面。** 选的是这个。可用的通常
 *   只有一两家，一眼看完；将来接到八家十家也只是多换一行，不会把对话框撑爆。用不了的
 *   一个不丢，点开就看得见"为什么用不了"——是没装，还是记录读不进工作台。
 *
 * 名单一个字都不写死在这里，来自 `/api/workbench/agents`（见 `useAgentClients`）。
 * 前端再抄一份的话，接新家的人改完 driver 会发现界面上它根本不出现。
 *
 * ## 工作目录：最近用过的那几个之外还得有路
 *
 * 后端一直收这个参数，只是从前界面从没送过，于是浏览器起的会话全落在家目录。挑它正是
 * 这个对话框存在的另一半理由。
 *
 * 但从前能挑的只有"最近开过会话的那几个目录"，外加家目录。**第一次用 frago 的人那份清
 * 单是空的**，于是唯一的出路是照着记忆手打一整条绝对路径——打错一个字就落进一个空目
 * 录，而人当场看不出来。所以这里补了一条翻目录的路（`browseDirectories`）：一层一层点
 * 进去，停在哪一层就是选了哪一层，子目录多的时候还能打字筛。
 *
 * 翻目录与最近用过的是**同一块地方的两个面**，不是上下堆着的两份清单：对话框一共就这么
 * 高，两份都摊开会把第一句话那一块挤出屏幕。
 *
 * ## 第一句话可以带图，也可以不写
 *
 * 从前这里只收文字。人开一场会话十有八九是为了说"照着这张图改"，而那张图在这一步贴不
 * 进来——只能先随便打一句、等会话起来、再到中栏输入区补发一次，而第一句话恰恰是最需要
 * 它的那一句。三条路（粘贴、拖入、选文件）与中栏输入区共用同一份判据（`useAttachments`）
 * 和同一条展示条（`AttachmentStrip`）：同一个动作在两处得是同一个结果。
 *
 * 它一直都是可以留空的（有图就能建），但界面从来没说过这件事，看上去跟上面两格一样是
 * 必填。那句"可以留空"现在写在框底下。
 *
 * ## 创建之后：编号未必当场就有
 *
 * claude 接受由调用方指定编号，点完创建当场就知道这一场叫什么，直接跳进去。codex 与
 * opencode 的编号由它们自己分配，frago 要等会话起来后认领——那一段空窗如实说出来，
 * 由 `useSessionLaunch` 拿着把手去等（见 `waitForSession`）。假装编号已经有了，界面会
 * 跳进一场并不存在的会话，人看到一片空记录流，以为刚开的会话丢了。
 *
 * **这个对话框只管建，不管等。** 建出去之后它自己关掉，等待那一段由左栏的启动卡与中栏
 * 的启动面板接手——对话框继续挂在屏幕上会挡住新会话本身，而人此刻要看的正是它。
 */

import { useEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronRight,
  CornerLeftUp,
  Folder,
  FolderSearch,
  Home,
  Loader2,
  Plus,
} from 'lucide-react';
import Modal from '../ui/Modal';
import { browseDirectories, getSystemDirectories } from '../../api/client';
import { getRecentDirectories, addRecentDirectory } from '../../utils/recentDirectories';
import AttachmentStrip from '@/components/ui/AttachmentStrip';
import { MAX_ATTACHMENTS, useAttachments } from '@/hooks/useAttachments';
import type { DirectoryListing } from '@/types/api';
import {
  createSession,
  pickDefaultAgent,
  rememberLastAgent,
  useAgentClients,
  agentReasonText,
  type PendingLaunch,
} from '@/hooks/useAgentClients';

interface NewSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  /**
   * 建出去了。第二个参数是人刚打的那第一句话——对话框一关它就没别的地方存了，而接下来
   * 那十几秒的等待要靠它告诉人"你在等的是哪一句"。
   */
  onCreated: (launch: PendingLaunch, text: string) => void;
}

interface DirChoice {
  path: string;
  hint?: string;
}

/** 一块的标题与灰字说明。三块长得一模一样，人才看得出它们是三个并列的问题。 */
function SectionHeading({ id, title, hint }: { id: string; title: string; hint: string }) {
  return (
    <div className="flex flex-col gap-1">
      <h4 id={id} className="text-[13px] font-semibold text-[var(--text-primary)]">
        {title}
      </h4>
      <p className="text-[11px] leading-relaxed text-[var(--text-muted)]">{hint}</p>
    </div>
  );
}

export default function NewSessionModal({ isOpen, onClose, onCreated }: NewSessionModalProps) {
  const { t } = useTranslation();
  const [choices, setChoices] = useState<DirChoice[]>([]);
  const [dir, setDir] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [agent, setAgent] = useState<string | null>(null);
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const { images, documents, addFiles, removeImage, removeDocument, clear, count } =
    useAttachments();
  const filePicker = useRef<HTMLInputElement>(null);
  /** 连点几层，回来的顺序未必是点下去的顺序。只认最后一次点的那一层。 */
  const browseSeq = useRef(0);

  const clients = useAgentClients(isOpen);
  const selectable = useMemo(() => clients.agents.filter((a) => a.selectable), [clients.agents]);
  const unavailable = useMemo(() => clients.agents.filter((a) => !a.selectable), [clients.agents]);
  const chosen = useMemo(
    () => selectable.find((a) => a.agent_type === agent) ?? null,
    [selectable, agent]
  );

  useEffect(() => {
    if (!isOpen) return;
    setText('');
    setError(null);
    setCreating(false);
    setShowUnavailable(false);
    setBrowsing(false);
    setListing(null);
    setFilter('');
    clear();

    let cancelled = false;

    const load = async () => {
      const recent = getRecentDirectories().map((r) => ({ path: r.path }));
      let system: DirChoice[] = [];

      try {
        const dirs = await getSystemDirectories();
        if (dirs.home) system.push({ path: dirs.home, hint: 'home' });
        if (dirs.cwd && dirs.cwd !== dirs.home) system.push({ path: dirs.cwd, hint: 'cwd' });
      } catch {
        // Directory service unreachable — recents alone still allow a pick,
        // and the free-text field always works.
        system = [];
      }

      const seen = new Set(recent.map((r) => r.path));
      const merged = [...recent, ...system.filter((s) => !seen.has(s.path))];

      if (cancelled) return;
      setChoices(merged);
      setDir((prev) => prev || merged[0]?.path || '');
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen, clear]);

  /**
   * 清单一到就把默认那一家选上。人上次挑的优先——换机位是有惯性的。
   *
   * 只在还没选过时落笔（`prev ?? …`）：清单重取一次就把人刚点的那一家改回默认，
   * 是这类"自动选中"最常见的坏法。
   */
  useEffect(() => {
    if (!clients.agents.length) return;
    setAgent((prev) => prev ?? pickDefaultAgent(clients.agents, clients.fallbackDefault));
  }, [clients.agents, clients.fallbackDefault]);

  /**
   * 翻进某一层。**停在哪一层就是选了哪一层**——翻到了想要的目录还得再点一次"就用这个"，
   * 是白白多出来的一步，而且那一步没做的人会以为自己已经选好了。
   */
  const openFolder = async (path: string) => {
    const seq = ++browseSeq.current;
    setBrowseLoading(true);
    try {
      const next = await browseDirectories(path);
      if (seq !== browseSeq.current) return;
      setListing(next);
      setFilter('');
      setDir(next.path);
    } catch {
      // 读不动就停在原地：清单整个消失，人会以为这条路根本走不通。
      if (seq === browseSeq.current) setListing(null);
    } finally {
      if (seq === browseSeq.current) setBrowseLoading(false);
    }
  };

  const toggleBrowsing = () => {
    const next = !browsing;
    setBrowsing(next);
    if (next) void openFolder(dir.trim());
  };

  const visibleEntries = useMemo(() => {
    const entries = listing?.entries ?? [];
    const needle = filter.trim().toLowerCase();
    return needle ? entries.filter((e) => e.name.toLowerCase().includes(needle)) : entries;
  }, [listing, filter]);

  // 只有图、一个字没打也算数：人截了张图想说"看这个"，逼他再补一句废话没有道理。
  // 与中栏输入区同一条判据，服务端那边也认这一档。
  const canSubmit =
    !creating && !!chosen && dir.trim().length > 0 && (text.trim().length > 0 || count > 0);

  /** 截图粘贴进来的是文件而不是文字，拦下来当附件，别让它变成一串乱码落进文本框。 */
  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = e.clipboardData?.files;
    if (!files || files.length === 0) return;
    e.preventDefault();
    void addFiles(files);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;
    e.preventDefault();
    void addFiles(files);
  };

  const handleCreate = async () => {
    if (!canSubmit || !chosen) return;
    setError(null);
    setCreating(true);
    try {
      const first = text.trim();
      const launch = await createSession({
        agent: chosen.agent_type,
        cwd: dir.trim(),
        text: first,
        images: images.map((im) => im.dataUrl),
        documents: documents.map((d) => ({ name: d.name, data: d.dataUrl })),
      });
      rememberLastAgent(chosen.agent_type);
      addRecentDirectory(dir.trim());
      onCreated(launch, first);
      onClose();
    } catch (e) {
      // 建不起来就**留在对话框里**并把话原样摆出来。关掉再弹一句提示，人打的那段话
      // 就没了，还得从头再敲一遍。
      setError(e instanceof Error ? e.message : t('workbench.errors.createFailedPlain'));
      setCreating(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('workbench.newSession.title')}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <SectionHeading
            id="new-session-client"
            title={t('workbench.newSession.clientLabel')}
            hint={t('workbench.newSession.clientHint')}
          />

          {clients.loading && !clients.agents.length ? (
            <p className="text-[11px] text-[var(--text-muted)]">
              {t('workbench.newSession.probing')}
            </p>
          ) : clients.error ? (
            <p className="text-xs text-[var(--accent-error)] break-words">{clients.error}</p>
          ) : !selectable.length ? (
            <p className="text-xs text-[var(--accent-error)] break-words">
              {t('workbench.newSession.noneAvailable')}
            </p>
          ) : (
            <div
              className="flex flex-wrap gap-1.5"
              role="radiogroup"
              aria-labelledby="new-session-client"
            >
              {selectable.map((c) => (
                <button
                  key={c.agent_type}
                  type="button"
                  role="radio"
                  aria-checked={c.agent_type === agent}
                  data-testid={`agent-${c.agent_type}`}
                  onClick={() => setAgent(c.agent_type)}
                  title={c.path ?? undefined}
                  className={`rounded-full px-3 py-1 text-[12px] transition-colors ${
                    c.agent_type === agent
                      ? 'bg-[var(--accent-primary-10)] text-[var(--accent-primary)] ring-1 ring-[var(--accent-primary)]'
                      : 'bg-[var(--bg-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
                  }`}
                >
                  {c.display_name}
                </button>
              ))}
            </div>
          )}

          {/* 编号要等认领的那两家，把这段空窗先说在前头——点完创建之后才发现要等，
              人会以为卡住了。 */}
          {chosen?.id_origin === 'claimed' ? (
            <p className="text-[11px] text-[var(--text-muted)] -mt-0.5">
              {t('workbench.newSession.claimedHint', { name: chosen.display_name })}
            </p>
          ) : null}

          {/* 用不了的那几家不藏：藏起来人只会以为 frago 不支持它，而真相往往只是没装。 */}
          {unavailable.length ? (
            <div className="flex flex-col gap-1">
              <button
                type="button"
                onClick={() => setShowUnavailable((v) => !v)}
                aria-expanded={showUnavailable}
                data-testid="toggle-unavailable-agents"
                className="flex items-center gap-1 self-start text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
              >
                {showUnavailable ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <span>
                  {t('workbench.newSession.unavailableCount', { n: unavailable.length })}
                </span>
              </button>
              {showUnavailable
                ? unavailable.map((c) => (
                    <p
                      key={c.agent_type}
                      className="pl-4 text-[11px] leading-relaxed text-[var(--text-muted)]"
                    >
                      <span className="text-[var(--text-secondary)]">{c.display_name}</span>
                      {' — '}
                      {agentReasonText(c.reason)}
                    </p>
                  ))
                : null}
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 border-t border-[var(--border-color)] pt-4">
          <SectionHeading
            id="new-session-cwd"
            title={t('workbench.newSession.cwdLabel')}
            hint={t('workbench.newSession.cwdHint')}
          />

          {/* 翻目录和最近用过的是同一块地方的两个面：两份清单一起摊开，第一句话那一块
              会被挤出屏幕。 */}
          <div className="flex items-center justify-between gap-2">
            {/* 翻目录时这一行是人现在停在哪一层，**路径照原样印**——大写化会把
                `/Users/frago` 印成 `/USERS/FRAGO`，那是一条这台机器上并不存在的路径。
                只有"最近用过"那个小标题才走通栏小标题那套大写字样。 */}
            {browsing ? (
              <span
                title={listing?.path ?? ''}
                className="truncate font-mono text-[11px] text-[var(--text-secondary)]"
              >
                {listing?.path ?? ''}
              </span>
            ) : (
              <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
                {t('workbench.newSession.cwdRecent')}
              </span>
            )}
            <button
              type="button"
              data-testid="toggle-browse-dirs"
              onClick={toggleBrowsing}
              aria-expanded={browsing}
              className="flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
            >
              <FolderSearch size={13} strokeWidth={1.5} />
              {browsing
                ? t('workbench.newSession.cwdBrowseClose')
                : t('workbench.newSession.cwdBrowse')}
            </button>
          </div>

          {browsing ? (
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="browse-up"
                  disabled={!listing?.parent || browseLoading}
                  onClick={() => listing?.parent && void openFolder(listing.parent)}
                  title={t('workbench.newSession.cwdUp')}
                  aria-label={t('workbench.newSession.cwdUp')}
                  className="shrink-0 rounded-md p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] disabled:opacity-40"
                >
                  <CornerLeftUp size={14} strokeWidth={1.5} />
                </button>
                <input
                  type="text"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={t('workbench.newSession.cwdFilter')}
                  data-testid="browse-filter"
                  className="min-w-0 flex-1 rounded-md border border-[var(--border-color)] bg-[var(--bg-subtle)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
                />
              </div>

              <div className="flex max-h-36 flex-col gap-1 overflow-y-auto" data-testid="browse-list">
                {browseLoading && !listing ? (
                  <p className="px-3 py-2 text-[11px] text-[var(--text-muted)]">
                    {t('workbench.newSession.cwdLoading')}
                  </p>
                ) : visibleEntries.length ? (
                  visibleEntries.map((e) => (
                    <button
                      key={e.path}
                      type="button"
                      onClick={() => void openFolder(e.path)}
                      className="flex items-center gap-2 rounded-md px-3 py-2 text-left text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)]"
                    >
                      <Folder size={14} className="shrink-0" />
                      <span className="truncate font-mono text-xs">{e.name}</span>
                      <ChevronRight size={12} className="ml-auto shrink-0 opacity-50" />
                    </button>
                  ))
                ) : (
                  <p className="px-3 py-2 text-[11px] text-[var(--text-muted)]">
                    {t('workbench.newSession.cwdEmpty')}
                  </p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex max-h-36 flex-col gap-1 overflow-y-auto">
              {choices.map((c) => (
                <button
                  key={c.path}
                  type="button"
                  onClick={() => setDir(c.path)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-md text-left transition-colors ${
                    c.path === dir
                      ? 'bg-[var(--accent-primary-10)] text-[var(--accent-primary)]'
                      : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                  }`}
                >
                  {c.hint === 'home' ? (
                    <Home size={14} className="shrink-0" />
                  ) : (
                    <Folder size={14} className="shrink-0" />
                  )}
                  <span className="truncate font-mono text-xs">{c.path}</span>
                  {c.hint && (
                    <span className="ml-auto shrink-0 text-[10px] text-[var(--text-muted)]">
                      {c.hint}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}

          <label
            htmlFor="new-session-cwd-path"
            className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]"
          >
            {t('workbench.newSession.cwdPathLabel')}
          </label>
          <input
            id="new-session-cwd-path"
            type="text"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            placeholder="/absolute/path"
            className="bg-[var(--bg-subtle)] border border-[var(--border-color)] rounded-md px-3 py-2 text-xs font-mono text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
          />
        </div>

        {/* 第一句话这一块收图片与文档，三条路（粘贴、拖入、选文件）与中栏输入区完全相同。
            人开一场会话往往就是为了说"照着这张图改"，从前这里只收文字，那张图得等会话
            起来之后再补发一次，而第一句话才是最需要它的那一句。 */}
        <div
          className="flex flex-col gap-2 border-t border-[var(--border-color)] pt-4"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
        >
          <SectionHeading
            id="new-session-first"
            title={t('workbench.newSession.firstMessage')}
            hint={t('workbench.newSession.firstMessageOptional')}
          />

          <AttachmentStrip
            images={images}
            documents={documents}
            onRemoveImage={removeImage}
            onRemoveDocument={removeDocument}
            idPrefix="new-session"
          />

          <textarea
            value={text}
            data-testid="new-session-input"
            aria-labelledby="new-session-first"
            onChange={(e) => setText(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                void handleCreate();
              }
            }}
            rows={3}
            placeholder={t('workbench.newSession.firstMessagePlaceholder')}
            className="resize-none bg-[var(--bg-subtle)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
          />

          <input
            ref={filePicker}
            type="file"
            multiple
            hidden
            data-testid="new-session-file"
            onChange={(e) => {
              if (e.target.files) void addFiles(e.target.files);
              e.target.value = '';
            }}
          />
          {/* 从前这是一行灰字，看不出能点。描个边，它才像个按钮。 */}
          <button
            type="button"
            data-testid="new-session-pick"
            disabled={count >= MAX_ATTACHMENTS}
            onClick={() => filePicker.current?.click()}
            className="flex items-center gap-1.5 self-start rounded-md border border-[var(--border-color)] px-2.5 py-1.5 text-[11px] text-[var(--text-secondary)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] disabled:opacity-40"
          >
            <Plus size={13} strokeWidth={1.5} />
            {t('workbench.newSession.attach')}
          </button>
        </div>

        {error && (
          <p className="text-xs text-[var(--accent-error)] break-words">
            {t('workbench.newSession.createFailed', { reason: error })}
          </p>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-color)] pt-4">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 rounded-md text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            {t('workbench.newSession.cancel')}
          </button>
          <button
            type="button"
            onClick={() => void handleCreate()}
            disabled={!canSubmit}
            className="flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold bg-[var(--accent-primary)] text-[var(--text-on-accent)] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {creating ? <Loader2 size={13} className="animate-spin" /> : null}
            {t('workbench.newSession.create')}
          </button>
        </div>
      </div>
    </Modal>
  );
}
