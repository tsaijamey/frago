/**
 * NewSessionModal — start a Claude session from the browser.
 *
 * Creating a session is exactly what the existing list already tracks, so this
 * deliberately produces a *normal* session rather than a special web-only one:
 * the page mints a fresh session uuid and posts the first turn to the same
 * `/claude-sessions/{sid}/send` endpoint every existing row uses. Claude starts
 * with `--session-id <uuid>` in the chosen directory, writes its transcript to
 * the usual place, and the next scan picks it up as an ordinary row — same
 * detail panel, same send path, same data.
 *
 * The directory matters: the backend has always accepted one, but nothing in
 * the UI ever sent it, so browser-started sessions all landed in the home
 * directory. Picking it here is the whole point of the dialog.
 */

import { useEffect, useState } from 'react';
import { Folder, Home } from 'lucide-react';
import Modal from '../ui/Modal';
import { getSystemDirectories } from '../../api/client';
import { getRecentDirectories, addRecentDirectory } from '../../utils/recentDirectories';

interface NewSessionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (sid: string) => void;
}

interface DirChoice {
  path: string;
  hint?: string;
}

export default function NewSessionModal({ isOpen, onClose, onCreated }: NewSessionModalProps) {
  const [choices, setChoices] = useState<DirChoice[]>([]);
  const [dir, setDir] = useState('');
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setText('');
    setError(null);

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

  const canSubmit = dir.trim().length > 0 && text.trim().length > 0;

  const handleCreate = () => {
    if (!canSubmit) return;
    setError(null);

    // A fresh uuid IS the session id — claude is launched with `--session-id`,
    // so the transcript lands at <projects>/<encoded-cwd>/<uuid>.jsonl and the
    // row that appears in the list is keyed by this exact value.
    const sid = crypto.randomUUID();

    // Deliberately not awaited: /send only returns once claude has finished the
    // whole first turn, which can take minutes. Blocking the dialog on that
    // would leave the user staring at a spinner long after the session exists.
    // The detail panel already knows how to poll for a reply that has not
    // landed yet — the same path every existing session uses — so hand off to
    // it immediately and let it show the "activating" state.
    fetch(`/api/claude-sessions/${sid}/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.trim(), cwd: dir.trim() }),
    }).catch(() => {
      // Network-level failure only; the panel surfaces per-turn errors itself.
    });

    addRecentDirectory(dir.trim());
    onCreated(sid);
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="新建会话">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <label className="text-xs font-medium text-[var(--text-secondary)]">起始目录</label>
          <p className="text-[11px] text-[var(--text-muted)] -mt-1">
            会话在该目录下启动，等同于在这里打开终端后运行 claude。
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
          <label className="text-xs font-medium text-[var(--text-secondary)]">第一句话</label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                handleCreate();
              }
            }}
            rows={3}
            placeholder="要它做什么…"
            className="resize-none bg-[var(--bg-subtle)] border border-[var(--border-color)] rounded-md px-3 py-2 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent-primary)]"
          />
        </div>

        {error && (
          <p className="text-xs text-[var(--accent-error)] break-words">创建失败：{error}</p>
        )}

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 rounded-md text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={!canSubmit}
            className="flex items-center gap-2 px-4 py-2 rounded-md text-xs font-semibold bg-[var(--accent-primary)] text-[var(--text-on-accent)] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            创建
          </button>
        </div>
      </div>
    </Modal>
  );
}
