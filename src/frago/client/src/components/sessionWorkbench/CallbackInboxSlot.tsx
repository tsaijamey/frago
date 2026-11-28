/**
 * CallbackInboxSlot — 输入区上方的非侵入轻提示槽位（与 Next Task 队列物理分轨）。
 *
 * 三态呈现严格对齐定稿主原型（`#sessions/callback-inbox`）：
 * - 空态（`count === 0`）：完全隐藏，占高 `0px`，零边距/内边距/边框。
 * - 运行中态（`running`）：单行提示「N 份后台回执已收齐，本轮结束后自动并入」，可点击展开纯只读
 *   摘要抽屉（不抢占输入框与主发送按钮焦点，无编辑/发送控件）。
 * - 挂卡中态（`holding`）：当 `blocked_reason === 'blocked_by_card'` 或存在待拍板交互卡时，
 *   决策卡内保持 0 条回执节点，仅在卡外输入区上方单行低扰动提示「另有 N 份后台回执已就绪，拍板后自动汇总」。
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import type { CallbackInboxItem, CallbackInboxSummary } from '@/types/api';

function formatReceiptTime(raw: string | null | undefined): string {
  if (!raw) return '';
  const ts = Date.parse(raw);
  if (!Number.isFinite(ts)) return raw;
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${hh}:${mm}`;
}

function formatSourceRole(
  item: CallbackInboxItem,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  if (item.employee_id) {
    return item.target_name ? `${item.employee_id} · ${item.target_name}` : item.employee_id;
  }
  if (item.target_name) return item.target_name;
  return item.kind === 'employee'
    ? t('workbench.callbackInbox.kindEmployee')
    : t('workbench.callbackInbox.kindWorker');
}

function formatItemStatus(
  item: CallbackInboxItem,
  t: (key: string, opts?: Record<string, unknown>) => string
): string {
  if (item.delivery_state === 'delivering') {
    return t('workbench.callbackInbox.statusDelivering');
  }
  if (item.exit_code !== null && item.exit_code !== undefined && item.exit_code !== 0) {
    return t('workbench.callbackInbox.statusFailed', { code: item.exit_code });
  }
  if (item.exit_code === 0) {
    return t('workbench.callbackInbox.statusExitReady', { code: 0 });
  }
  return t('workbench.callbackInbox.statusReady');
}

export interface CallbackInboxSlotProps {
  inbox?: CallbackInboxSummary | null;
  holdingByCard?: boolean;
}

export default function CallbackInboxSlot({
  inbox,
  holdingByCard = false,
}: CallbackInboxSlotProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const count = inbox?.count ?? 0;
  const holding = count > 0 && (inbox?.blocked_reason === 'blocked_by_card' || holdingByCard);

  useEffect(() => {
    if (count <= 0 || holding) {
      setExpanded(false);
    }
  }, [count, holding]);

  if (count <= 0) {
    return (
      <div
        id="callback-inbox-slot"
        data-testid="callback-inbox-slot"
        data-count="0"
        className="cb-inbox-slot is-empty"
        style={{ display: 'none' }}
      />
    );
  }

  if (holding) {
    return (
      <div
        id="callback-inbox-slot"
        data-testid="callback-inbox-slot"
        data-count={count}
        data-mode="holding"
        className="cb-inbox-slot is-holding"
      >
        <div
          id="callback-inbox-bar"
          data-testid="callback-inbox-bar"
          data-state="holding"
          className="cb-inbox-bar is-holding"
          aria-live="polite"
        >
          <span className="cb-inbox-count">{count}</span>
          <span className="cb-inbox-msg">
            {t('workbench.callbackInbox.holdingBar', { n: count })}
          </span>
          <span className="cb-inbox-hint">
            {t('workbench.callbackInbox.holdingHint')}
          </span>
        </div>
      </div>
    );
  }

  const items = inbox?.items ?? [];

  return (
    <div
      id="callback-inbox-slot"
      data-testid="callback-inbox-slot"
      data-count={count}
      data-mode="running"
      className="cb-inbox-slot is-running"
    >
      {expanded ? (
        <div
          id="callback-inbox-drawer"
          data-testid="callback-inbox-drawer"
          role="region"
          aria-label={t('workbench.callbackInbox.drawerAriaLabel')}
          className="cb-inbox-drawer"
        >
          <div className="cb-drawer-hd">
            <span className="cb-drawer-title">
              {t('workbench.callbackInbox.drawerTitle', { n: count })}
            </span>
            <span className="cb-drawer-ro">
              {t('workbench.callbackInbox.readOnlyBadge')}
            </span>
            <button
              type="button"
              id="callback-inbox-collapse"
              data-testid="callback-inbox-collapse"
              className="cb-drawer-collapse"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => setExpanded(false)}
            >
              <ChevronDown size={12} aria-hidden="true" />
              <span>{t('workbench.callbackInbox.collapse')}</span>
            </button>
          </div>
          <div className="cb-drawer-list">
            {items.map((item) => {
              const timeStr = formatReceiptTime(item.worker_finished_at || item.updated_at);
              return (
                <div
                  key={item.job_id}
                  data-testid={`cb-drawer-item-${item.job_id}`}
                  className="cb-drawer-item"
                >
                  <span className="cb-drawer-role">{formatSourceRole(item, t)}</span>
                  <div className="cb-drawer-body">
                    {item.task_summary || t('workbench.callbackInbox.noSummary')}
                  </div>
                  <div className="cb-drawer-meta">
                    {timeStr ? <span className="num">{timeStr}</span> : null}
                    <span className="cb-drawer-badge">{formatItemStatus(item, t)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <button
        type="button"
        id="callback-inbox-bar"
        data-testid="callback-inbox-bar"
        data-state="running"
        className="cb-inbox-bar"
        aria-expanded={expanded}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="cb-inbox-count">{count}</span>
        <span className="cb-inbox-msg">
          {t('workbench.callbackInbox.runningBar', { n: count })}
        </span>
        <span className="cb-inbox-hint">
          <span>
            {expanded
              ? t('workbench.callbackInbox.collapseSummary')
              : t('workbench.callbackInbox.viewSummary')}
          </span>
          {expanded ? (
            <ChevronDown size={12} aria-hidden="true" />
          ) : (
            <ChevronRight size={12} aria-hidden="true" />
          )}
        </span>
      </button>
    </div>
  );
}
