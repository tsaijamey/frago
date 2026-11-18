/**
 * 虚拟桌面（agent_os）常驻页。
 *
 * 切去别的页面时，`PageHost` 把这一页保留在 DOM 中且不卸载 iframe，WebSocket 与画布
 * 帧流不断连。
 *
 * 将连接状态、分辨率、FPS、旁路女声守护开关、Observe/Takeover 模式切换、刷新/解锁
 * 与虚拟应用切换统一归拢至顶部页头与单行紧凑工具条（`.dt-toolbar`），把最大视口高度
 * 让给虚拟桌面舞台。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Monitor, RefreshCw, Volume2, VolumeX } from 'lucide-react';
import { desktopAppUrl, getActiveDesktopSession } from '@/api/client';
import { agentReasonText, useAgentClients, type AgentClient } from '@/hooks/useAgentClients';
import { usePageStore } from '@/stores/pageStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import EmptyState from '@/components/ui/EmptyState';
import './desktop.css';

/** 画布的三档状态：还在装载 / 装载完 / 装载失败。 */
type FrameState = 'loading' | 'ready' | 'error';
type ControlMode = 'observe' | 'takeover';
type VirtualAppKey = 'all' | 'term' | 'browser' | 'image' | 'video' | 'slide' | 'overlay';

const RESOLUTIONS = ['1920×1080', '1440×900', '1280×720'] as const;
const FPS_OPTIONS = ['30 fps', '60 fps', '15 fps'] as const;
const DESKTOP_AGENT_PRIORITY = ['coreagent', 'claude', 'codex', 'agy', 'opencode'] as const;

const VIRTUAL_APPS: { key: VirtualAppKey; label: string; short: string }[] = [
  { key: 'all', label: 'All apps (Desktop)', short: 'All' },
  { key: 'term', label: 'Terminal', short: 'Terminal' },
  { key: 'browser', label: 'Chrome Browser', short: 'Browser' },
  { key: 'image', label: 'Image Preview', short: 'Preview' },
  { key: 'video', label: 'Video Player', short: 'Player' },
  { key: 'slide', label: 'Slide Layer', short: 'Slide' },
  { key: 'overlay', label: 'Progress Overlay', short: 'Overlay' },
];

const VIRTUAL_APP_KEYS = new Set<VirtualAppKey>(VIRTUAL_APPS.map((a) => a.key));

function agentPriorityRank(agentType: string): number {
  const idx = DESKTOP_AGENT_PRIORITY.indexOf(
    agentType.toLowerCase() as (typeof DESKTOP_AGENT_PRIORITY)[number]
  );
  return idx >= 0 ? idx : DESKTOP_AGENT_PRIORITY.length;
}

export default function DesktopPage() {
  const { t } = useTranslation();
  const sessionId = usePageStore((s) => s.desktopSessionId);
  const explicitSessionId = usePageStore((s) => s.desktopExplicitSessionId);
  const setDesktopSessionId = usePageStore((s) => s.setDesktopSessionId);
  const currentPage = usePageStore((s) => s.currentPage);
  const isActive = currentPage === 'desktop';
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const userPickedAgentRef = useRef(false);
  const [frameState, setFrameState] = useState<FrameState>('loading');
  // 重新挂载 iframe 的钥匙：装载失败时人点「重新载入」，换掉 key 强制它重来一次。
  const [reloadKey, setReloadKey] = useState(0);
  const [resolution, setResolution] = useState<string>(RESOLUTIONS[0]);
  const [fps, setFps] = useState<string>(FPS_OPTIONS[0]);
  const [narratorOn, setNarratorOn] = useState<boolean>(true);
  const [controlMode, setControlMode] = useState<ControlMode>('observe');
  const [soundUnlocked, setSoundUnlocked] = useState<boolean>(false);
  const [activeApp, setActiveApp] = useState<VirtualAppKey>('all');
  const [selectedAgent, setSelectedAgent] = useState<string>('');
  const configRef = useRef({
    resolution: RESOLUTIONS[0] as string,
    fps: FPS_OPTIONS[0] as string,
    narratorOn: true,
    controlMode: 'observe' as ControlMode,
  });

  const { agents: rawAgents, loading: loadingAgents } = useAgentClients(true);

  const orderedAgents: AgentClient[] = useMemo(() => {
    return [...rawAgents].sort((a, b) => {
      const ra = agentPriorityRank(a.agent_type);
      const rb = agentPriorityRank(b.agent_type);
      if (ra !== rb) return ra - rb;
      return a.agent_type.localeCompare(b.agent_type);
    });
  }, [rawAgents]);

  const selectableAgents = useMemo(
    () => orderedAgents.filter((a) => a.selectable),
    [orderedAgents]
  );

  const defaultPriorityAgent = selectableAgents[0]?.agent_type ?? '';

  const src = desktopAppUrl(explicitSessionId);

  const { isConnected } = useWebSocket({ autoConnect: true });

  const postToStage = useCallback((payload: Record<string, unknown>) => {
    try {
      iframeRef.current?.contentWindow?.postMessage(payload, '*');
    } catch {
      // ignore transient errors before iframe document is ready
    }
  }, []);

  useEffect(() => {
    if (!defaultPriorityAgent) return;
    if (!selectedAgent) {
      setSelectedAgent(defaultPriorityAgent);
      if (frameState === 'ready') {
        postToStage({ type: 'frago:desktop-agent', agent: defaultPriorityAgent });
      }
    }
  }, [defaultPriorityAgent, selectedAgent, frameState, postToStage]);

  // 双向同步：接收画布内会话变更与全部顶部工具条状态（mode / narrator / soundUnlocked / app / agent）。
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const data = e.data;
      if (!data || typeof data !== 'object') return;
      if (data.type === 'frago:desktop-session') {
        const nextSid = typeof data.sessionId === 'string' && data.sessionId.trim() ? data.sessionId.trim() : null;
        setDesktopSessionId(nextSid, { clearExplicit: !!data.reset });
        if (typeof data.agent === 'string' && data.agent.trim() && !userPickedAgentRef.current) {
          setSelectedAgent(data.agent.trim());
        }
        return;
      }
      if (data.type === 'frago:desktop-state') {
        if (data.mode === 'observe' || data.mode === 'takeover') {
          configRef.current.controlMode = data.mode;
          setControlMode(data.mode);
        }
        if (typeof data.narrator === 'boolean') {
          configRef.current.narratorOn = data.narrator;
          setNarratorOn(data.narrator);
        }
        if (typeof data.soundUnlocked === 'boolean') {
          setSoundUnlocked(data.soundUnlocked);
        }
        if (typeof data.app === 'string' && VIRTUAL_APP_KEYS.has(data.app as VirtualAppKey)) {
          setActiveApp(data.app as VirtualAppKey);
        }
        if (typeof data.resolution === 'string' && (RESOLUTIONS as readonly string[]).includes(data.resolution)) {
          configRef.current.resolution = data.resolution;
          setResolution(data.resolution);
        }
        if (typeof data.fps === 'string' && (FPS_OPTIONS as readonly string[]).includes(data.fps)) {
          configRef.current.fps = data.fps;
          setFps(data.fps);
        }
        if (typeof data.agent === 'string' && data.agent.trim() && !userPickedAgentRef.current) {
          setSelectedAgent(data.agent.trim());
        }
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [setDesktopSessionId]);

  useEffect(() => {
    if (explicitSessionId || sessionId) return;
    let cancelled = false;
    getActiveDesktopSession()
      .then((res) => {
        if (cancelled) return;
        if (res?.restored && res.session_id) {
          const cur = usePageStore.getState().desktopSessionId;
          if (!cur) setDesktopSessionId(res.session_id);
        }
      })
      .catch(() => {
        // 忽略挂载期的瞬时网络错误，由 iframe 内同步兜底
      });
    return () => {
      cancelled = true;
    };
  }, [explicitSessionId, sessionId, setDesktopSessionId]);

  useEffect(() => {
    postToStage({ type: 'frago:desktop-visibility', visible: isActive });
  }, [isActive, postToStage]);

  useEffect(() => {
    if (!isActive) return;

    const postHotkey = (action: 'alt-right-down' | 'alt-right-up' | 'ctrl-right-down') => {
      postToStage({ type: 'frago:desktop-hotkey', action });
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
  }, [isActive, postToStage]);

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

  const updateResolution = (next: string) => {
    configRef.current.resolution = next;
    setResolution(next);
    postToStage({
      type: 'frago:desktop-config',
      resolution: next,
      fps: configRef.current.fps,
      narrator: configRef.current.narratorOn,
      mode: configRef.current.controlMode,
    });
  };

  const updateFps = (next: string) => {
    configRef.current.fps = next;
    setFps(next);
    postToStage({
      type: 'frago:desktop-config',
      resolution: configRef.current.resolution,
      fps: next,
      narrator: configRef.current.narratorOn,
      mode: configRef.current.controlMode,
    });
  };

  const toggleNarrator = () => {
    const next = !configRef.current.narratorOn;
    configRef.current.narratorOn = next;
    setNarratorOn(next);
    postToStage({
      type: 'frago:desktop-config',
      resolution: configRef.current.resolution,
      fps: configRef.current.fps,
      narrator: next,
      mode: configRef.current.controlMode,
    });
  };

  const updateControlMode = (next: ControlMode) => {
    configRef.current.controlMode = next;
    setControlMode(next);
    postToStage({
      type: 'frago:desktop-config',
      resolution: configRef.current.resolution,
      fps: configRef.current.fps,
      narrator: configRef.current.narratorOn,
      mode: next,
    });
  };

  const unlockAudio = () => {
    setSoundUnlocked(true);
    postToStage({ type: 'frago:desktop-unlock-audio', unlocked: true });
  };

  const selectVirtualApp = (next: VirtualAppKey) => {
    setActiveApp(next);
    postToStage({ type: 'frago:desktop-app', app: next });
  };

  const selectOperatorAgent = (nextAgent: string) => {
    if (!nextAgent) return;
    userPickedAgentRef.current = true;
    setSelectedAgent(nextAgent);
    postToStage({ type: 'frago:desktop-agent', agent: nextAgent });
  };

  const selectedAgentObj = orderedAgents.find((a) => a.agent_type === selectedAgent);

  // 状态栏文案：服务没连上时先说服务，再说桌面本身。
  const status = !isConnected
    ? { tone: 'error' as const, pillClass: 'warn', label: t('desktop.statusDisconnected', 'Disconnected') }
    : frameState === 'loading'
      ? { tone: 'running' as const, pillClass: '', label: t('desktop.statusLoading', 'Loading') }
      : frameState === 'error'
        ? { tone: 'error' as const, pillClass: 'warn', label: t('desktop.statusError', 'Failed to load') }
        : { tone: 'done' as const, pillClass: 'ok', label: t('desktop.statusConnected', 'Connected') };

  const showCanvas = isConnected && frameState === 'ready';

  return (
    <div className="dt-page">
      <header className="ui-page-header ph">
        <div className="ui-page-header-titles">
          <h1 className="ui-page-header-title">{t('sidebar.nav.desktop')}</h1>
          <span className="ui-page-header-meta font-mono">
            {sessionId
              ? `/app/agent_os?userInput=true&session=${sessionId.slice(0, 8)}…`
              : t('desktop.subtitle', 'Virtual desktop for the agent to work in')}
          </span>
        </div>
        <div className="ui-page-header-actions flex-wrap gap-1.5">
          <span
            className={`dt-pill ${status.pillClass} dt-status inline-flex h-[24px] items-center gap-1.5 rounded-full border px-[9px] text-[12px] ${
              status.pillClass === 'ok'
                ? 'border-border-color bg-bg-primary text-text-secondary'
                : status.pillClass === 'warn'
                  ? 'border-accent-warning-border bg-accent-warning-10 text-accent-warning'
                  : 'border-border-color bg-bg-primary text-text-secondary'
            }`}
            data-testid="desktop-status-pill"
          >
            <span
              className={`dot inline-block h-[6px] w-[6px] rounded-full ${
                status.pillClass === 'ok'
                  ? 'bg-accent-primary'
                  : status.pillClass === 'warn'
                    ? 'bg-accent-warning'
                    : 'bg-text-muted'
              }`}
            />
            {status.label}
          </span>
          <select
            className="dt-select"
            aria-label={t('desktop.resolution', { defaultValue: 'Resolution' })}
            value={resolution}
            onChange={(e) => updateResolution(e.target.value)}
          >
            {RESOLUTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select
            className="dt-select"
            aria-label={t('desktop.fps', { defaultValue: 'FPS' })}
            value={fps}
            onChange={(e) => updateFps(e.target.value)}
          >
            {FPS_OPTIONS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={`dt-pill ${narratorOn ? 'ok' : ''} inline-flex h-[24px] cursor-pointer items-center gap-1.5 rounded-full border px-[9px] text-[12px] transition-colors ${
              narratorOn
                ? 'border-accent-primary-border bg-accent-primary-10 text-accent-primary'
                : 'border-border-color bg-bg-primary text-text-secondary hover:bg-bg-hover'
            }`}
            onClick={toggleNarrator}
            aria-pressed={narratorOn}
            title={t('desktop.narratorHint', { defaultValue: 'Toggle SpeechSummarizerDaemon narrator' })}
            data-testid="desktop-narrator-toggle"
          >
            {narratorOn ? <Volume2 size={12} /> : <VolumeX size={12} />}
            <span>{narratorOn ? 'Voice: Xiaoxiao' : 'Voice: Muted'}</span>
          </button>
          <div className="ui-seg-group" role="group" aria-label={t('desktop.controlMode', { defaultValue: 'Control mode' })}>
            <button
              type="button"
              className={`ui-seg-pill ${controlMode === 'observe' ? 'ui-seg-pill--active' : ''}`}
              onClick={() => updateControlMode('observe')}
              aria-pressed={controlMode === 'observe'}
            >
              {t('desktop.observe', { defaultValue: 'Observe' })}
            </button>
            <button
              type="button"
              className={`ui-seg-pill ${controlMode === 'takeover' ? 'ui-seg-pill--active' : ''}`}
              onClick={() => updateControlMode('takeover')}
              aria-pressed={controlMode === 'takeover'}
            >
              {t('desktop.takeover', { defaultValue: 'Takeover' })}
            </button>
          </div>
          <button
            type="button"
            className="ui-icon-btn"
            onClick={reload}
            title={t('desktop.reload', 'Reload desktop')}
            aria-label={t('desktop.reload', 'Reload desktop')}
          >
            <RefreshCw size={15} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            className={`dt-compact-btn ${soundUnlocked ? 'dt-compact-btn--on' : ''}`}
            onClick={unlockAudio}
            aria-pressed={soundUnlocked}
            data-testid="desktop-audio-unlock"
          >
            {soundUnlocked ? 'Audio Ready' : 'Unlock'}
          </button>
        </div>
      </header>

      <div
        className="dt-toolbar flex shrink-0 flex-wrap items-center gap-2 border-b border-border-color bg-bg-secondary px-[20px] py-[6px]"
        data-testid="desktop-compact-toolbar"
      >
        <select
          className="dt-select dt-select--sm"
          aria-label={t('desktop.virtualApp', { defaultValue: 'Virtual App' })}
          value={activeApp}
          onChange={(e) => selectVirtualApp(e.target.value as VirtualAppKey)}
        >
          {VIRTUAL_APPS.map((app) => (
            <option key={app.key} value={app.key}>
              {app.label}
            </option>
          ))}
        </select>
        <div className="ui-seg-group" role="group" aria-label={t('desktop.virtualAppSwitcher', { defaultValue: 'Virtual app view' })}>
          {VIRTUAL_APPS.map((app) => (
            <button
              key={app.key}
              type="button"
              className={`ui-seg-pill ${activeApp === app.key ? 'ui-seg-pill--active' : ''}`}
              onClick={() => selectVirtualApp(app.key)}
              aria-pressed={activeApp === app.key}
            >
              {app.short}
            </button>
          ))}
        </div>
        <div className="dt-agent-selector ml-auto flex items-center gap-1.5" data-testid="desktop-agent-selector">
          <span className="text-[11px] font-medium text-text-muted">
            {t('desktop.agentLabel', { defaultValue: 'Agent' })}
          </span>
          <select
            className="dt-select dt-select--sm dt-select--agent"
            aria-label={t('desktop.operatorAgent', { defaultValue: 'Operator Agent' })}
            data-testid="desktop-agent-select"
            value={selectedAgent}
            onChange={(e) => selectOperatorAgent(e.target.value)}
            disabled={orderedAgents.length > 0 && selectableAgents.length === 0}
            title={
              selectedAgentObj && !selectedAgentObj.selectable && selectedAgentObj.reason
                ? (agentReasonText(selectedAgentObj.reason) ?? selectedAgentObj.reason)
                : t('desktop.operatorAgentHint', { defaultValue: 'Select desktop-operator agent kernel' })
            }
          >
            {orderedAgents.length === 0 ? (
              <option value="">
                {loadingAgents
                  ? t('desktop.agentsLoading', { defaultValue: 'Probing agents…' })
                  : t('desktop.agentAuto', { defaultValue: 'Auto' })}
              </option>
            ) : (
              <>
                {selectableAgents.length === 0 && (
                  <option value="" disabled>
                    {t('desktop.noAgentAvailable', { defaultValue: 'No available agent' })}
                  </option>
                )}
                {orderedAgents.map((a) => {
                  const reason = !a.selectable && a.reason ? agentReasonText(a.reason) : null;
                  return (
                    <option
                      key={a.agent_type}
                      value={a.agent_type}
                      disabled={!a.selectable}
                      title={reason ?? undefined}
                    >
                      {a.display_name}
                      {reason ? ` — ${reason}` : ''}
                    </option>
                  );
                })}
              </>
            )}
          </select>
        </div>
      </div>

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
            postToStage({
              type: 'frago:desktop-visibility',
              visible: usePageStore.getState().currentPage === 'desktop',
            });
            postToStage({
              type: 'frago:desktop-config',
              resolution,
              fps,
              narrator: narratorOn,
              mode: controlMode,
            });
            postToStage({
              type: 'frago:desktop-app',
              app: activeApp,
            });
            if (selectedAgent) {
              postToStage({
                type: 'frago:desktop-agent',
                agent: selectedAgent,
              });
            }
            if (soundUnlocked) {
              postToStage({
                type: 'frago:desktop-unlock-audio',
                unlocked: true,
              });
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
