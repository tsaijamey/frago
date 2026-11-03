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
 * ## 内核、目录、第一句话
 *
 * 内核默认取员工自己那一栏（`agent_kernel`），能改——员工记的是「这个岗位习惯用哪家」，
 * 不是「只能用这家」。改过之后只影响这一场，NEVER 写回员工的编制：一次临时换机位不是
 * 重新定岗。
 *
 * 目录默认取员工那一栏（`cwd`），空着也可以：服务端在请求里没给目录时会取员工那一栏
 * （`routes/workbench.py` 里那一段），所以这里留空等于「到那个员工的领地里去」。人在这一栏
 * 手写了路径则以他写的为准。
 *
 * ## 起完之后
 *
 * 编号当场就有的（claude）直接跳进那一场；要认领的（codex / opencode）在这里等，等的全过程
 * 摆在人眼前——照的是结对页那套（`StartTeamPanel`）：起会话那条路本来就有两种编号来路，
 * 假装编号已经有了会把人送进一场并不存在的会话。等到编号再跳，**NEVER 先跳再补**。
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Folder, Loader2, Sparkles } from 'lucide-react';
import DialogShell from './DialogShell';
import { kernelLabel } from './employeeMeta';
import { fetchEmployee, type EmployeeDetail, type EmployeePost } from '@/hooks/useEmployees';
import {
  agentReasonText,
  createSession,
  pickDefaultAgent,
  rememberLastAgent,
  useAgentClients,
  waitForSession,
} from '@/hooks/useAgentClients';
import { addRecentDirectory } from '@/utils/recentDirectories';
import { withTilde } from '@/components/sessionWorkbench/filePaths';

interface LaunchEmployeeDialogProps {
  /** 点的是哪个员工。null 表示这个窗没开着。 */
  post: EmployeePost | null;
  onClose: () => void;
  /**
   * 会话起来了，编号在这里。第二个参数是人刚打的那句话——切过去之后没别的地方存，而这一场
   * 刚起时记录流还是空的，页面要靠它告诉人「起来的是哪一句」。
   */
  onCreated: (sessionId: string, text: string) => void;
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
  const [cwd, setCwd] = useState('');
  const [text, setText] = useState('');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** 正在等哪一步。null = 没在等。文案照结对页那三档的写法。 */
  const [waiting, setWaiting] = useState<'claiming' | null>(null);
  /** 人在等的时候按了取消。取消的是「等」，不是那场会话——它已经起来了。 */
  const [cancelled, setCancelled] = useState(false);
  const abort = useRef<AbortController | null>(null);

  const clients = useAgentClients(open);
  const selectable = useMemo(() => clients.agents.filter((a) => a.selectable), [clients.agents]);
  const chosen = useMemo(
    () => selectable.find((a) => a.agent_type === agent) ?? null,
    [selectable, agent]
  );

  // 换一张卡片就把整块重置。上一个人的目录、上一个人打了一半的话带过来，人就以为自己在
  // 跟新的那个员工说话，而框里全是他刚跟别人说过的东西。
  useEffect(() => {
    if (!post) return;
    setDetail(null);
    setDetailError(null);
    setCtxOpen(false);
    setAgent(null);
    setCwd(post.cwd ?? '');
    setText('');
    setError(null);
    setCreating(false);
    setWaiting(null);
    setCancelled(false);
  }, [post]);

  // 窗一关就撒手：等编号那一趟不该在人已经走了之后还挂着。
  useEffect(
    () => () => {
      abort.current?.abort();
    },
    []
  );

  // 详情（含语境原文与纳管目录）只在窗开着时取一次：这些是这台机器上的事实，不会在窗开着
  // 的这十几秒里变。
  useEffect(() => {
    if (!post) return;
    let alive = true;
    fetchEmployee(post.member_post_id)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        // 取不到详情不让这一场开不下去——起会话本身不需要它（服务端自己会拼）。但要说出来，
        // 否则下面那块语境预览一直转圈，人会以为这一场起不来。
        setDetailError(e instanceof Error ? e.message : t('employees.errors.detailFailedPlain'));
      });
    return () => {
      alive = false;
    };
  }, [post, t]);

  /**
   * 默认选哪家：员工自己那一栏优先，它在清单里挑不了就退回 `pickDefaultAgent` 那套判断
   * （人上次用的、服务端建议的）。员工记的是这个岗位习惯用哪家，不是只能用这家。
   */
  useEffect(() => {
    if (!post || !clients.agents.length) return;
    setAgent((prev) => {
      if (prev) return prev;
      const own = clients.agents.find((a) => a.agent_type === post.agent_kernel && a.selectable);
      return own?.agent_type ?? pickDefaultAgent(clients.agents, clients.fallbackDefault);
    });
  }, [post, clients.agents, clients.fallbackDefault]);

  const ctx = detail?.business_context_block ?? '';
  const slots = detail?.managed_data.data_slots ?? [];
  const folderCount = slots.length || post?.data_summary.slot_count || 0;
  const entryCount =
    slots.reduce((n, s) => n + s.total_count, 0) || post?.data_summary.entry_count || 0;

  // 第一句话可以留空：服务端那边「第一句话和附件不能都是空的」，而这里没有附件入口，
  // 所以这一栏就是必填。空着时按钮不可点，别让人点了才发现。
  const canSubmit = !creating && !!chosen && text.trim().length > 0;

  /**
   * 建这一场。**建与等分成两段，因为编号的来路本来就是两种。**
   *
   * claude 接受由调用方指定编号，点完创建当场就知道这一场叫什么，直接切过去。codex 与
   * opencode 的编号由它们自己分配，frago 要等会话起来后认领——那一段空窗如实说出来，人
   * 按了取消只停「等」，那场会话本身照旧起来，所以取消之后要把「它起来了、编号是多少」
   * 说清楚，别让人以为白按了一次。
   */
  const handleCreate = async () => {
    if (!post || !chosen || !canSubmit) return;
    setError(null);
    setCancelled(false);
    setCreating(true);
    const controller = new AbortController();
    abort.current = controller;

    try {
      const first = text.trim();
      const launch = await createSession({
        agent: chosen.agent_type,
        cwd: cwd.trim(),
        text: first,
        employee: post.member_post_id,
      });
      rememberLastAgent(chosen.agent_type);
      if (cwd.trim()) addRecentDirectory(cwd.trim());

      let sessionId = launch.session_id;
      if (!sessionId) {
        setWaiting('claiming');
        sessionId = await waitForSession(launch.handle, { signal: controller.signal });
        setWaiting(null);
      }

      onCreated(sessionId, first);
      onClose();
    } catch (e) {
      setWaiting(null);
      if (controller.signal.aborted) {
        // 取消的是「等」，不是那场会话。
        setCancelled(true);
        setCreating(false);
      } else {
        // 建不起来就**留在这个窗里**并把话原样摆出来。关掉再弹一句提示，人打的那段话就没了。
        setError(e instanceof Error ? e.message : t('employees.launch.createFailedPlain'));
        setCreating(false);
      }
    } finally {
      abort.current = null;
    }
  };

  if (!post) return null;

  return (
    <DialogShell
      title={t('employees.launch.title', { name: post.title })}
      onClose={onClose}
      width={560}
      closable={!creating}
      footer={
        <>
          {waiting ? (
            // 等编号这一段：能按的只有取消，而取消停的是「等」，那场会话照旧起来。
            <button
              type="button"
              className="page-header-btn"
              onClick={() => abort.current?.abort()}
              data-testid="employee-cancel-wait"
            >
              {t('employees.launch.cancelWait')}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="page-header-btn"
                onClick={onClose}
                disabled={creating}
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
                className="page-header-btn page-header-primary"
                onClick={handleCreate}
                disabled={!canSubmit}
                data-testid="employee-start-session"
              >
                {creating ? <Loader2 size={14} className="cs-spin" /> : null}
                {t('employees.launch.start')}
              </button>
            </>
          )}
        </>
      }
    >
      {/* 这个员工是谁：缩写 + 一行职责 + 内核。与人点卡片之前看到的那张卡片同一个身份。 */}
      <div className="flex items-center gap-2.5 rounded-[8px] border border-border-color bg-bg-secondary px-2.5 py-2">
        <span className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-[6px] border border-border-color bg-bg-primary font-mono text-[11px] font-semibold text-text-primary">
          {post.member_post_id.slice(0, 3).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-text-secondary">
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
          <span className="shrink-0 text-[11.5px] font-semibold text-text-primary">
            {t('employees.launch.contextTitle')}
          </span>
          <span className="min-w-0 flex-1 truncate text-[11.5px] text-text-muted">
            {detailError
              ? t('employees.launch.contextFailed')
              : t('employees.launch.contextSummary', {
                  folders: folderCount,
                  entries: entryCount,
                  domains: detail?.managed_data.knowledge_domains.length ?? 0,
                  recipes: detail?.managed_data.recipes.length ?? 0,
                })}
          </span>
          <span className="shrink-0 text-[11.5px] text-text-secondary">
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
              <p className="pt-2 text-[11.5px] text-text-muted">
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
          <p className="text-[11.5px] text-text-muted">{t('employees.launch.kernelProbing')}</p>
        ) : clients.error ? (
          <p className="break-words text-[11.5px] text-accent-error">{clients.error}</p>
        ) : !selectable.length ? (
          <p className="break-words text-[11.5px] text-accent-error">
            {t('employees.launch.kernelNone')}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t('employees.launch.kernelLabel')}>
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
                  className={`inline-flex h-7 items-center gap-1.5 rounded-[8px] border px-[11px] text-[12.5px] transition-colors ${
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
          </div>
        )}
        {/* 员工自己那一栏挑不了时才说一句：不说的话人会觉得「默认怎么不是我这个岗位配的那家」 */}
        {chosen && post.agent_kernel && chosen.agent_type !== post.agent_kernel ? (
          <p className="hint">
            {t('employees.launch.kernelSwitched', {
              wanted: kernelLabel(post.agent_kernel),
              using: chosen.display_name,
              reason: agentReasonText(
                clients.agents.find((a) => a.agent_type === post.agent_kernel)?.reason
              ) ?? '',
            })}
          </p>
        ) : null}
      </div>

      {/* 在哪儿干活。留空 = 到员工自己的领地里去，服务端会取员工那一栏。 */}
      <div className="fgrp">
        <label htmlFor="employee-launch-cwd">{t('employees.launch.cwdLabel')}</label>
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
            : post.cwd
              ? t('employees.launch.cwdUsesEmployee', { dir: withTilde(post.cwd) })
              : t('employees.launch.cwdNeeded')}
        </p>
      </div>

      {/* 第一句话 */}
      <div className="fgrp">
        <label htmlFor="employee-launch-text">{t('employees.launch.firstMessage')}</label>
        <textarea
          id="employee-launch-text"
          className="sinput"
          style={{ height: 72, padding: '7px 9px', resize: 'none', lineHeight: 1.45 }}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('employees.launch.firstMessagePlaceholder', { name: post.title })}
          disabled={creating}
        />
      </div>

      {/* 等编号那一档。**必须说出来在等什么**：这一档可能十几秒，界面纹丝不动的话人分不出
          是没建成、还是在起，只好再点一次，于是起了两场。 */}
      {waiting ? (
        <p
          className="flex items-center gap-2 rounded-[8px] bg-bg-secondary px-3 py-2 text-[12px] text-text-secondary"
          data-testid="employee-waiting"
        >
          <Loader2 size={13} className="cs-spin shrink-0" />
          {t('employees.launch.waitingId', { name: chosen?.display_name ?? '' })}
        </p>
      ) : null}

      {/* 人按了取消之后：那场会话本身照旧起来了，把这件事和它叫什么说清楚。 */}
      {cancelled ? (
        <p className="rounded-[8px] bg-bg-secondary px-3 py-2 text-[12px] text-text-secondary">
          {t('employees.launch.waitCancelled')}
        </p>
      ) : null}

      {error ? (
        <p className="break-words rounded-[8px] bg-accent-error-10 px-3 py-2 text-[12px] text-accent-error">
          {t('employees.launch.createFailed', { reason: error })}
        </p>
      ) : null}
    </DialogShell>
  );
}
