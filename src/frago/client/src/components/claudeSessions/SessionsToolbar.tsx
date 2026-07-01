import type { TFunction } from 'i18next';
import { Search, X } from 'lucide-react';
import type { ClaudeSessionHuman } from '@/api/client';
import { DAY_OPTIONS, HUMAN_META } from './sessionUtils';

interface SessionsToolbarProps {
  t: TFunction;
  days: number;
  setDays: (d: number) => void;
  search: string;
  setSearch: (s: string) => void;
  filters: Record<ClaudeSessionHuman, boolean>;
  toggleFilter: (key: ClaudeSessionHuman) => void;
  counts: Record<ClaudeSessionHuman, number>;
}

export default function SessionsToolbar({
  t,
  days,
  setDays,
  search,
  setSearch,
  filters,
  toggleFilter,
  counts,
}: SessionsToolbarProps) {
  return (
    <div className="cs-toolbar">
      {/* Date range */}
      <div className="cs-segment">
        {DAY_OPTIONS.map((d) => (
          <button
            key={d}
            type="button"
            className={`cs-segment-btn ${days === d ? 'active' : ''}`}
            onClick={() => setDays(d)}
          >
            {t('claudeSessions.days', { count: d })}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="cs-search">
        <Search size={14} className="cs-search-icon" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('claudeSessions.searchPlaceholder')}
        />
        {search && (
          <button type="button" className="cs-search-clear" onClick={() => setSearch('')}>
            <X size={13} />
          </button>
        )}
      </div>

      {/* Filter pills */}
      <div className="cs-pills">
        {(['human', 'maybe', 'agent'] as ClaudeSessionHuman[]).map((key) => {
          const meta = HUMAN_META[key];
          const active = filters[key];
          return (
            <button
              key={key}
              type="button"
              className={`cs-pill ${active ? 'active' : ''}`}
              style={active ? { borderColor: meta.color, color: meta.color } : undefined}
              onClick={() => toggleFilter(key)}
            >
              <meta.Icon size={13} />
              <span>{t(meta.labelKey)}</span>
              <span className="cs-pill-count">{counts[key]}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
