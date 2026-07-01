import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getClaudeSessions } from '@/api';
import type { ClaudeSessionItem, ClaudeSessionHuman } from '@/api/client';

/**
 * useSessionsList — owns the session list state: fetching, day range,
 * search, human/maybe/agent filters, derived counts/visible, and copy.
 */
export function useSessionsList() {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  const [sessions, setSessions] = useState<ClaudeSessionItem[]>([]);
  const [scannedFiles, setScannedFiles] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Record<ClaudeSessionHuman, boolean>>({
    human: true,
    maybe: true,
    agent: false,
  });
  const [copiedSid, setCopiedSid] = useState<string | null>(null);

  const fetchSessions = useCallback(async (lookbackDays: number) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getClaudeSessions({ days: lookbackDays });
      setSessions(res.sessions);
      setScannedFiles(res.scanned_files);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSessions(days);
  }, [days, fetchSessions]);

  const counts = useMemo(() => {
    const c: Record<ClaudeSessionHuman, number> = { human: 0, maybe: 0, agent: 0 };
    for (const s of sessions) c[s.human] += 1;
    return c;
  }, [sessions]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sessions.filter((s) => {
      if (!filters[s.human]) return false;
      if (!q) return true;
      const haystack = [
        s.title,
        s.name,
        s.ai_title,
        s.recap,
        s.first_user_full,
        s.project,
        s.branch,
        s.sid,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [sessions, filters, search]);

  const handleCopy = useCallback(
    async (cmd: string, sid: string) => {
      try {
        await navigator.clipboard.writeText(cmd);
        setCopiedSid(sid);
        showToast(t('claudeSessions.copied'), 'success');
        setTimeout(() => setCopiedSid((cur) => (cur === sid ? null : cur)), 1500);
      } catch {
        showToast(t('claudeSessions.copyFailed'), 'error');
      }
    },
    [showToast, t]
  );

  const toggleFilter = (key: ClaudeSessionHuman) =>
    setFilters((f) => ({ ...f, [key]: !f[key] }));

  return {
    t,
    sessions,
    scannedFiles,
    loading,
    error,
    days,
    setDays,
    search,
    setSearch,
    filters,
    toggleFilter,
    copiedSid,
    counts,
    visible,
    fetchSessions,
    handleCopy,
  };
}
