/**
 * NewSessionModal — 从浏览器起一场会话，并且**由人来挑用哪个客户端**。
 *
 * 建出来的是一场**普通会话**，不是什么网页专用的东西：它跟着各家自己的规矩起，记录写到
 * 各家自己该去的地方，下一次扫描它就是左栏里一行普通会话——同一个详情面板、同一条发送
 * 路径、同一份数据。
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
 * ## 起始目录
 *
 * 后端一直收这个参数，只是从前界面从没送过，于是浏览器起的会话全落在家目录。挑它正是
 * 这个对话框存在的另一半理由。
 *
 * ## 创建之后：编号未必当场就有
 *
 * claude 接受由调用方指定编号，点完创建当场就知道这一场叫什么，直接跳进去。codex 与
 * opencode 的编号由它们自己分配，frago 要等会话起来后认领——那一段空窗如实说出来，
 * 由 `SessionRail` 拿着把手去等（见 `waitForSession`）。假装编号已经有了，界面会跳进
 * 一场并不存在的会话，人看到一片空记录流，以为刚开的会话丢了。
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Folder, Home, Loader2 } from 'lucide-react';
import Modal from '../ui/Modal';
import { getSystemDirectories } from '../../api/client';
import { getRecentDirectories, addRecentDirectory } from '../../utils/recentDirectories';
import {
  createSession,
  pickDefaultAgent,
  rememberLastAgent,
  useAgentClients,
  type PendingLaunch,
} from '@/hooks/useAgentClients';

interface NewSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (launch: PendingLaunch) => void;
}

interface DirChoice {
  path: string;
  hint?: string;
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
  }, [isOpen]);

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

  const canSubmit = !creating && !!chosen && dir.trim().length > 0 && text.trim().length > 0;

  const handleCreate = async () => {
    if (!canSubmit || !chosen) return;
    setError(null);
    setCreating(true);
    try {
      const launch = await createSession({
        agent: chosen.agent_type,
        cwd: dir.trim(),
        text: text.trim(),
      });
      rememberLastAgent(chosen.agent_type);
      addRecentDirectory(dir.trim());
      onCreated(launch);
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
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            {t('workbench.newSession.clientLabel')}
          </label>

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
              aria-label={t('workbench.newSession.clientLabel')}
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
                      {c.reason}
                    </p>
                  ))
                : null}
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            {t('workbench.newSession.cwdLabel')}
          </label>
          <p className="text-[11px] text-[var(--text-muted)] -mt-1">
            {t('workbench.newSession.cwdHint')}
          </p>

          <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
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

          <input
            type="text"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            placeholder="/absolute/path"
            className="bg-[var(--bg-subtle)] border border-[var(--border-color)] rounded-md px-3 py-2 text-xs font-mono text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-[var(--text-secondary)]">
            {t('workbench.newSession.firstMessage')}
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
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
        </div>

        {error && (
          <p className="text-xs text-[var(--accent-error)] break-words">
            {t('workbench.newSession.createFailed', { reason: error })}
          </p>
        )}

        <div className="flex items-center justify-end gap-2">
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
