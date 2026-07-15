import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/stores/appStore';
import { getPaSessions } from '@/api';
import type { PaSessionItem } from '@/api/client';

/**
 * usePaSessionsList — owns the PA-sessions tab state: the resident
 * conversations PA itself is holding open (one per conv_key), fetched fresh
 * each time the tab is shown.
 */
export function usePaSessionsList() {
  const { t } = useTranslation();
  const showToast = useAppStore((s) => s.showToast);

  const [sessions, setSessions] = useState<PaSessionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copiedSid, setCopiedSid] = useState<string | null>(null);

  const fetchPaSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getPaSessions();
      setSessions(res.sessions);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPaSessions();
  }, [fetchPaSessions]);

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

  return {
    t,
    sessions,
    loading,
    error,
    copiedSid,
    fetchPaSessions,
    handleCopy,
  };
}
