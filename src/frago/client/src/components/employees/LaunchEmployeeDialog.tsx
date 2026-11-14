/**
 * 点员工卡片 → 起一场带着这个员工业务语境的新会话。
 *
 * ## 这个窗在回答一句话：「这一场会带着什么起来」
 *
 * 员工页存在的全部意义，是让人不必每开一场会话都重述「我是谁、我手上有哪些数据、用哪套
 * 方法」。那句话是服务端拼的（`build_business_context_block`），人从来没亲眼见过它长什么样
 * ——只知道有这么回事。所以这里把那**段原文原样摆出来**（可展开的「自动带入业务语境」），
 * 连同纳管目录的统计。看得见，才敢信。
 *
 * ## 复用成熟的会话启动管线（`PromptComposerBox` + 目录浏览 + `useSessionLaunch`）
 *
 * 1. 输入盒直接复用会话工作台统一的 `PromptComposerBox`：天然支持截图粘贴（兼容 `files` 与
 *    `items` 两种剪贴板载体，并在弹窗容器层兜底粘贴）、拖拽文件、点击选附件、行首 `/` 挑
 *    skill、文本框自动增高与 `Cmd/Ctrl + Enter` 发送；
 * 2. 工作目录默认取员工那一栏（`cwd`），岗位没配就取 `~/.frago`，并复用工作台同款目录树浏览；
 * 3. 点下「开始对话」调完 `createSession` 后**立即交由会话工作台 `useSessionLaunch` 接手**
 *    （左栏启动卡 + 中栏两步启动面板 `SessionLaunchPanel`），不再把人困在模态弹窗里阻塞空等。
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  ChevronRight,
  CornerLeftUp,
  Folder,
  FolderSearch,
  Info,
  Sparkles,
} from 'lucide-react';
import DialogShell from './DialogShell';
import AttachmentStrip from '@/components/ui/AttachmentStrip';
import { useAttachments } from '@/hooks/useAttachments';
import { modKey } from '@/hooks/usePlatform';
import { browseDirectories } from '@/api/client';
import { useDataStore } from '@/stores/dataStore';
import type { DirectoryListing, SkillItem } from '@/types/api';
import { employeeInitials, kernelLabel, resolveEmployeeColor } from './employeeMeta';
import { fetchEmployee, type EmployeeDetail, type EmployeePost } from '@/hooks/useEmployees';
import {
  agentReasonText,
  createSession,
  pickDefaultAgent,
  rememberLastAgent,
  useAgentClients,
  type PendingLaunch,
} from '@/hooks/useAgentClients';
import { addRecentDirectory } from '@/utils/recentDirectories';
import { withTilde } from '@/components/sessionWorkbench/filePaths';
import PromptComposerBox, {
  extractClipboardFiles,
} from '@/components/sessionWorkbench/PromptComposerBox';

const DEFAULT_CWD = '~/.frago';

interface LaunchEmployeeDialogProps {
  /** 点的是哪个员工。null 表示这个窗没开着。 */
  post: EmployeePost | null;
  onClose: () => void;
  /**
   * 会话建出去了，把把手（`PendingLaunch`）与第一句话交回宿主，由会话工作台的
   * `useSessionLaunch`（`SessionLaunchPanel` + `SessionRail`）统一接管认领与预热进度。
   */
  onCreated: (launch: PendingLaunch, text: string) => void;
}

export default function LaunchEmployeeDialog({
  post,
  onClose,
  onCreated,
}: LaunchEmployeeDialogProps) {
  const { t } = useTranslation();
  const open = post !== null;

  const [detail, setDetail] = useState<EmployeeDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [ctxOpen, setCtxOpen] = useState(false);
  const [agent, setAgent] = useState<string | null>(null);
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [cwd, setCwd] = useState(DEFAULT_CWD);
  const [browsing, setBrowsing] = useState(false);
  const [listing, setListing] = useState<DirectoryListing | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [text, setText] = useState('');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const browseSeq = useRef(0);

  const allSkills = useDataStore((s) => s.skills);
  const { images, documents, addFiles, removeImage, removeDocument, clear, count } =
    useAttachments();

  const addSkill = useCallback((skill: SkillItem) => {
    setSkills((prev) => (prev.some((s) => s.name === skill.name) ? prev : [...prev, skill]));
  }, []);
  const removeSkill = useCallback((name: string) => {
    setSkills((prev) => prev.filter((s) => s.name !== name));
  }, []);

  const clients = useAgentClients(open);
  const selectable = useMemo(() => clients.agents.filter((a) => a.selectable), [clients.agents]);
  const unavailable = useMemo(() => clients.agents.filter((a) => !a.selectable), [clients.agents]);
  const chosen = useMemo(
    () => selectable.find((a) => a.agent_type === agent) ?? null,
    [selectable, agent]
  );

  // 换一张卡片就把整块重置。
  useEffect(() => {
    if (!post) return;
    setDetail(null);
    setDetailError(null);
    setCtxOpen(false);
    setAgent(null);
    setShowUnavailable(false);
    setCwd(post.cwd || DEFAULT_CWD);
    setBrowsing(false);
    setListing(null);
    setFilter('');
    setText('');
    setSkills(
      (post.skills ?? []).map((name) => {
        const matched = allSkills.find((s) => s.name === name);
        return matched ?? { name, description: '', file_path: '' };
      })
    );
    setError(null);
    setCreating(false);
    clear();
  }, [post, clear, allSkills]);

  // 详情（含语境原文与纳管目录）只在窗开着时取一次。
  useEffect(() => {
    if (!post) return;
    let alive = true;
    fetchEmployee(post.member_post_id)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setDetailError(e instanceof Error ? e.message : t('employees.errors.detailFailedPlain'));
      });
    return () => {
      alive = false;
    };
  }, [post, t]);

  /**
   * 默认选哪家：员工自己那一栏优先，它在清单里挑不了就退回 `pickDefaultAgent`。
   */
  useEffect(() => {
    if (!post || !clients.agents.length) return;
    setAgent((prev) => {
      if (prev) return prev;
      const own = clients.agents.find((a) => a.agent_type === post.agent_kernel && a.selectable);
      return own?.agent_type ?? pickDefaultAgent(clients.agents, clients.fallbackDefault);
    });
  }, [post, clients.agents, clients.fallbackDefault]);

  const openFolder = async (path: string) => {
    const seq = ++browseSeq.current;
    setBrowseLoading(true);
    try {
      const next = await browseDirectories(path);
      if (seq !== browseSeq.current) return;
      setListing(next);
      setFilter('');
      setCwd(next.path);
    } catch {
      if (seq === browseSeq.current) setListing(null);
    } finally {
      if (seq === browseSeq.current) setBrowseLoading(false);
    }
  };

  const toggleBrowsing = () => {
    const next = !browsing;
    setBrowsing(next);
    if (next) void openFolder(cwd.trim() || post?.cwd || DEFAULT_CWD);
  };

  const visibleEntries = useMemo(() => {
    const entries = listing?.entries ?? [];
    const needle = filter.trim().toLowerCase();
    return needle ? entries.filter((e) => e.name.toLowerCase().includes(needle)) : entries;
  }, [listing, filter]);

  const ctx = detail?.business_context_block ?? '';
  const slots = detail?.managed_data.data_slots ?? [];
  const folderCount = slots.length || post?.data_summary.slot_count || 0;
  const entryCount =
    slots.reduce((n, s) => n + s.total_count, 0) || post?.data_summary.entry_count || 0;

  const defaultSkillCount = post?.skills?.length ?? 0;
  const canSubmit =
    !creating &&
    !!chosen &&
    (text.trim().length > 0 || count > 0 || skills.length > defaultSkillCount);

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;
    e.preventDefault();
    void addFiles(files);
  };

  const handleContainerPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    if (e.defaultPrevented) return;
    const extracted = extractClipboardFiles(e.clipboardData);
    if (extracted.length === 0) return;
    e.preventDefault();
    void addFiles(e.clipboardData?.files?.length ? e.clipboardData.files : extracted);
  };

  /**
   * 建这一场，并立即把 `PendingLaunch` 交给会话工作台的 `useSessionLaunch` 接手。
   * 对话框只管建、不管等：认领编号（agy / codex / opencode）与预热进度统一由会话页中栏的
   * `SessionLaunchPanel` 与左栏启动卡展示。
   */
  const handleCreate = async () => {
    if (!post || !chosen || !canSubmit) return;
    setError(null);
    setCreating(true);

    try {
      const first = text.trim();
      const launch = await createSession({
        agent: chosen.agent_type,
        cwd: cwd.trim(),
        text: first,
        images: images.map((im) => im.dataUrl),
        documents: documents.map((d) => ({ name: d.name, data: d.dataUrl })),
        skills: skills.map((s) => s.name),
        employee: post.member_post_id,
      });
      rememberLastAgent(chosen.agent_type);
      if (cwd.trim()) addRecentDirectory(cwd.trim());

      onCreated(
        {
          ...launch,
          employee_id: post.member_post_id,
          employee_title: post.title,
          employee_color: resolveEmployeeColor(post.color, post.member_post_id),
        },
        first
      );
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('employees.launch.createFailedPlain'));
      setCreating(false);
    }
  };

  if (!post) return null;

  return (
    <DialogShell
      title={t('employees.launch.title', { name: post.title })}
      onClose={onClose}
      width={600}
      closable={!creating}
    >
      <div
        className="flex flex-col gap-3"
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onPaste={handleContainerPaste}
      >
        {/* 这个员工是谁：缩写 + 一行职责 + 内核。 */}
        <div
          className="flex items-center gap-2.5 rounded-[8px] border border-border-color bg-bg-secondary px-2.5 py-2"
          data-emp-color={resolveEmployeeColor(post.color, post.member_post_id)}
        >
          <span
            className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-[6px] border font-mono text-[11px] font-semibold"
            style={{
              background: 'var(--emp-bg, var(--bg-primary))',
              color: 'var(--emp-fg, var(--text-primary))',
              borderColor: 'var(--emp-border, var(--border-color))',
            }}
          >
            {employeeInitials(post.member_post_id)}
          </span>
          <span className="min-w-0 flex-1 truncate text-[13px] text-text-secondary">
            {post.description || post.work_scope}
          </span>
          <span className="shrink-0 rounded-[4px] border border-border-color bg-bg-hover px-1.5 font-mono text-[11px] text-text-secondary">
            {kernelLabel(post.agent_kernel)}
          </span>
        </div>

        {/* 自动带入的业务语境：平时收成一行摘要，点开看服务端拼出来的原文 */}
        <div className="flex-shrink-0 overflow-hidden rounded-[8px] border border-border-color bg-bg-secondary">
          <button
            type="button"
            className="flex h-8 w-full min-w-0 items-center gap-2 px-2.5 text-left transition-colors hover:bg-bg-hover"
            onClick={() => setCtxOpen((v) => !v)}
            aria-expanded={ctxOpen}
            data-testid="employee-context-toggle"
          >
            {ctxOpen ? (
              <ChevronDown size={13} className="shrink-0 text-text-muted" />
            ) : (
              <ChevronRight size={13} className="shrink-0 text-text-muted" />
            )}
            <Sparkles size={13} className="shrink-0 text-text-muted" />
            <span className="shrink-0 text-[12px] font-semibold text-text-primary">
              {t('employees.launch.contextTitle')}
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px] text-text-muted">
              {detailError
                ? t('employees.launch.contextFailed')
                : t('employees.launch.contextSummary', {
                    folders: folderCount,
                    entries: entryCount,
                    domains: detail?.managed_data.knowledge_domains.length ?? 0,
                    recipes: detail?.managed_data.recipes.length ?? 0,
                  })}
            </span>
            <span className="shrink-0 text-[12px] text-text-secondary">
              {ctxOpen ? t('employees.launch.contextHide') : t('employees.launch.contextPreview')}
            </span>
          </button>

          {ctxOpen ? (
            <div className="border-t border-border-color px-2.5 pb-2.5">
              {ctx ? (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words pt-2 font-mono text-[11px] leading-[1.55] text-text-secondary">
                  {ctx}
                </pre>
              ) : (
                <p className="pt-2 text-[12px] text-text-muted">
                  {detailError ?? t('employees.launch.contextLoading')}
                </p>
              )}
            </div>
          ) : null}
        </div>

        {/* 交给哪个内核跑 */}
        <div className="fgrp">
          <label>{t('employees.launch.kernelLabel')}</label>
          {clients.loading && !clients.agents.length ? (
            <p className="text-[12px] text-text-muted">{t('employees.launch.kernelProbing')}</p>
          ) : clients.error ? (
            <p className="break-words text-[12px] text-accent-error">{clients.error}</p>
          ) : !selectable.length ? (
            <p className="break-words text-[12px] text-accent-error">
              {t('employees.launch.kernelNone')}
            </p>
          ) : (
            <div
              className="flex flex-wrap items-center gap-1.5"
              role="radiogroup"
              aria-label={t('employees.launch.kernelLabel')}
            >
              {selectable.map((c) => {
                const selected = c.agent_type === agent;
                return (
                  <button
                    key={c.agent_type}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    data-testid={`employee-kernel-${c.agent_type}`}
                    onClick={() => setAgent(c.agent_type)}
                    title={c.path ?? undefined}
                    className={`inline-flex h-7 items-center gap-1.5 rounded-[8px] border px-[11px] text-[13px] transition-colors ${
                      selected
                        ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] font-medium text-text-primary'
                        : 'border-border-color bg-bg-secondary text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        selected ? 'bg-accent-primary' : 'bg-text-dim'
                      }`}
                    />
                    {c.display_name}
                  </button>
                );
              })}

              {unavailable.length ? (
                <button
                  type="button"
                  onClick={() => setShowUnavailable((v) => !v)}
                  aria-expanded={showUnavailable}
                  data-testid="employee-toggle-unavailable-agents"
                  className="inline-flex h-6 items-center gap-1 rounded-[6px] px-2 text-[12px] text-text-muted transition-colors hover:bg-bg-hover hover:text-text-secondary"
                >
                  {showUnavailable ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  <span>
                    {t('workbench.newSession.unavailableCount', { n: unavailable.length })}
                  </span>
                </button>
              ) : null}
            </div>
          )}

          {chosen && post.agent_kernel && chosen.agent_type !== post.agent_kernel ? (
            <p className="hint">
              {t('employees.launch.kernelSwitched', {
                wanted: kernelLabel(post.agent_kernel),
                using: chosen.display_name,
                reason:
                  agentReasonText(
                    clients.agents.find((a) => a.agent_type === post.agent_kernel)?.reason
                  ) ?? '',
              })}
            </p>
          ) : null}

          {chosen?.id_origin === 'claimed' ? (
            <p className="flex items-center gap-1.5 pt-0.5 text-[12px] leading-[1.45] text-text-muted">
              <Info size={13} className="shrink-0 text-text-dim" />
              <span>{t('workbench.newSession.claimedHint', { name: chosen.display_name })}</span>
            </p>
          ) : null}

          {showUnavailable && unavailable.length ? (
            <div className="flex flex-col gap-1 rounded-[8px] border border-dashed border-border-strong bg-bg-secondary px-2.5 py-2 text-[12px] text-text-muted">
              {unavailable.map((c) => (
                <p key={c.agent_type} className="leading-relaxed">
                  <span className="font-medium text-text-secondary">{c.display_name}</span>
                  {' — '}
                  {agentReasonText(c.reason)}
                </p>
              ))}
            </div>
          ) : null}
        </div>

        {/* 第一句话：直接复用成熟统一的 PromptComposerBox（粘贴/拖拽/选文件 + `/` 挑 skill + 自动伸缩 + 快捷键提交） */}
        <PromptComposerBox
          text={text}
          onChangeText={setText}
          skills={skills}
          onAddSkill={addSkill}
          onRemoveSkill={removeSkill}
          onAddFiles={addFiles}
          attachCount={count}
          canSubmit={canSubmit}
          submitting={creating}
          onSubmit={handleCreate}
          onCancel={onClose}
          autoFocus
          disabled={creating}
          placeholder={t('employees.launch.firstMessagePlaceholder', { name: post.title })}
          idPrefix="employee-launch"
          textareaId="employee-launch-text"
          ariaLabelledBy="employee-launch-first"
          minLines={3}
          maxLines={8}
          menuPlacement="above"
          headerSlot={
            <div className="flex items-baseline justify-between gap-2">
              <label
                id="employee-launch-first"
                htmlFor="employee-launch-text"
                className="text-[12px] font-medium text-text-secondary"
              >
                {t('employees.launch.firstMessage')}
              </label>
              <span className="text-[11px] text-text-muted">
                {t('employees.launch.attachHint')}
              </span>
            </div>
          }
          attachmentSlot={
            <AttachmentStrip
              images={images}
              documents={documents}
              onRemoveImage={removeImage}
              onRemoveDocument={removeDocument}
              idPrefix="employee-launch"
            />
          }
          attachButtonLabel={t('employees.launch.attach')}
          rightActionsSlot={
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="h-7 rounded-[7px] px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
                onClick={onClose}
                disabled={creating}
              >
                {t('common.cancel')}
              </button>
              <span className="mr-0.5 font-mono text-[11px] text-text-dim">{modKey}↵</span>
            </div>
          }
          submitTestId="employee-start-session"
          submitLabel={t('employees.launch.start')}
        />

        {/* 在哪儿干活：默认取员工岗位目录（或 ~/.frago），同时提供与新建会话一致的目录树浏览 */}
        <div className="fgrp">
          <div className="flex items-center justify-between gap-2">
            <label htmlFor="employee-launch-cwd">{t('employees.launch.cwdLabel')}</label>
            <button
              type="button"
              data-testid="employee-toggle-browse-dirs"
              onClick={toggleBrowsing}
              aria-expanded={browsing}
              className={`inline-flex h-6 shrink-0 items-center gap-1 rounded-[6px] border px-2 text-[11px] transition-colors ${
                browsing
                  ? 'border-[var(--sel-border)] bg-[var(--sel-bg)] text-text-primary'
                  : 'border-border-color bg-bg-secondary text-text-secondary hover:bg-bg-hover hover:text-text-primary'
              }`}
            >
              <FolderSearch size={12} strokeWidth={1.5} />
              {browsing
                ? t('workbench.newSession.cwdBrowseClose')
                : t('workbench.newSession.cwdBrowse')}
            </button>
          </div>
          <div className="flex items-center gap-1.5">
            <Folder size={13} className="shrink-0 text-text-muted" />
            <input
              id="employee-launch-cwd"
              type="text"
              className="sinput mono min-w-0 flex-1"
              value={cwd}
              onChange={(e) => setCwd(e.target.value)}
              placeholder={t('employees.launch.cwdPlaceholder')}
              spellCheck={false}
              disabled={creating}
            />
          </div>
          <p className="hint">
            {cwd.trim()
              ? withTilde(cwd.trim())
              : t('employees.launch.cwdUsesEmployee', {
                  dir: withTilde(post.cwd || DEFAULT_CWD),
                })}
          </p>

          {browsing ? (
            <div className="mt-1.5 flex flex-col gap-2 rounded-[8px] border border-border-color bg-bg-secondary p-2">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid="employee-browse-up"
                  disabled={!listing?.parent || browseLoading}
                  onClick={() => listing?.parent && void openFolder(listing.parent)}
                  title={t('workbench.newSession.cwdUp')}
                  aria-label={t('workbench.newSession.cwdUp')}
                  className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary disabled:opacity-40"
                >
                  <CornerLeftUp size={13} strokeWidth={1.5} />
                  <span>{t('workbench.newSession.cwdUp')}</span>
                </button>
                <input
                  type="text"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={t('workbench.newSession.cwdFilter')}
                  data-testid="employee-browse-filter"
                  className="h-7 min-w-0 flex-1 rounded-[7px] border border-border-color bg-bg-primary px-2.5 text-[12px] text-text-primary outline-none focus:border-[var(--sel-border)]"
                />
              </div>

              <div
                className="flex max-h-48 flex-col divide-y divide-border-color overflow-y-auto rounded-[8px] border border-border-color bg-bg-primary"
                data-testid="employee-browse-list"
              >
                {browseLoading && !listing ? (
                  <p className="px-3 py-2.5 text-[12px] text-text-muted">
                    {t('workbench.newSession.cwdLoading')}
                  </p>
                ) : visibleEntries.length ? (
                  visibleEntries.map((e) => (
                    <button
                      key={e.path}
                      type="button"
                      onClick={() => void openFolder(e.path)}
                      title={e.path}
                      className="flex h-8 w-full shrink-0 items-center gap-2.5 px-3 text-left font-mono text-[12px] text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
                    >
                      <Folder size={13} className="shrink-0 text-text-muted" />
                      <span className="min-w-0 flex-1 truncate">{e.name}</span>
                      <ChevronRight size={12} className="shrink-0 text-text-dim" />
                    </button>
                  ))
                ) : (
                  <p className="px-3 py-2.5 text-center text-[12px] text-text-muted">
                    {t('workbench.newSession.cwdEmpty')}
                  </p>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {error ? (
          <p className="break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-[12px] text-accent-error">
            {t('employees.launch.createFailed', { reason: error })}
          </p>
        ) : null}
      </div>
    </DialogShell>
  );
}
