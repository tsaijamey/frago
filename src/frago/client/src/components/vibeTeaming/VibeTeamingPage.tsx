/**
 * vibe teaming：两个人的会话并排摆着。
 *
 * 左边是本机这场会话，右边是对方那场。两列用的是同一个记录流组件，因为两家的记录
 * 在离开各自机器之前就已经被翻译成同一种形状了——双列能成立，靠的是这件事，不是
 * 这一页做了什么特别的适配。
 *
 * **右边那列是只读的。** 人不能在这一页替对方说话；能做的是让**自己的 agent** 往
 * 对方的会话里投一条消息（底下那个输入框），它落到对方那边是一条带前缀的用户发言。
 * 这条区别是整个功能的要害：两边各自的 agent 仍然只听自己主人的，队友的话进来时
 * 带着标记，看得出不是主人说的。
 */

import { useEffect, useMemo, useState } from 'react';
import { usePageStore } from '@/stores/pageStore';
import { useTranslation } from 'react-i18next';
import { Link2, LogOut, Plus, RefreshCw, Send } from 'lucide-react';

import RecordStream from '@/components/sessionWorkbench/RecordStream';
import { useWorkbenchRecords } from '@/hooks/useWorkbenchRecords';
import {
  joinTeam,
  leaveTeam,
  openTeam,
  sendToPeer,
  usePeerRecords,
  useTeamState,
  type TeamBinding,
} from '@/hooks/useTeam';

const ICON = { size: 16, strokeWidth: 1.5 } as const;

export default function VibeTeamingPage() {
  const { t } = useTranslation();
  const { state, error: stateError, loading, reload } = useTeamState();
  const [selected, setSelected] = useState<string | null>(null);

  const active = useMemo(() => (state?.teams ?? []).filter((one) => one.active), [state]);

  // 没选或选的那个已经退出了，就落到第一个还在的上面。人退出一个 team 之后不该
  // 盯着一列空白发愣。
  useEffect(() => {
    if (active.length === 0) {
      setSelected(null);
      return;
    }
    if (!selected || !active.some((one) => one.code === selected)) {
      setSelected(active[0].code);
    }
  }, [active, selected]);

  const binding = active.find((one) => one.code === selected) ?? null;

  if (loading) {
    return <div className="p-6 text-sm text-fg-muted">{t('team.loading')}</div>;
  }

  if (stateError) {
    return <div className="p-6 text-sm text-danger">{stateError}</div>;
  }

  if (!state?.configured) {
    return <NotConfigured relayUrl={state?.relay_url ?? ''} />;
  }

  return (
    <div className="flex h-full flex-col">
      <TeamBar
        teams={active}
        selected={selected}
        onSelect={setSelected}
        onChanged={reload}
      />
      {binding ? (
        <PairedColumns binding={binding} prefix={state.prefix} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-sm text-fg-muted">
          {t('team.empty')}
        </div>
      )}
    </div>
  );
}

/** 中继还没配好时这一页说什么。 */
function NotConfigured({ relayUrl }: { relayUrl: string }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl p-8">
      <h2 className="text-base font-medium">{t('team.setupTitle')}</h2>
      <p className="mt-2 text-sm text-fg-muted">{t('team.setupWhy')}</p>
      {/* 命令原样摆出来。这一步要敲口令，而口令只能在提示符里敲——把它做成界面上
          的输入框，等于把口令放进一个会被浏览器记住、会进日志的地方。 */}
      <pre className="mt-4 overflow-x-auto rounded-md bg-surface-2 p-3 text-xs">
        {`frago team config --url ${relayUrl || 'https://你的服务器'} \\\n  --email 你在那台服务器上的账号 --ask-password`}
      </pre>
      <p className="mt-3 text-xs text-fg-muted">{t('team.setupNote')}</p>
    </div>
  );
}

/** 顶上那条：现在在哪些 team 里，加一个、退一个。 */
function TeamBar({
  teams,
  selected,
  onSelect,
  onChanged,
}: {
  teams: TeamBinding[];
  selected: string | null;
  onSelect: (code: string) => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joining, setJoining] = useState(false);
  const [code, setCode] = useState('');

  // 这一页参加 team 用的是哪一场会话：工作台中栏此刻停着的那一场。拿不到就让人
  // 先去工作台挑一场——替他挑一场是这类界面最常见的坏法，挑错了他要过很久才发现。
  const sessionId = useSelectedSessionId();

  const guard = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b border-border px-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        {teams.map((one) => (
          <button
            key={one.code}
            onClick={() => onSelect(one.code)}
            className={`rounded-md px-2.5 py-1 font-mono text-xs ${
              one.code === selected ? 'bg-accent text-on-accent' : 'bg-surface-2 text-fg-muted'
            }`}
          >
            {one.code}
            <span className="ml-1.5 opacity-70">{one.side}</span>
          </button>
        ))}

        <button
          disabled={busy || !sessionId}
          onClick={() => void guard(() => openTeam(sessionId!))}
          className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-surface-2 disabled:opacity-40"
          title={sessionId ? t('team.openHint') : t('team.needSession')}
        >
          <Plus {...ICON} />
          {t('team.open')}
        </button>

        {joining ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!code.trim() || !sessionId) return;
              void guard(() => joinTeam(code.trim().toUpperCase(), sessionId)).then(() => {
                setCode('');
                setJoining(false);
              });
            }}
            className="flex items-center gap-1"
          >
            <input
              autoFocus
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder={t('team.codePlaceholder')}
              maxLength={6}
              className="w-24 rounded-md border border-border bg-surface px-2 py-1 font-mono text-xs"
            />
            <button type="submit" disabled={busy} className="text-xs text-accent">
              {t('team.join')}
            </button>
          </form>
        ) : (
          <button
            disabled={!sessionId}
            onClick={() => setJoining(true)}
            className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-surface-2 disabled:opacity-40"
          >
            <Link2 {...ICON} />
            {t('team.joinWithCode')}
          </button>
        )}

        {selected && (
          <button
            disabled={busy}
            onClick={() => void guard(() => leaveTeam(selected))}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-xs text-fg-muted hover:bg-surface-2"
            title={t('team.leaveHint')}
          >
            <LogOut {...ICON} />
            {t('team.leave')}
          </button>
        )}
      </div>
      {error && <p className="mt-1.5 text-xs text-danger">{error}</p>}
      {!sessionId && <p className="mt-1.5 text-xs text-fg-muted">{t('team.needSession')}</p>}
    </div>
  );
}

/** 工作台中栏此刻停着的那一场会话。
 *
 * 直接读工作台自己记的那一个，不另存一份：两处各记一份「当前是哪一场」，迟早会在
 * 人换会话时分叉，而分叉出来的结果是 team 绑到了另一场会话上——人以为队友在看他
 * 现在这一场，队友看到的是他半小时前那一场。
 */
function useSelectedSessionId(): string | null {
  return usePageStore((s) => s.workbenchSessionId);
}

/** 两列正文。 */
function PairedColumns({ binding, prefix }: { binding: TeamBinding; prefix: string }) {
  const { t } = useTranslation();
  const mine = useWorkbenchRecords(binding.session_id, { live: true });
  const peer = usePeerRecords(binding.code);

  return (
    <div className="grid flex-1 grid-cols-2 gap-px overflow-hidden bg-border">
      <section className="flex min-w-0 flex-col bg-surface">
        <ColumnHeader title={t('team.mine')} subtitle={binding.session_id} />
        <div className="min-h-0 flex-1 overflow-auto">
          <RecordStream
            sessionId={binding.session_id}
            records={mine.records}
            loading={mine.loading}
            loadingOlder={mine.loadingOlder}
            hasOlder={mine.hasOlder}
            error={mine.error}
            onLoadOlder={() => void mine.loadOlder()}
            awaitingAgent={mine.awaitingAgent}
          />
        </div>
      </section>

      <section className="flex min-w-0 flex-col bg-surface">
        <ColumnHeader
          title={t('team.peer')}
          subtitle={
            peer.status?.peer_present ? t('team.peerPresent') : t('team.peerAbsent')
          }
          action={
            <button
              onClick={() => void peer.reload()}
              className="rounded-md p-1 text-fg-muted hover:bg-surface-2"
              title={t('team.refresh')}
            >
              <RefreshCw {...ICON} />
            </button>
          }
        />
        <div className="min-h-0 flex-1 overflow-auto">
          <RecordStream
            sessionId={binding.code}
            records={peer.records}
            loading={peer.loading}
            loadingOlder={false}
            hasOlder={false}
            error={peer.error}
            onLoadOlder={() => {}}
          />
        </div>
        <PeerComposer code={binding.code} prefix={prefix} onSent={() => void peer.reload()} />
      </section>
    </div>
  );
}

function ColumnHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: React.ReactNode;
}) {
  return (
    <header className="flex items-center gap-2 border-b border-border px-3 py-2">
      <span className="text-xs font-medium">{title}</span>
      <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-fg-muted">
        {subtitle}
      </span>
      {action}
    </header>
  );
}

/** 往对方会话投一条消息。 */
function PeerComposer({
  code,
  prefix,
  onSent,
}: {
  code: string;
  prefix: string;
  onSent: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await sendToPeer(code, text.trim());
      setText('');
      onSent();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-border p-2">
      {/* 前缀原样摆在输入框上面。人要知道这句话落到对方那边长什么样——不摆出来，
          他会按「跟对方本人说话」的口气写，而读到它的是对方的 agent。 */}
      <p className="mb-1 truncate text-[11px] text-fg-muted" title={prefix}>
        {prefix.replace('{code}', code)}
      </p>
      <div className="flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit();
          }}
          rows={2}
          placeholder={t('team.composerPlaceholder')}
          className="min-w-0 flex-1 resize-none rounded-md border border-border bg-surface px-2 py-1.5 text-sm"
        />
        <button
          onClick={() => void submit()}
          disabled={busy || !text.trim()}
          className="self-end rounded-md bg-accent px-3 py-1.5 text-on-accent disabled:opacity-40"
          title={t('team.sendHint')}
        >
          <Send {...ICON} />
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}
