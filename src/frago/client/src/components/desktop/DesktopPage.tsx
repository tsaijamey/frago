/**
 * 虚拟桌面（agent_os）常驻页。
 *
 * 从前虚拟桌面是独立打开的一张浏览器标签页（`/app/agent_os`），人在工作台看会话、
 * 看虚拟桌面得在两个标签之间来回切。现在它作为左侧菜单 `desktop` 项（紧跟 `sessions`
 * 下方）常驻在主界面右侧，与会话工作台等主视图并列，不再走临时标签页，也不挂到
 * `recipes` 的临时子项下面。
 *
 * 切去别的页面时，`PageHost` 把这一页保留在 DOM 中且不卸载 iframe，WebSocket 与画布
 * 帧流不断连。
 *
 * 2026-11-14：这一页此前是「一整块纯黑，没有任何说明」。人从浅色的产品里点进桌面，
 * 撞进一块黑矩形，看不出它在加载、连上了、还是坏了。现在顶上补一条轻薄状态栏，
 * 把桌面连接态写清楚；画布在没连上/还在加载时让位给一块与深浅主题协调的工作台
 * 占位容器，里面给出当前状态与可做的事，而不是让用户对着一块黑屏猜。
 *
 * 桌面画布内部（画布上的窗口、Dock、右下角语音花瓣与对话入口）由 `/app/agent_os/`
 * 那份页面自己渲染，不在本组件内。
 */

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Monitor, RefreshCw } from 'lucide-react';
import { desktopAppUrl } from '@/api/client';
import { usePageStore } from '@/stores/pageStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import EmptyState from '@/components/ui/EmptyState';

/** 画布的三档状态：还在装载 / 装载完 / 装载失败。 */
type FrameState = 'loading' | 'ready' | 'error';

export default function DesktopPage() {
  const { t } = useTranslation();
  const sessionId = usePageStore((s) => s.desktopSessionId);
  const currentPage = usePageStore((s) => s.currentPage);
  const isActive = currentPage === 'desktop';
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [frameState, setFrameState] = useState<FrameState>('loading');
  // 重新挂载 iframe 的钥匙：装载失败时人点「重新载入」，换掉 key 强制它重来一次。
  const [reloadKey, setReloadKey] = useState(0);
  const src = desktopAppUrl(sessionId);

  const { isConnected } = useWebSocket({ autoConnect: true });

  useEffect(() => {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    try {
      win.postMessage({ type: 'frago:desktop-visibility', visible: isActive }, '*');
    } catch {
      // ignore transient errors before iframe document is ready
    }
  }, [isActive]);

  useEffect(() => {
    if (!isActive) return;

    const postHotkey = (action: 'alt-right-down' | 'alt-right-up' | 'ctrl-right-down') => {
      try {
        iframeRef.current?.contentWindow?.postMessage(
          { type: 'frago:desktop-hotkey', action },
          '*'
        );
      } catch {
        // ignore
      }
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'AltRight') {
        e.preventDefault();
        if (!e.repeat) postHotkey('alt-right-down');
      } else if (e.code === 'ControlRight' && !e.repeat) {
        postHotkey('ctrl-right-down');
      }
    };

    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'AltRight') {
        e.preventDefault();
        postHotkey('alt-right-up');
      }
    };

    window.addEventListener('keydown', onKeyDown, true);
    window.addEventListener('keyup', onKeyUp, true);
    return () => {
      window.removeEventListener('keydown', onKeyDown, true);
      window.removeEventListener('keyup', onKeyUp, true);
    };
  }, [isActive]);

  // 装载兜底：iframe 的 onLoad 在少数失败路径上不会触发，超过一段时间仍没就绪，
  // 就按「连不上」呈现，别让人一直盯着转圈。
  useEffect(() => {
    if (frameState !== 'loading') return;
    const timer = window.setTimeout(() => {
      setFrameState((prev) => (prev === 'loading' ? 'error' : prev));
    }, 20_000);
    return () => window.clearTimeout(timer);
  }, [frameState, reloadKey]);

  const reload = () => {
    setFrameState('loading');
    setReloadKey((prev) => prev + 1);
  };

  // 状态栏文案：服务没连上时先说服务，再说桌面本身。
  const status = !isConnected
    ? { tone: 'error' as const, label: t('desktop.statusDisconnected', 'Disconnected') }
    : frameState === 'loading'
      ? { tone: 'running' as const, label: t('desktop.statusLoading', 'Loading') }
      : frameState === 'error'
        ? { tone: 'error' as const, label: t('desktop.statusError', 'Failed to load') }
        : { tone: 'done' as const, label: t('desktop.statusConnected', 'Connected') };

  const showCanvas = isConnected && frameState === 'ready';

  return (
    <div className="dt-page">
      <header className="ui-page-header">
        <div className="ui-page-header-titles">
          <h1 className="ui-page-header-title">{t('sidebar.nav.desktop')}</h1>
          <span className="ui-page-header-meta">
            {t('desktop.subtitle', 'Virtual desktop for the agent to work in')}
          </span>
        </div>
        <div className="ui-page-header-actions">
          <span className={`ui-signal-pill dt-status dt-status--${status.tone}`}>
            <span className={`ui-signal-dot ui-signal-dot--${status.tone}`} />
            {status.label}
          </span>
          <button
            type="button"
            className="ui-icon-btn"
            onClick={reload}
            title={t('desktop.reload', 'Reload desktop')}
            aria-label={t('desktop.reload', 'Reload desktop')}
          >
            <RefreshCw size={16} strokeWidth={1.75} />
          </button>
        </div>
      </header>

      <div className="dt-stage">
        {/* iframe 一直在 DOM 里（切走不卸载是这一页的既有约定），但没就绪时
            藏起来，让下面的占位容器说话。 */}
        <iframe
          key={reloadKey}
          ref={iframeRef}
          className="desktop-page-frame dt-frame"
          style={{ visibility: showCanvas ? 'visible' : 'hidden' }}
          src={src}
          title={t('sidebar.nav.desktop')}
          allow="microphone; autoplay"
          onLoad={() => {
            setFrameState('ready');
            try {
              iframeRef.current?.contentWindow?.postMessage(
                {
                  type: 'frago:desktop-visibility',
                  visible: usePageStore.getState().currentPage === 'desktop',
                },
                '*'
              );
            } catch {
              // ignore
            }
          }}
          onError={() => setFrameState('error')}
        />

        {!showCanvas && (
          <div className="dt-placeholder">
            <EmptyState
              Icon={Monitor}
              title={
                !isConnected
                  ? t('desktop.offlineTitle', 'Desktop is not connected')
                  : frameState === 'error'
                    ? t('desktop.errorTitle', 'The desktop did not load')
                    : t('desktop.loadingTitle', 'Starting the desktop…')
              }
              description={
                !isConnected
                  ? t(
                      'desktop.offlineDesc',
                      'Waiting for the local frago service. It will come back on its own once the service is running.'
                    )
                  : frameState === 'error'
                    ? t('desktop.errorDesc', 'Try reloading; if it keeps failing, check that the local service is running.')
                    : t('desktop.loadingDesc', 'The canvas appears here as soon as it is ready.')
              }
              action={
                frameState === 'error' || !isConnected ? (
                  <button type="button" className="page-header-btn" onClick={reload}>
                    <RefreshCw size={14} strokeWidth={1.75} />
                    {t('desktop.reload', 'Reload desktop')}
                  </button>
                ) : undefined
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}
