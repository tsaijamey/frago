import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { DecisionInboxItem, ResolveDecisionRequest } from '@/api';
import { resolveEmployeeColor } from '@/components/employees/employeeMeta';
import type { DecisionInboxHookState, DecisionInboxTab } from '@/hooks/useDecisionInbox';

export interface DecisionInboxViewProps {
  inbox: DecisionInboxHookState;
  onBackToSessions: () => void;
  onOpenSession: (sessionId: string) => void;
}

function isChoiceLike(item: DecisionInboxItem): boolean {
  return (
    item.action_type === 'choice' ||
    item.action_type === 'single-choice' ||
    item.action_type === 'multi-choice' ||
    item.action_type === 'binary' ||
    (item.action_type === 'choice-and-text' && item.options.length > 0)
  );
}

function isMultiChoice(item: DecisionInboxItem): boolean {
  return item.action_type === 'multi-choice' || (item.action_type === 'choice-and-text' && !!item.multi);
}

function formatEpoch(ts: number | null | undefined): string {
  if (!ts || !Number.isFinite(ts)) return '—';
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function DecisionInboxView({
  inbox,
  onBackToSessions,
  onOpenSession,
}: DecisionInboxViewProps) {
  const { t } = useTranslation();
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [choiceMap, setChoiceMap] = useState<Record<string, string>>({});
  const [choicesMap, setChoicesMap] = useState<Record<string, string[]>>({});
  const [answerMap, setAnswerMap] = useState<Record<string, string>>({});
  const [noteMap, setNoteMap] = useState<Record<string, string>>({});

  const filteredQueue = useMemo(() => {
    const items = inbox.items;
    if (inbox.activeTab === 'pending') {
      return items.filter((i) => i.status === 'pending');
    }
    if (inbox.activeTab === 'schedule') {
      return items.filter((i) => i.status === 'pending' && i.source === 'schedule');
    }
    if (inbox.activeTab === 'session') {
      return items.filter((i) => i.status === 'pending' && i.source === 'session');
    }
    return items.filter((i) => i.status === 'snoozed');
  }, [inbox.activeTab, inbox.items]);

  const selected = useMemo(
    () =>
      filteredQueue.find((i) => i.proposal_id === inbox.selectedProposalId) ??
      filteredQueue[0] ??
      null,
    [filteredQueue, inbox.selectedProposalId],
  );

  useEffect(() => {
    if (selected && selected.proposal_id !== inbox.selectedProposalId) {
      inbox.setSelectedProposalId(selected.proposal_id);
    }
  }, [inbox, selected]);

  const handleSelectItem = (proposalId: string) => {
    inbox.setSelectedProposalId(proposalId);
    setConfirmingId(null);
  };

  const handleSetTab = (tab: DecisionInboxTab) => {
    inbox.setActiveTab(tab);
    setConfirmingId(null);
  };

  const getSingleChoice = (item: DecisionInboxItem): string | null => {
    if (Object.prototype.hasOwnProperty.call(choiceMap, item.proposal_id)) {
      return choiceMap[item.proposal_id];
    }
    return item.selected_opt ?? item.recommended ?? item.options[0]?.key ?? null;
  };

  const getMultiChoices = (item: DecisionInboxItem): string[] => {
    if (Object.prototype.hasOwnProperty.call(choicesMap, item.proposal_id)) {
      return choicesMap[item.proposal_id];
    }
    const def = item.selected_opt ?? item.recommended;
    return def ? [def] : [];
  };

  const getAnswerText = (item: DecisionInboxItem): string => {
    if (Object.prototype.hasOwnProperty.call(answerMap, item.proposal_id)) {
      return answerMap[item.proposal_id];
    }
    return item.draft ?? '';
  };

  const getNoteText = (item: DecisionInboxItem): string => noteMap[item.proposal_id] ?? '';

  const isSelectionIrreversible = (item: DecisionInboxItem): boolean => {
    if (item.irreversible) return true;
    if (isMultiChoice(item)) {
      const picked = new Set(getMultiChoices(item));
      return item.options.some((opt) => picked.has(opt.key) && opt.reversible === false);
    }
    const picked = getSingleChoice(item);
    if (!picked) return false;
    const found = item.options.find((opt) => opt.key === picked);
    return found?.reversible === false;
  };

  const toggleMultiChoice = (proposalId: string, key: string, item: DecisionInboxItem) => {
    const current = getMultiChoices(item);
    const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
    setChoicesMap((prev) => ({ ...prev, [proposalId]: next }));
    setConfirmingId(null);
  };

  const selectSingleChoice = (proposalId: string, key: string) => {
    setChoiceMap((prev) => ({ ...prev, [proposalId]: key }));
    setConfirmingId(null);
  };

  const buildResolvePayload = (item: DecisionInboxItem): ResolveDecisionRequest => {
    const note = getNoteText(item).trim() || null;
    if (isMultiChoice(item)) {
      const choices = getMultiChoices(item);
      const answerText = getAnswerText(item).trim() || null;
      return {
        choices,
        choice: choices[0] ?? null,
        answer_text: answerText,
        note,
      };
    }
    if (item.action_type === 'text-answer') {
      return {
        answer_text: getAnswerText(item).trim() || null,
        note,
      };
    }
    if (item.action_type === 'choice-and-text') {
      return {
        choice: getSingleChoice(item),
        answer_text: getAnswerText(item).trim() || null,
        note,
      };
    }
    return {
      choice: getSingleChoice(item),
      note,
    };
  };

  const handleApproveClick = async (item: DecisionInboxItem) => {
    if (isSelectionIrreversible(item) && confirmingId !== item.proposal_id) {
      setConfirmingId(item.proposal_id);
      return;
    }
    const payload = buildResolvePayload(item);
    setConfirmingId(null);
    await inbox.resolve(item.proposal_id, payload);
  };

  const handleRejectClick = async (item: DecisionInboxItem) => {
    setConfirmingId(null);
    const note = getNoteText(item).trim() || null;
    await inbox.reject(item.proposal_id, { note });
  };

  const canApprove = (item: DecisionInboxItem): boolean => {
    if (inbox.mutatingId !== null) return false;
    if (isMultiChoice(item)) {
      return item.options.length === 0 || getMultiChoices(item).length > 0;
    }
    if (item.action_type === 'text-answer') {
      return getAnswerText(item).trim().length > 0;
    }
    if (item.action_type === 'choice-and-text') {
      const hasChoice = item.options.length > 0 && Boolean(getSingleChoice(item));
      const hasText = getAnswerText(item).trim().length > 0;
      return hasChoice || hasText;
    }
    return true;
  };

  const selectedConfirming = Boolean(selected && confirmingId === selected.proposal_id);
  const suggestions = useMemo(() => {
    if (!selected) return [];
    const list: string[] = [];
    if (selected.suggestion) list.push(selected.suggestion);
    if (Array.isArray(selected.suggestions)) {
      for (const s of selected.suggestions) {
        if (s && !list.includes(s)) list.push(s);
      }
    }
    return list;
  }, [selected]);

  return (
    <div className="inbox-view" data-testid="inbox-view">
      <header className="ch">
        <div style={{ minWidth: 0, flex: 1 }}>
          <h1 className="trunc" style={{ lineHeight: 1.3 }}>
            {t('workbench.inbox.pageTitle')}
          </h1>
          <div className="cmeta">
            <span>{t('workbench.inbox.pageSubtitle')}</span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <button
            type="button"
            className="sc-btn"
            data-testid="inbox-back-session"
            onClick={onBackToSessions}
          >
            {t('workbench.inbox.backToStream')}
          </button>
        </div>
      </header>

      <div
        className={`inbox-undo-bar ${inbox.feedback ? 'show' : ''}`}
        id="inbox-undo-bar"
        data-testid="inbox-undo-bar"
      >
        <span id="inbox-undo-msg">{inbox.feedback?.message ?? ''}</span>
        {inbox.feedback?.undoProposalId ? (
          <button
            type="button"
            className="sc-btn sm"
            data-testid="inbox-undo-btn"
            disabled={inbox.mutatingId !== null}
            onClick={() => void inbox.undoLast()}
          >
            {t('workbench.inbox.undo')}
          </button>
        ) : null}
      </div>

      {inbox.error ? (
        <div className="inbox-error-bar" role="alert" data-testid="inbox-error-bar">
          <span>{inbox.error}</span>
        </div>
      ) : null}

      <div className="inbox-body" data-testid="inbox-split-view">
        <div className="inbox-queue">
          <div className="inbox-qbar">
            <button
              type="button"
              className={`inbox-qtab ${inbox.activeTab === 'pending' ? 'on' : ''}`}
              data-testid="inbox-tab-pending"
              onClick={() => handleSetTab('pending')}
            >
              {t('workbench.inbox.tabPending')} <span className="n">{inbox.counts.pending}</span>
            </button>
            <button
              type="button"
              className={`inbox-qtab ${inbox.activeTab === 'schedule' ? 'on' : ''}`}
              data-testid="inbox-tab-schedule"
              onClick={() => handleSetTab('schedule')}
            >
              {t('workbench.inbox.tabSchedule')} <span className="n">{inbox.counts.schedule}</span>
            </button>
            <button
              type="button"
              className={`inbox-qtab ${inbox.activeTab === 'session' ? 'on' : ''}`}
              data-testid="inbox-tab-session"
              onClick={() => handleSetTab('session')}
            >
              {t('workbench.inbox.tabSession')} <span className="n">{inbox.counts.session}</span>
            </button>
            <button
              type="button"
              className={`inbox-qtab ${inbox.activeTab === 'snoozed' ? 'on' : ''}`}
              data-testid="inbox-tab-snoozed"
              onClick={() => handleSetTab('snoozed')}
            >
              {t('workbench.inbox.tabSnoozed')} <span className="n">{inbox.counts.snoozed}</span>
            </button>
          </div>

          <div className="inbox-qscroll">
            {filteredQueue.length ? (
              filteredQueue.map((item) => {
                const isSelected = selected?.proposal_id === item.proposal_id;
                const isMutating = inbox.mutatingId === item.proposal_id;
                const empColor =
                  item.employee_id || item.employee_name
                    ? resolveEmployeeColor(item.employee_color, item.employee_id ?? undefined)
                    : null;
                return (
                  <article
                    key={item.proposal_id}
                    className={`inbox-ditem ${isSelected ? 'sel' : ''}`}
                    data-testid={`inbox-item-${item.proposal_id}`}
                    onClick={() => handleSelectItem(item.proposal_id)}
                  >
                    <div className="inbox-dtop">
                      <span
                        className={`inbox-pill ${item.source === 'schedule' ? 'src-sch' : 'src-ses'}`}
                      >
                        {item.source_label}
                      </span>
                      {empColor ? (
                        <span className="inbox-pill emp" data-emp-color={empColor}>
                          {item.employee_name || item.employee_id}
                        </span>
                      ) : null}
                      <span
                        className={`inbox-pill ${
                          item.risk === 'high' ? 'risk-hi' : item.risk === 'medium' ? 'risk-md' : ''
                        }`}
                      >
                        {item.risk_label}
                      </span>
                      <span className="inbox-dtime">
                        {formatEpoch(item.updated_at || item.created_at)}
                      </span>
                    </div>
                    <div className="inbox-dtitle">{item.title}</div>
                    <div className="inbox-ddesc">{item.summary}</div>
                    <div className="inbox-dacts" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="sc-btn sm"
                        onClick={() => handleSelectItem(item.proposal_id)}
                      >
                        {t('workbench.inbox.viewContext')}
                      </button>
                      <div className="right">
                        {item.status === 'pending' ? (
                          <button
                            type="button"
                            className="sc-btn sm"
                            data-testid={`inbox-snooze-${item.proposal_id}`}
                            disabled={isMutating}
                            onClick={() => void inbox.snooze(item.proposal_id)}
                          >
                            {t('workbench.inbox.snooze')}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="sc-btn sm"
                            data-testid={`inbox-unsnooze-${item.proposal_id}`}
                            disabled={isMutating}
                            onClick={() => void inbox.unsnooze(item.proposal_id)}
                          >
                            {t('workbench.inbox.unsnooze')}
                          </button>
                        )}
                        <button
                          type="button"
                          className="sc-btn sm primary"
                          disabled={!canApprove(item)}
                          onClick={() => {
                            handleSelectItem(item.proposal_id);
                            void handleApproveClick(item);
                          }}
                        >
                          {isChoiceLike(item)
                            ? t('workbench.inbox.quickDecide')
                            : t('workbench.inbox.approveExec')}
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })
            ) : (
              <div className="inbox-empty" data-testid="inbox-queue-empty">
                {t('workbench.inbox.queueEmpty')}
              </div>
            )}
          </div>
        </div>

        <aside
          className="inbox-ctx-pane"
          aria-label={t('workbench.inbox.ctxPaneAria')}
          data-testid="inbox-ctx-pane"
        >
          {selected ? (
            <>
              <div className="inbox-ctx-hd">
                <h2>{t('workbench.inbox.ctxTitle')}</h2>
                {selected.session_id ? (
                  <button
                    type="button"
                    className="sc-btn sm"
                    data-testid="inbox-open-session"
                    onClick={() => onOpenSession(selected.session_id!)}
                  >
                    {t('workbench.inbox.openSourceSession')}
                  </button>
                ) : null}
              </div>

              <div className="inbox-ctx-scroll">
                <div className="inbox-ctx-sec">
                  <div className="inbox-ctx-lbl">{t('workbench.inbox.secTriggerRisk')}</div>
                  <div className="inbox-ctx-title">{selected.title}</div>
                  <dl className="inbox-kv">
                    <dt>{t('workbench.inbox.kvSource')}</dt>
                    <dd>
                      {selected.source_label}
                      {selected.schedule_name ? ` · ${selected.schedule_name}` : ''}
                    </dd>
                    <dt>{t('workbench.inbox.kvEmployee')}</dt>
                    <dd>
                      {selected.employee_id || selected.employee_name ? (
                        <span
                          className="inbox-pill emp"
                          data-emp-color={resolveEmployeeColor(
                            selected.employee_color,
                            selected.employee_id ?? undefined,
                          )}
                        >
                          {selected.employee_name || selected.employee_id}
                        </span>
                      ) : (
                        t('workbench.inbox.unassigned')
                      )}
                    </dd>
                    <dt>{t('workbench.inbox.kvSession')}</dt>
                    <dd className="mono">
                      {selected.session_id || t('workbench.inbox.noneValue')}
                    </dd>
                    <dt>{t('workbench.inbox.kvSkipReason')}</dt>
                    <dd>
                      {selected.skip_reason || selected.why || t('workbench.inbox.noneValue')}
                    </dd>
                    <dt>{t('workbench.inbox.kvImpactScope')}</dt>
                    <dd>{selected.impact_scope || t('workbench.inbox.noneValue')}</dd>
                    {selected.expires_at ? (
                      <>
                        <dt>{t('workbench.inbox.kvExpiresAt')}</dt>
                        <dd className="mono">{formatEpoch(selected.expires_at)}</dd>
                      </>
                    ) : null}
                  </dl>
                </div>

                <div className="inbox-ctx-sec">
                  <div className="inbox-ctx-lbl">{t('workbench.inbox.secEvidence')}</div>
                  <pre className="inbox-code">
                    {selected.evidence || selected.summary || t('workbench.inbox.noEvidence')}
                  </pre>
                </div>

                <div className="inbox-ctx-sec">
                  <div className="inbox-ctx-lbl">{t('workbench.inbox.secQuickAction')}</div>

                  {isChoiceLike(selected) ? (
                    <div className="inbox-opt-list">
                      {selected.options.map((opt) => {
                        const multi = isMultiChoice(selected);
                        const isOn = multi
                          ? getMultiChoices(selected).includes(opt.key)
                          : getSingleChoice(selected) === opt.key;
                        return (
                          <button
                            key={opt.key}
                            type="button"
                            className={`inbox-opt-btn ${isOn ? 'on' : ''}`}
                            data-testid={`inbox-opt-${opt.key}`}
                            onClick={() =>
                              multi
                                ? toggleMultiChoice(selected.proposal_id, opt.key, selected)
                                : selectSingleChoice(selected.proposal_id, opt.key)
                            }
                          >
                            <span className="inbox-opt-key">{opt.key}</span>
                            <div style={{ minWidth: 0, flex: 1 }}>
                              <div className="inbox-opt-lbl">{opt.label}</div>
                              {opt.effect ? (
                                <div className="inbox-opt-eff">{opt.effect}</div>
                              ) : null}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ) : null}

                  {selected.action_type === 'text-answer' ||
                  selected.action_type === 'choice-and-text' ? (
                    <div className="inbox-text-wrap">
                      <textarea
                        className="inbox-answer-inp"
                        data-testid="inbox-answer-input"
                        rows={3}
                        placeholder={t('workbench.inbox.answerPlaceholder')}
                        value={getAnswerText(selected)}
                        onChange={(e) => {
                          const val = e.target.value;
                          setAnswerMap((prev) => ({ ...prev, [selected.proposal_id]: val }));
                        }}
                      />
                      {selected.draft ? (
                        <div className="inbox-draft-row">
                          <span className="inbox-draft-lbl">{t('workbench.inbox.draftLabel')}</span>
                          <button
                            type="button"
                            className="sc-btn sm"
                            data-testid="inbox-use-draft"
                            onClick={() =>
                              setAnswerMap((prev) => ({
                                ...prev,
                                [selected.proposal_id]: selected.draft ?? '',
                              }))
                            }
                          >
                            {t('workbench.inbox.useDraft')}
                          </button>
                        </div>
                      ) : null}
                      {suggestions.length > 0 ? (
                        <div className="inbox-suggest-row">
                          {suggestions.map((sug) => (
                            <button
                              key={sug}
                              type="button"
                              className="sc-btn sm"
                              onClick={() =>
                                setAnswerMap((prev) => ({ ...prev, [selected.proposal_id]: sug }))
                              }
                            >
                              {t('workbench.inbox.suggestionPrefix')}
                              {sug}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  <input
                    className="inbox-note-inp"
                    data-testid="inbox-note-input"
                    placeholder={t('workbench.inbox.notePlaceholder')}
                    value={getNoteText(selected)}
                    onChange={(e) => {
                      const val = e.target.value;
                      setNoteMap((prev) => ({ ...prev, [selected.proposal_id]: val }));
                    }}
                  />

                  {selectedConfirming ? (
                    <div className="inbox-confirm-bar" data-testid="inbox-confirm-bar">
                      <span>{t('workbench.inbox.irreversibleConfirm')}</span>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button
                          type="button"
                          className="sc-btn sm warn"
                          data-testid="inbox-confirm-exec"
                          disabled={inbox.mutatingId !== null}
                          onClick={() => void handleApproveClick(selected)}
                        >
                          {t('workbench.inbox.confirmExec')}
                        </button>
                        <button
                          type="button"
                          className="sc-btn sm"
                          data-testid="inbox-confirm-cancel"
                          onClick={() => setConfirmingId(null)}
                        >
                          {t('workbench.inbox.cancel')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="inbox-ctx-actions">
                      <button
                        type="button"
                        className="sc-btn primary"
                        id="inbox-approve-btn"
                        data-testid="inbox-approve-btn"
                        disabled={!canApprove(selected)}
                        onClick={() => void handleApproveClick(selected)}
                      >
                        {isChoiceLike(selected)
                          ? t('workbench.inbox.submitChoice')
                          : t('workbench.inbox.approveAndRelease')}
                      </button>
                      <button
                        type="button"
                        className="sc-btn danger"
                        data-testid="inbox-reject-btn"
                        disabled={inbox.mutatingId !== null}
                        onClick={() => void handleRejectClick(selected)}
                      >
                        {t('workbench.inbox.reject')}
                      </button>
                      {selected.status === 'pending' ? (
                        <button
                          type="button"
                          className="sc-btn"
                          style={{ marginLeft: 'auto' }}
                          data-testid="inbox-ctx-snooze"
                          disabled={inbox.mutatingId !== null}
                          onClick={() => void inbox.snooze(selected.proposal_id)}
                        >
                          {t('workbench.inbox.snooze')}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="sc-btn"
                          style={{ marginLeft: 'auto' }}
                          data-testid="inbox-ctx-unsnooze"
                          disabled={inbox.mutatingId !== null}
                          onClick={() => void inbox.unsnooze(selected.proposal_id)}
                        >
                          {t('workbench.inbox.unsnooze')}
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="inbox-ctx-empty" data-testid="inbox-ctx-empty">
              {t('workbench.inbox.ctxEmpty')}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
