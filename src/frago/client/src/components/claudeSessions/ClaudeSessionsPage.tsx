/**
 * ClaudeSessionsPage — Web dashboard homepage for managing Claude Code sessions.
 *
 * Scans ~/.claude/projects via /api/claude-sessions and lets the user browse,
 * filter (human / maybe / agent), search, copy a `claude --resume` command, and
 * peek at a session's message stream in a side panel.
 *
 * Inspired by the claude_sessions_dashboard recipe's view mode, rebuilt as a
 * native in-app React page using the shared theme tokens.
 */

import { useState } from 'react';
import { CalendarDays, RefreshCw } from 'lucide-react';
import { useSessionsList } from './useSessionsList';
import { useSessionDetail } from './useSessionDetail';
import SessionsToolbar from './SessionsToolbar';
import SessionList from './SessionList';
import SessionDetailPanel from './SessionDetailPanel';
import TokenCalendarModal from './TokenCalendarModal';

export default function ClaudeSessionsPage() {
  const {
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
  } = useSessionsList();

  const {
    detailSid,
    detail,
    detailLoading,
    input,
    setInput,
    sending,
    sendError,
    activation,
    pollStalled,
    streamRef,
    handleStreamScroll,
    openDetail,
    closeDetail,
    handleSend,
    refreshDetail,
  } = useSessionDetail();

  const [calendarOpen, setCalendarOpen] = useState(false);

  return (
    <div className="page-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--spacing-md)' }}>
      {/* Header */}
      <div className="cs-header">
        <div>
          <h1 className="cs-title">{t('claudeSessions.title')}</h1>
          <p className="cs-subtitle">{t('claudeSessions.subtitle')}</p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
          <button
            type="button"
            className="cs-refresh"
            onClick={() => setCalendarOpen(true)}
            title={t('claudeSessions.tokenCalendar.open')}
          >
            <CalendarDays size={15} />
            <span>{t('claudeSessions.tokenCalendar.open')}</span>
          </button>
          <button
            type="button"
            className="cs-refresh"
            onClick={() => fetchSessions(days)}
            disabled={loading}
            title={t('claudeSessions.rescan')}
          >
            <RefreshCw size={15} className={loading ? 'cs-spin' : ''} />
            <span>{t('claudeSessions.rescan')}</span>
          </button>
        </div>
      </div>

      {calendarOpen && <TokenCalendarModal t={t} onClose={() => setCalendarOpen(false)} />}

      <SessionsToolbar
        t={t}
        days={days}
        setDays={setDays}
        search={search}
        setSearch={setSearch}
        filters={filters}
        toggleFilter={toggleFilter}
        counts={counts}
      />

      <SessionList
        t={t}
        loading={loading}
        error={error}
        visible={visible}
        sessions={sessions}
        scannedFiles={scannedFiles}
        detailSid={detailSid}
        copiedSid={copiedSid}
        openDetail={openDetail}
        handleCopy={handleCopy}
      />

      {/* Detail side panel */}
      {detailSid && (
        <SessionDetailPanel
          t={t}
          sessions={sessions}
          detailSid={detailSid}
          detail={detail}
          detailLoading={detailLoading}
          input={input}
          setInput={setInput}
          sending={sending}
          sendError={sendError}
          activation={activation}
          pollStalled={pollStalled}
          streamRef={streamRef}
          handleStreamScroll={handleStreamScroll}
          closeDetail={closeDetail}
          handleSend={handleSend}
          refreshDetail={refreshDetail}
          handleCopy={handleCopy}
        />
      )}
    </div>
  );
}
