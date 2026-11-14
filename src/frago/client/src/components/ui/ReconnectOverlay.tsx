/**
 * 本机后台服务不在时展示的重连与终端唤醒指引。
 *
 * 两段式反馈：
 * 1. 短暂失联（< 10 秒，如服务日常重启或自更新）：只展示轻量转圈提示，不弹出大面板打断视线；
 * 2. 连续失联满 10 秒（WAKE_GUIDE_DELAY_MS）：多半是运行 Frago 的终端被关闭或电脑休眠后服务停了，
 *    升级展示零代码友好的「终端唤醒指引」面板（含一键复制命令、Mac/Windows 操作说明、立即重测按钮）；
 *    同时允许点击「暂时收起」退化为顶部紧凑警示条，查看页面已有内容且保留草稿不丢失，服务恢复即自动收起。
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Copy, RefreshCw, Terminal, ChevronUp, ChevronDown } from 'lucide-react';
import { useConnectionStore, WAKE_COMMAND } from '@/api/connection';

async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back to textarea copy below
  }

  if (typeof document === 'undefined') return false;
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    const ok = typeof document.execCommand === 'function' ? document.execCommand('copy') : false;
    document.body.removeChild(textarea);
    return ok;
  } catch {
    return false;
  }
}

export default function ReconnectOverlay() {
  const reachable = useConnectionStore((state) => state.reachable);
  const prolonged = useConnectionStore((state) => state.prolonged);
  const collapsed = useConnectionStore((state) => state.collapsed);
  const probing = useConnectionStore((state) => state.probing);
  const setCollapsed = useConnectionStore((state) => state.setCollapsed);
  const probeNow = useConnectionStore((state) => state.probeNow);
  const { t } = useTranslation();

  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (reachable) {
      setCopied(false);
      if (copyTimerRef.current) {
        clearTimeout(copyTimerRef.current);
        copyTimerRef.current = null;
      }
    }
  }, [reachable]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) {
        clearTimeout(copyTimerRef.current);
      }
    };
  }, []);

  if (reachable) return null;

  const handleCopy = async () => {
    const ok = await copyTextToClipboard(WAKE_COMMAND);
    if (!ok && typeof navigator === 'undefined') return;
    setCopied(true);
    if (copyTimerRef.current) {
      clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = setTimeout(() => {
      copyTimerRef.current = null;
      setCopied(false);
    }, 2_000);
  };

  const handleProbeNow = () => {
    void probeNow();
  };

  // 连续失联满 10 秒且用户主动点击「暂时收起」：退化为顶部紧凑警示条，不遮挡底层草稿与内容
  if (prolonged && collapsed) {
    return (
      <div
        className="reconnect-compact-wrap"
        data-testid="reconnect-compact-banner"
        role="status"
        aria-live="polite"
      >
        <div className="reconnect-compact-bar">
          <div className="reconnect-compact-main">
            <span className="reconnect-status-dot" aria-hidden="true" />
            <span className="reconnect-compact-text">{t('reconnect.compactBannerText')}</span>
            <code className="reconnect-inline-code">{WAKE_COMMAND}</code>
          </div>
          <div className="reconnect-compact-actions">
            <button
              type="button"
              onClick={() => void handleCopy()}
              data-testid="reconnect-banner-copy-btn"
              className="reconnect-btn-secondary reconnect-btn-xs"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              <span>{copied ? t('reconnect.copied') : t('reconnect.copyCommand')}</span>
            </button>
            <button
              type="button"
              onClick={handleProbeNow}
              disabled={probing}
              data-testid="reconnect-banner-probe-btn"
              className="reconnect-btn-secondary reconnect-btn-xs"
            >
              <RefreshCw size={12} className={probing ? 'animate-spin' : ''} />
              <span>{probing ? t('reconnect.probing') : t('reconnect.probeNow')}</span>
            </button>
            <button
              type="button"
              onClick={() => setCollapsed(false)}
              data-testid="reconnect-expand-btn"
              className="reconnect-btn-primary reconnect-btn-xs"
            >
              <ChevronDown size={12} />
              <span>{t('reconnect.expandGuide')}</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 短暂波动期（800ms ~ 10s）：轻量重连转圈提示，不打断用户
  if (!prolonged) {
    return (
      <div
        className="reconnect-overlay"
        data-testid="reconnect-overlay"
        role="status"
        aria-live="polite"
      >
        <div className="reconnect-card">
          <div className="spinner" />
          <div className="reconnect-title">{t('reconnect.title')}</div>
          <div className="reconnect-hint">{t('reconnect.hint')}</div>
        </div>
      </div>
    );
  }

  // 连续失联满 10 秒：展示零先验普通用户友好的「终端唤醒指引」面板
  return (
    <div
      className="reconnect-overlay"
      data-testid="reconnect-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reconnect-wake-title"
    >
      <div className="reconnect-wake-card" data-testid="reconnect-wake-guide">
        <div className="reconnect-wake-header">
          <div className="reconnect-wake-icon" aria-hidden="true">
            <Terminal size={18} />
          </div>
          <div>
            <h2 id="reconnect-wake-title" className="reconnect-wake-title">
              {t('reconnect.wakeTitle')}
            </h2>
            <p className="reconnect-wake-reason">{t('reconnect.wakeReason')}</p>
          </div>
        </div>

        <div className="reconnect-command-section">
          <div className="reconnect-command-label">{t('reconnect.commandLabel')}</div>
          <div className="reconnect-command-box">
            <code className="reconnect-command-code" data-testid="reconnect-wake-command">
              {WAKE_COMMAND}
            </code>
            <button
              type="button"
              onClick={() => void handleCopy()}
              data-testid="reconnect-copy-btn"
              className={`reconnect-copy-btn ${copied ? 'is-copied' : ''}`}
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
              <span>{copied ? t('reconnect.copied') : t('reconnect.copyCommand')}</span>
            </button>
          </div>
        </div>

        <div className="reconnect-os-grid">
          <div className="reconnect-os-card">
            <div className="reconnect-os-title">{t('reconnect.macLabel')}</div>
            <div className="reconnect-os-desc">{t('reconnect.macSteps')}</div>
          </div>
          <div className="reconnect-os-card">
            <div className="reconnect-os-title">{t('reconnect.winLabel')}</div>
            <div className="reconnect-os-desc">{t('reconnect.winSteps')}</div>
          </div>
        </div>

        <div className="reconnect-auto-note">
          <span className="reconnect-pulse-dot" aria-hidden="true" />
          <span>{t('reconnect.autoRecoverNote')}</span>
        </div>

        <div className="reconnect-wake-footer">
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            data-testid="reconnect-collapse-btn"
            className="reconnect-btn-secondary"
          >
            <ChevronUp size={14} />
            <span>{t('reconnect.collapseToBar')}</span>
          </button>
          <button
            type="button"
            onClick={handleProbeNow}
            disabled={probing}
            data-testid="reconnect-probe-btn"
            className="reconnect-btn-primary"
          >
            <RefreshCw size={14} className={probing ? 'animate-spin' : ''} />
            <span>{probing ? t('reconnect.probing') : t('reconnect.probeNow')}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
