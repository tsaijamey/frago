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
import { CalendarDays, RefreshCw, Plus } from 'lucide-react';
import { useSessionsList } from './useSessionsList';
import { usePaSessionsList } from './usePaSessionsList';
import { useSessionDetail } from './useSessionDetail';
import { useSessionActivity } from './useSessionActivity';
import SessionsToolbar from './SessionsToolbar';
import SessionList from './SessionList';
import PaSessionList from './PaSessionList';
import SessionDetailPanel from './SessionDetailPanel';
import TokenCalendarModal from './TokenCalendarModal';
import NewSessionModal from './NewSessionModal';

type Tab = 'all' | 'pa';

export default function ClaudeSessionsPage() {
  const [tab, setTab] = useState<Tab>('all');
  const [newSessionOpen, setNewSessionOpen] = useState(false);

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
    t: tPa,
    sessions: paSessions,
    loading: paLoading,
    error: paError,
    copiedSid: paCopiedSid,
    fetchPaSessions,
    handleCopy: handlePaCopy,
  } = usePaSessionsList();

  // Shared multi-session background-keepalive engine: keeps every session the
  // user has sent into alive in the background and flags unread replies.
  const sessionActivity = useSessionActivity();

  const {
    detailSid,
    detailTitle,
    detail,
    detailLoading,
    input,
    setInput,
    images,
    addImageFiles,
    removeImage,
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
  } = useSessionDetail(sessionActivity);

  const [calendarOpen, setCalendarOpen] = useState(false);

  return (
    <div className="cs-page">
      {/* Header */}
      <div className="cs-header">
        <div>
          <h1 className="cs-title">{t('claudeSessions.title')}</h1>
          <p className="cs-subtitle">{t('claudeSessions.subtitle')}</p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--spacing-sm)' }}>
          {/* Creates an ordinary session in a chosen directory — it lands in
              this same list and uses the same detail panel. */}
          <button
            type="button"
            className="cs-refresh cs-refresh--primary"
            onClick={() => setNewSessionOpen(true)}
            title={t('claudeSessions.newSession')}
          >
            <Plus size={15} />
            <span>{t('claudeSessions.newSession')}</span>
          </button>
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
            onClick={() => (tab === 'pa' ? fetchPaSessions() : fetchSessions(days))}
            disabled={tab === 'pa' ? paLoading : loading}
            title={t('claudeSessions.rescan')}
          >
            <RefreshCw size={15} className={(tab === 'pa' ? paLoading : loading) ? 'cs-spin' : ''} />
            <span>{t('claudeSessions.rescan')}</span>
          </button>
        </div>
      </div>

      {calendarOpen && <TokenCalendarModal t={t} onClose={() => setCalendarOpen(false)} />}

      <NewSessionModal
        isOpen={newSessionOpen}
        onClose={() => setNewSessionOpen(false)}
        onCreated={async (sid) => {
          // Open the panel at once — it polls for the first reply on its own.
          openDetail(sid);
          // The row cannot appear until claude has written its transcript, which
          // lags the click by a few seconds, so rescan on a short backoff rather
          // than once. Cheap, and it stops the list looking empty meanwhile.
          for (const delay of [1500, 3000, 6000, 12000]) {
            await new Promise((r) => setTimeout(r, delay));
            await fetchSessions(days);
          }
        }}
      />

      <div className="cs-segment" style={{ alignSelf: 'flex-start' }}>
        <button
          type="button"
          className={`cs-segment-btn ${tab === 'all' ? 'active' : ''}`}
          onClick={() => setTab('all')}
        >
          {t('claudeSessions.tabs.all')}
        </button>
        <button
          type="button"
          className={`cs-segment-btn ${tab === 'pa' ? 'active' : ''}`}
          onClick={() => setTab('pa')}
        >
          {t('claudeSessions.tabs.pa')}
        </button>
      </div>

      {/* Split view: the list keeps its own scroll on the left and stays
          clickable while a session is open on the right. */}
      <div className="cs-split">
        <div className="cs-main">
          {tab === 'all' ? (
            <>
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
                activity={sessionActivity.activity}
                openDetail={openDetail}
                handleCopy={handleCopy}
              />
            </>
          ) : (
            <PaSessionList
              t={tPa}
              loading={paLoading}
              error={paError}
              sessions={paSessions}
              detailSid={detailSid}
              copiedSid={paCopiedSid}
              activity={sessionActivity.activity}
              onRefresh={fetchPaSessions}
              openDetail={openDetail}
              handleCopy={handlePaCopy}
            />
          )}
        </div>

        {detailSid && (
          <div className="cs-side">
            <SessionDetailPanel
              t={t}
              sessions={sessions}
              detailSid={detailSid}
              detailTitle={detailTitle}
              detail={detail}
              detailLoading={detailLoading}
              input={input}
              setInput={setInput}
              images={images}
              addImageFiles={addImageFiles}
              removeImage={removeImage}
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
          </div>
        )}
      </div>
    </div>
  );
}
