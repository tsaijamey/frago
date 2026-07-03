/**
 * TokenCalendarModal — monthly calendar of per-day Claude token usage.
 *
 * Opens over the sessions page; each request (open / month switch / refresh)
 * is a single synchronous GET — the backend computes incrementally against its
 * file-level cache, so repeat views are sub-second. While a request is pending
 * an indeterminate progress bar shows above the grid.
 */

import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, RefreshCw, X } from 'lucide-react';
import type { TFunction } from 'i18next';
import { getTokenCalendar } from '@/api';
import type { TokenCalendarResponse } from '@/api/client';
import { formatTokens, monthMatrix, shiftMonth, toDateKey } from './tokenCalendarUtils';

interface Props {
  t: TFunction;
  onClose: () => void;
}

function currentMonth(): string {
  return toDateKey(new Date()).slice(0, 7);
}

export default function TokenCalendarModal({ t, onClose }: Props) {
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState<TokenCalendarResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMonth = useCallback(async (m: string) => {
    setLoading(true);
    setError(null);
    try {
      setData(await getTokenCalendar(m));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMonth(month);
  }, [month, fetchMonth]);

  const [y, m] = month.split('-').map(Number);
  const todayKey = toDateKey(new Date());
  const weeks = monthMatrix(month);
  const weekdayKeys = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

  return (
    <div className="cs-cal-overlay" onClick={onClose}>
      <div
        className="cs-cal-card"
        role="dialog"
        aria-label={t('claudeSessions.tokenCalendar.title')}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cs-cal-header">
          <div className="cs-cal-month-nav">
            <button
              type="button"
              className="cs-cal-nav-btn"
              onClick={() => setMonth((cur) => shiftMonth(cur, -1))}
              aria-label={t('claudeSessions.tokenCalendar.prevMonth')}
            >
              <ChevronLeft size={16} />
            </button>
            <span className="cs-cal-month-label">
              {t('claudeSessions.tokenCalendar.monthLabel', {
                year: y,
                month: m,
                month2: String(m).padStart(2, '0'),
              })}
            </span>
            <button
              type="button"
              className="cs-cal-nav-btn"
              onClick={() => setMonth((cur) => shiftMonth(cur, 1))}
              aria-label={t('claudeSessions.tokenCalendar.nextMonth')}
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <div className="cs-cal-total">
            {t('claudeSessions.tokenCalendar.monthTotal')}:{' '}
            <strong>{data ? formatTokens(data.month_total.total) : '—'}</strong>
          </div>
          <div className="cs-cal-actions">
            <button
              type="button"
              className="cs-cal-nav-btn"
              onClick={() => fetchMonth(month)}
              disabled={loading}
              title={t('claudeSessions.tokenCalendar.refresh')}
            >
              <RefreshCw size={14} className={loading ? 'cs-spin' : ''} />
            </button>
            <button
              type="button"
              className="cs-cal-nav-btn"
              onClick={onClose}
              aria-label={t('claudeSessions.tokenCalendar.close')}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {loading && <div className="cs-cal-progress"><div className="cs-cal-progress-bar" /></div>}
        {error && (
          <div className="cs-cal-error">
            {t('claudeSessions.tokenCalendar.error', { error })}{' '}
            <button type="button" className="cs-cal-retry" onClick={() => fetchMonth(month)}>
              {t('claudeSessions.tokenCalendar.retry')}
            </button>
          </div>
        )}

        <div className="cs-cal-grid">
          {weekdayKeys.map((k) => (
            <div key={k} className="cs-cal-weekday">
              {t(`claudeSessions.tokenCalendar.weekday.${k}`)}
            </div>
          ))}
          {weeks.flat().map((cell) => {
            const bucket = data?.days[cell.date];
            return (
              <div
                key={cell.date}
                className={[
                  'cs-cal-cell',
                  cell.inMonth ? '' : 'cs-cal-cell-out',
                  cell.date === todayKey ? 'cs-cal-cell-today' : '',
                ].join(' ').trim()}
                title={
                  bucket
                    ? t('claudeSessions.tokenCalendar.cellTooltip', {
                        input: formatTokens(bucket.input),
                        output: formatTokens(bucket.output),
                        cacheCreation: formatTokens(bucket.cache_creation),
                        cacheRead: formatTokens(bucket.cache_read),
                      })
                    : undefined
                }
              >
                <span className="cs-cal-day">{cell.day}</span>
                <span className="cs-cal-tokens">
                  {bucket ? formatTokens(bucket.total) : '—'}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
