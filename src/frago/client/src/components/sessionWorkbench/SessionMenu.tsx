/**
 * SessionMenu — 会话卡状态行最右、会话详情页头最右的那个「…」。两处是同一份菜单。
 *
 * 三段，段间一条分隔线：
 *
 * | 段 | 项 |
 * |---|---|
 * | 1 | Pin / Unpin、Put in group（分组接回之前置灰）、复制续接命令 |
 * | 2 | Close tmux session —— 只在这场开在 tmux 里时出现，整段连同分隔线都不画 |
 * | 3 | Delete session —— 报错红，先确认 |
 *
 * **关与删的动作、接口、收尾都不在这里另写。** 关走 `useCloseTmux`（`StopRunButton.tsx`，
 * 底下是 `useStopSessionRun`），删走 `useDeleteSession` 与 `deleteErrorKey`
 * （`DeleteSessionButton.tsx`，404 / 409 换成本地的话，其余照搬服务端那句）。这里改的只是入口与确认的
 * 位置：确认画在菜单里（问句 + 一句后果 + Cancel / 确认键），删不动的话摆在确认那一段。
 *
 * **在干活先确认，不在干活直接关。** 本页知道的（这场有没答完的一句）当场问；本页不知道的
 * 先直接关，服务端判出屏上还在干活时换成同一句确认再问一次。
 *
 * 菜单画在 `document.body` 上、按按钮的位置定位：卡片外面那圈 tmux 流光与清单的滚动区都会
 * 裁掉伸出去的部分，挂在卡片里就只剩按钮亮着、菜单看不见。靠清单底边那几张往下放不下就往上
 * 开（照 `StackPanel` 的 `menuOpensUp`，量的是清单那一框）。点菜单外面、按 Esc 收起；清单
 * 滚动时菜单跟着按钮走。
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Check, Copy, Folder, Loader2, MoreHorizontal, Pin, SquareTerminal, Trash2 } from 'lucide-react';
import type { WorkbenchSession } from '@/hooks/useWorkbenchSessions';
import { menuOpensUp } from './StackPanel';
import { resumeCommand } from './SessionItem';
import { deleteErrorKey, useDeleteSession, type DeleteSessionResult } from './DeleteSessionButton';
import { useCloseTmux } from './StopRunButton';

type View = 'menu' | 'close' | 'delete';

export interface SessionMenuProps {
  session: WorkbenchSession;
  /** 卡片那份宽 176，页头那份宽 188、按钮大一号。 */
  variant?: 'card' | 'header';
  pinned: boolean;
  onTogglePin?: (session: WorkbenchSession) => void;
  /** 这场此刻开在 tmux 里：第二段才画。 */
  inTmux: boolean;
  /** 本页刚发出的一句还没答完——点关先问。 */
  busyTurn?: boolean;
  /** tmux 里这一场没了（关掉了，或本来就没了）。 */
  onStopped?: () => void;
  onDeleted?: (result: DeleteSessionResult) => void;
  /** 复制续接命令。不给、或这一家没有续接命令（CoreAgent）就不长这一项。 */
  onCopy?: (session: WorkbenchSession) => void;
  copied?: boolean;
  /**
   * 往哪个框里量「下面放不放得下」：菜单外层带这个属性的那个祖先。找不到就按窗口量。
   */
  boundSelector?: string;
}

const ITEM =
  'flex w-full items-center gap-2 whitespace-nowrap rounded-[6px] px-2 py-[5px] text-left text-[12px] text-text-primary transition-colors duration-150 hover:bg-bg-hover disabled:cursor-default disabled:text-text-muted disabled:hover:bg-transparent';

export default function SessionMenu({
  session,
  variant = 'card',
  pinned,
  onTogglePin,
  inTmux,
  busyTurn = false,
  onStopped,
  onDeleted,
  onCopy,
  copied = false,
  boundSelector = '[data-session-menu-bound]',
}: SessionMenuProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>('menu');
  const [up, setUp] = useState(false);
  /** 菜单贴着按钮摆：右边对齐按钮右边，往下开记上沿、往上开记下沿（都是视口坐标）。 */
  const [pos, setPos] = useState<{ right: number; top?: number; bottom?: number } | null>(null);
  const stop = useCloseTmux(session.session_id, { busyTurn, onStopped });
  const stopping = stop.phase === 'stopping';
  const del = useDeleteSession(session, onDeleted);
  const deleting = del.busy;
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const cmd = onCopy ? resumeCommand(session) : null;

  const closeMenu = () => {
    if (stopping || deleting) return;
    setOpen(false);
    setView('menu');
    del.reset();
    stop.reset();
  };

  // 点菜单外面、按 Esc 收起。清单 15 秒一刷不收：卡片按会话编号认，刷新不重挂载。
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (wrap.current?.contains(target) || panel.current?.contains(target)) return;
      closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  });

  // 打开、换到确认那一段时都重量一次：确认段比菜单高。
  useLayoutEffect(() => {
    if (!open) {
      setUp(false);
      setPos(null);
      return undefined;
    }
    const btn = button.current;
    const el = panel.current;
    if (!btn || !el) return undefined;
    const place = () => {
      const r = btn.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      const vw = window.innerWidth || document.documentElement.clientWidth;
      const box = btn.closest(boundSelector);
      const bound = box ? box.getBoundingClientRect() : { top: 0, bottom: vh };
      const goUp = menuOpensUp(r, bound, el.offsetHeight);
      setUp(goUp);
      setPos(goUp ? { right: vw - r.right, bottom: vh - r.top + 4 } : { right: vw - r.right, top: r.bottom + 4 });
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    return () => {
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open, view, boundSelector]);

  const finish = () => {
    setOpen(false);
    setView('menu');
  };
  const closeTmux = () => {
    void stop.begin().then((step) => (step === 'done' ? finish() : setView('close')));
  };
  const confirmClose = () => {
    void stop.confirm().then((step) => step === 'done' && finish());
  };
  const confirmDelete = () => {
    void del.confirm().then((ok) => ok && finish());
  };

  const deleteErrorText = (f: { status: number; detail: string }) => {
    const key = deleteErrorKey(f.status);
    return key ? t(key) : f.detail;
  };

  const header = variant === 'header';
  const closeResult =
    stop.phase === 'absent'
      ? t('workbench.stopRun.absent')
      : stop.phase === 'failed'
        ? t('workbench.stopRun.failed', { error: stop.error ?? '' })
        : null;

  return (
    <div
      ref={wrap}
      className="relative shrink-0"
      // 菜单里的点击不许冒到卡片上——冒上去就成了「选中这一场」。
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        ref={button}
        type="button"
        data-testid="session-menu-button"
        data-variant={variant}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('workbench.menu.button')}
        title={t('workbench.menu.button')}
        onClick={() => (open ? closeMenu() : setOpen(true))}
        className={`flex items-center justify-center rounded-[5px] transition-colors duration-150 ${
          header
            ? 'h-7 w-7 text-text-muted hover:bg-bg-hover hover:text-text-primary'
            : 'h-[17px] w-5 text-[var(--card-meta)] hover:bg-bg-hover hover:text-text-primary'
        } ${open ? 'bg-bg-hover text-text-primary' : ''}`}
      >
        <MoreHorizontal size={header ? 16 : 12} strokeWidth={header ? 1.5 : 2} />
      </button>

      {open ? createPortal(
        // 菜单里的点击同样不许冒到卡片上：React 的事件照组件树冒泡，会经过上面那一层 wrap。
        <div
          ref={panel}
          role="menu"
          data-testid="session-menu"
          data-direction={up ? 'up' : 'down'}
          style={{ ...(pos ?? { right: 0, top: 0 }), visibility: pos ? undefined : 'hidden' }}
          className={`fixed z-[60] rounded-[8px] border border-border-color bg-bg-elevated p-1 shadow-lg ${
            header ? 'w-[188px]' : 'w-[176px]'
          }`}
        >
          {view === 'menu' ? (
            <>
              <div data-testid="session-menu-section" data-section="organize">
                {onTogglePin ? (
                  <button
                    type="button"
                    role="menuitem"
                    data-testid="session-menu-pin"
                    title={pinned ? t('workbench.rail.unpinHint') : t('workbench.rail.pinHint')}
                    onClick={() => {
                      onTogglePin(session);
                      closeMenu();
                    }}
                    className={ITEM}
                  >
                    <Pin size={12} fill={pinned ? 'currentColor' : 'none'} className="shrink-0 text-text-muted" />
                    {pinned ? t('workbench.rail.unpin') : t('workbench.rail.pin')}
                  </button>
                ) : null}
                {/* 标签分组 09-24 从左栏拿掉，主人说稍后接回；接回之前这一项占着位置、置灰。 */}
                <button
                  type="button"
                  role="menuitem"
                  data-testid="session-menu-group"
                  disabled
                  title={t('workbench.menu.putInGroupSoon')}
                  className={ITEM}
                >
                  <Folder size={12} className="shrink-0" />
                  {t('workbench.menu.putInGroup')}
                </button>
                {cmd ? (
                  <button
                    type="button"
                    role="menuitem"
                    data-testid="copy-resume"
                    title={cmd}
                    onClick={() => {
                      onCopy?.(session);
                      closeMenu();
                    }}
                    className={ITEM}
                  >
                    {copied ? (
                      <Check size={12} className="shrink-0 text-text-muted" />
                    ) : (
                      <Copy size={12} className="shrink-0 text-text-muted" />
                    )}
                    {t('workbench.menu.copyResume')}
                  </button>
                ) : null}
              </div>

              {inTmux ? (
                <div data-testid="session-menu-section" data-section="tmux">
                  <div className="my-1 h-px bg-border-color" />
                  <button
                    type="button"
                    role="menuitem"
                    data-testid="session-menu-close"
                    title={busyTurn ? t('workbench.stopRun.busyHint') : t('workbench.menu.closeHint')}
                    disabled={stopping}
                    onClick={closeTmux}
                    className={ITEM}
                  >
                    {stopping ? (
                      <Loader2 size={12} className="shrink-0 animate-spin text-text-muted" />
                    ) : (
                      <SquareTerminal size={12} className="shrink-0 text-text-muted" />
                    )}
                    {t('workbench.stopRun.action')}
                  </button>
                </div>
              ) : null}

              <div data-testid="session-menu-section" data-section="delete">
                <div className="my-1 h-px bg-border-color" />
                <button
                  type="button"
                  role="menuitem"
                  data-testid="session-menu-delete"
                  onClick={() => setView('delete')}
                  className={`${ITEM} !text-[var(--accent-error)] hover:!bg-[var(--accent-error-10)]`}
                >
                  <Trash2 size={12} className="shrink-0" />
                  {t('workbench.delete.action')}
                </button>
              </div>
            </>
          ) : view === 'close' ? (
            <div data-testid="session-menu-confirm-close" className="space-y-2 p-1.5">
              {closeResult ? null : (
                <>
                  <p className="text-[12px] font-medium leading-[1.45] text-text-primary">
                    {t('workbench.menu.closeBusyTitle')}
                  </p>
                  <p className="text-[11px] leading-[1.5] text-text-muted">{t('workbench.menu.closeBusyBody')}</p>
                </>
              )}
              {closeResult ? (
                <p
                  data-testid="session-stop-run-result"
                  className={`break-words text-[11px] leading-[1.5] ${
                    stop.phase === 'failed' ? 'text-accent-error' : 'text-text-secondary'
                  }`}
                >
                  {closeResult}
                </p>
              ) : null}
              <div className="flex gap-1.5 pt-0.5">
                <button
                  type="button"
                  onClick={closeMenu}
                  disabled={stopping}
                  className="flex-1 rounded-[6px] px-2 py-1 text-[12px] text-text-secondary hover:bg-bg-hover disabled:opacity-60"
                >
                  {stop.phase === 'absent' ? t('workbench.stopRun.dismiss') : t('workbench.stopRun.cancel')}
                </button>
                {stop.phase === 'absent' ? null : (
                  <button
                    type="button"
                    data-testid="session-stop-run-confirm"
                    onClick={confirmClose}
                    disabled={stopping}
                    className="flex flex-1 items-center justify-center gap-1 rounded-[6px] border border-border-strong px-2 py-1 text-[12px] font-medium text-text-primary hover:bg-bg-hover disabled:opacity-60"
                  >
                    {stopping ? <Loader2 size={11} className="animate-spin" /> : null}
                    {stopping ? t('workbench.stopRun.stopping') : t('workbench.stopRun.ok')}
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div data-testid="session-menu-confirm-delete" className="space-y-2 p-1.5">
              <p className="text-[12px] font-medium leading-[1.45] text-text-primary">
                {t('workbench.menu.deleteTitle')}
              </p>
              <p className="text-[11px] leading-[1.5] text-text-muted">{t('workbench.menu.deleteBody')}</p>
              {del.failure ? (
                <p
                  data-testid="session-delete-error"
                  className="break-words text-[11px] leading-[1.5] text-accent-error"
                >
                  {deleteErrorText(del.failure)}
                </p>
              ) : null}
              <div className="flex gap-1.5 pt-0.5">
                <button
                  type="button"
                  onClick={closeMenu}
                  disabled={deleting}
                  className="flex-1 rounded-[6px] px-2 py-1 text-[12px] text-text-secondary hover:bg-bg-hover disabled:opacity-60"
                >
                  {t('workbench.delete.cancel')}
                </button>
                <button
                  type="button"
                  data-testid="session-delete-confirm"
                  onClick={confirmDelete}
                  disabled={deleting}
                  className="flex flex-1 items-center justify-center gap-1 rounded-[6px] bg-accent-error px-2 py-1 text-[12px] font-medium text-[var(--text-on-accent)] hover:opacity-90 disabled:opacity-60"
                >
                  {deleting ? <Loader2 size={11} className="animate-spin" /> : null}
                  {deleting ? t('workbench.delete.busy') : t('workbench.delete.ok')}
                </button>
              </div>
            </div>
          )}
        </div>,
        document.body
      ) : null}
    </div>
  );
}
