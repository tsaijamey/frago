import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  getDecisionInbox,
  rejectDecisionItem,
  resolveDecisionItem,
  snoozeDecisionItem,
  undoDecisionItem,
  unsnoozeDecisionItem,
  type DecisionInboxCounts,
  type DecisionInboxItem,
  type DecisionInboxMutationResponse,
  type RejectDecisionRequest,
  type ResolveDecisionRequest,
} from '@/api';
import { getWebSocketClient, MessageType } from '@/api/websocket';

export type DecisionInboxTab = 'pending' | 'schedule' | 'session' | 'snoozed';

export interface DecisionInboxFeedback {
  message: string;
  /** 仅当操作属于可逆状态切换（snooze / unsnooze）时非空，绝不为 resolved/rejected 提供伪撤销。 */
  undoProposalId: string | null;
}

export interface UseDecisionInboxOptions {
  onMutated?: (
    item: DecisionInboxItem,
    action: 'resolve' | 'reject' | 'snooze' | 'unsnooze' | 'undo',
  ) => void;
}

const EMPTY_COUNTS: DecisionInboxCounts = {
  pending: 0,
  schedule: 0,
  session: 0,
  snoozed: 0,
};

function mergeMutatedItem(
  prev: DecisionInboxItem[],
  nextItem: DecisionInboxItem,
): DecisionInboxItem[] {
  const active = nextItem.status === 'pending' || nextItem.status === 'snoozed';
  const idx = prev.findIndex((x) => x.proposal_id === nextItem.proposal_id);
  if (!active) {
    return idx >= 0 ? prev.filter((x) => x.proposal_id !== nextItem.proposal_id) : prev;
  }
  if (idx >= 0) {
    const copy = [...prev];
    copy[idx] = nextItem;
    return copy;
  }
  return [nextItem, ...prev];
}

export function useDecisionInbox(options: UseDecisionInboxOptions = {}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<DecisionInboxItem[]>([]);
  const [counts, setCounts] = useState<DecisionInboxCounts>(EMPTY_COUNTS);
  const [loading, setLoading] = useState(true);
  const [mutatingId, setMutatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DecisionInboxTab>('pending');
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [railExpanded, setRailExpanded] = useState(false);
  const [feedback, setFeedback] = useState<DecisionInboxFeedback | null>(null);

  const onMutatedRef = useRef(options.onMutated);
  onMutatedRef.current = options.onMutated;
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await getDecisionInbox({ status: 'all', source: 'all' });
      if (!mountedRef.current) return;
      setItems(Array.isArray(data?.items) ? data.items : []);
      setCounts(data?.counts ?? EMPTY_COUNTS);
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const client = getWebSocketClient();
    const onInboxUpdate = () => {
      void refresh();
    };
    const unsubInbox = client.on(MessageType.DECISION_INBOX_UPDATE, onInboxUpdate);
    const unsubTurnDone = client.on(MessageType.SESSION_TURN_DONE, onInboxUpdate);
    return () => {
      unsubInbox();
      unsubTurnDone();
    };
  }, [refresh]);

  const applyMutation = useCallback(
    async (
      proposalId: string,
      action: 'resolve' | 'reject' | 'snooze' | 'unsnooze' | 'undo',
      fn: () => Promise<DecisionInboxMutationResponse>,
      buildFeedback: (item: DecisionInboxItem) => DecisionInboxFeedback | null,
    ): Promise<DecisionInboxMutationResponse | null> => {
      setMutatingId(proposalId);
      setError(null);
      try {
        const res = await fn();
        if (!mountedRef.current) return res;
        setItems((prev) => mergeMutatedItem(prev, res.item));
        if (res.counts) {
          setCounts(res.counts);
        }
        setFeedback(buildFeedback(res.item));
        onMutatedRef.current?.(res.item, action);
        return res;
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : String(err));
        }
        return null;
      } finally {
        if (mountedRef.current) {
          setMutatingId((cur) => (cur === proposalId ? null : cur));
        }
      }
    },
    [],
  );

  const resolve = useCallback(
    (proposalId: string, body: ResolveDecisionRequest = {}) =>
      applyMutation(
        proposalId,
        'resolve',
        () => resolveDecisionItem(proposalId, body),
        (item) => ({
          message: t('workbench.inbox.feedbackResolved', { title: item.title }),
          undoProposalId: null,
        }),
      ),
    [applyMutation, t],
  );

  const reject = useCallback(
    (proposalId: string, body: RejectDecisionRequest = {}) =>
      applyMutation(
        proposalId,
        'reject',
        () => rejectDecisionItem(proposalId, body),
        (item) => ({
          message: t('workbench.inbox.feedbackRejected', { title: item.title }),
          undoProposalId: null,
        }),
      ),
    [applyMutation, t],
  );

  const snooze = useCallback(
    (proposalId: string) =>
      applyMutation(
        proposalId,
        'snooze',
        () => snoozeDecisionItem(proposalId),
        (item) => ({
          message: t('workbench.inbox.feedbackSnoozed', { title: item.title }),
          undoProposalId: item.proposal_id,
        }),
      ),
    [applyMutation, t],
  );

  const unsnooze = useCallback(
    (proposalId: string) =>
      applyMutation(
        proposalId,
        'unsnooze',
        () => unsnoozeDecisionItem(proposalId),
        (item) => ({
          message: t('workbench.inbox.feedbackUnsnoozed', { title: item.title }),
          undoProposalId: item.proposal_id,
        }),
      ),
    [applyMutation, t],
  );

  const undoLast = useCallback(async () => {
    const targetId = feedback?.undoProposalId;
    if (!targetId) return null;
    const res = await applyMutation(
      targetId,
      'undo',
      () => undoDecisionItem(targetId),
      (item) => ({
        message: t('workbench.inbox.feedbackUndone', { title: item.title }),
        undoProposalId: null,
      }),
    );
    if (res && mountedRef.current) {
      setSelectedProposalId(res.item.proposal_id);
      setFeedback(null);
    }
    return res;
  }, [applyMutation, feedback, t]);

  const toggleRailExpanded = useCallback(() => {
    setRailExpanded((v) => !v);
  }, []);

  const clearFeedback = useCallback(() => {
    setFeedback(null);
  }, []);

  return {
    items,
    counts,
    loading,
    mutatingId,
    error,
    activeTab,
    setActiveTab,
    selectedProposalId,
    setSelectedProposalId,
    railExpanded,
    setRailExpanded,
    toggleRailExpanded,
    feedback,
    clearFeedback,
    refresh,
    resolve,
    reject,
    snooze,
    unsnooze,
    undoLast,
  };
}

export type DecisionInboxHookState = ReturnType<typeof useDecisionInbox>;
