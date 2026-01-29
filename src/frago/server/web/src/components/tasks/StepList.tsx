import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import type { TaskStep, StepType } from '@/types/pywebview';
import { User, Bot, Wrench, ArrowRight, Settings, Loader2, type LucideIcon } from 'lucide-react';
import { PairedToolStep } from './content';
import { getTaskSteps } from '@/api';
import { MessageCard } from '@/components/shared';
import { taskStepToUnifiedMessage } from '@/types/message';

interface StepListProps {
  sessionId: string;
  initialSteps: TaskStep[];
  totalSteps: number;
  hasMore: boolean;
  isRunning: boolean;
}

// Step type configuration (matches ConsoleMessage types for consistency)
const stepTypeConfig: Record<StepType, { Icon: LucideIcon; labelKey: string; colorClass: string }> = {
  user: { Icon: User, labelKey: 'tasks.user', colorClass: 'text-[var(--accent-primary)]' },
  assistant: { Icon: Bot, labelKey: 'tasks.assistant', colorClass: 'text-[var(--accent-success)]' },
  tool_call: { Icon: Wrench, labelKey: 'tasks.tool', colorClass: 'text-[var(--accent-warning)]' },
  tool_result: { Icon: ArrowRight, labelKey: 'tasks.result', colorClass: 'text-[var(--accent-warning)]' },
  system: { Icon: Settings, labelKey: 'tasks.system', colorClass: 'text-[var(--accent-info)]' },
};

function getStepConfig(type: StepType) {
  return stepTypeConfig[type] || stepTypeConfig.system;
}

// Filterable types (matches ConsoleMessage types for consistency)
// Note: 'system' type removed as backend no longer sends system messages
const filterableTypes: StepType[] = ['user', 'assistant', 'tool_call', 'tool_result'];

// Pagination settings
const PAGE_SIZE = 100;

// Types for paired/unpaired steps
type PairedStep = { type: 'paired'; call: TaskStep; result: TaskStep; key: string };
type SingleStep = { type: 'single'; step: TaskStep; key: string };
type DisplayStep = PairedStep | SingleStep;

/**
 * Pairs tool_call steps with their corresponding tool_result steps.
 * Returns an array of display items that can be either paired or single steps.
 */
function pairToolSteps(steps: TaskStep[]): DisplayStep[] {
  const result: DisplayStep[] = [];
  const pendingCalls = new Map<string, TaskStep>();
  const pairedCallIds = new Set<string>();

  // First pass: collect all tool_results and find their matching calls
  for (const step of steps) {
    if (step.type === 'tool_result' && step.tool_call_id) {
      // Find the matching call in previous steps
      for (const prevStep of steps) {
        if (
          prevStep.type === 'tool_call' &&
          prevStep.tool_call_id === step.tool_call_id
        ) {
          pendingCalls.set(step.tool_call_id, prevStep);
          pairedCallIds.add(step.tool_call_id);
          break;
        }
      }
    }
  }

  // Second pass: build display list
  for (const step of steps) {
    if (step.type === 'tool_call' && step.tool_call_id && pairedCallIds.has(step.tool_call_id)) {
      // Skip - will be rendered as part of paired step when result arrives
      continue;
    }

    if (step.type === 'tool_result' && step.tool_call_id) {
      const call = pendingCalls.get(step.tool_call_id);
      if (call) {
        // Paired step
        result.push({
          type: 'paired',
          call,
          result: step,
          key: `paired-${step.tool_call_id}`,
        });
        continue;
      }
    }

    // Single step (unpaired or non-tool)
    result.push({
      type: 'single',
      step,
      key: `single-${step.step_id}`,
    });
  }

  return result;
}

export default function StepList({ sessionId, initialSteps, totalSteps: _totalSteps, hasMore: initialHasMore, isRunning }: StepListProps) {
  const { t } = useTranslation();
  // Empty set means show all, non-empty means only show selected types
  const [activeFilters, setActiveFilters] = useState<Set<StepType>>(new Set());
  const scrollRef = useRef<HTMLDivElement>(null);

  // Pagination state - load older messages on scroll up
  const [steps, setSteps] = useState<TaskStep[]>(initialSteps);
  const [hasMoreOlder, setHasMoreOlder] = useState(initialHasMore);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [loadedOffset, setLoadedOffset] = useState(initialSteps.length);

  // Track if user is at bottom for auto-scroll
  const [isAtBottom, setIsAtBottom] = useState(true);

  // Update steps when initialSteps changes (e.g., from polling)
  useEffect(() => {
    // Check if new steps arrived (compare by length or last step timestamp)
    if (initialSteps.length > steps.length) {
      // Append new steps only (don't replace existing)
      const newSteps = initialSteps.slice(steps.length);
      if (newSteps.length > 0) {
        setSteps(prev => [...prev, ...newSteps]);
      }
    } else if (initialSteps.length === steps.length && initialSteps.length > 0) {
      // Same length, check if last step is different (content updated)
      const lastInitial = initialSteps[initialSteps.length - 1];
      const lastCurrent = steps[steps.length - 1];
      if (lastInitial.content !== lastCurrent.content) {
        // Update the last step
        setSteps(prev => [...prev.slice(0, -1), lastInitial]);
      }
    }
  }, [initialSteps, steps.length]);

  const toggleFilter = (type: StepType) => {
    setActiveFilters(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  // Empty set shows all, otherwise only show selected types
  const filteredSteps = activeFilters.size === 0
    ? steps
    : steps.filter(step => activeFilters.has(step.type));

  // Pair tool calls with their results
  const displaySteps = useMemo(() => pairToolSteps(filteredSteps), [filteredSteps]);

  // Load older steps when scrolling near top
  const loadOlderSteps = useCallback(async () => {
    if (isLoadingOlder || !hasMoreOlder) return;

    setIsLoadingOlder(true);
    try {
      const result = await getTaskSteps(sessionId, loadedOffset, PAGE_SIZE);
      if (result.steps.length > 0) {
        // Save scroll position before prepending
        const el = scrollRef.current;
        const prevScrollHeight = el?.scrollHeight ?? 0;
        const prevScrollTop = el?.scrollTop ?? 0;

        // Prepend older steps
        setSteps(prev => [...result.steps, ...prev]);
        setLoadedOffset(prev => prev + result.steps.length);
        setHasMoreOlder(result.has_more);

        // Restore scroll position after React updates the DOM
        requestAnimationFrame(() => {
          if (el) {
            const newScrollHeight = el.scrollHeight;
            el.scrollTop = newScrollHeight - prevScrollHeight + prevScrollTop;
          }
        });
      } else {
        setHasMoreOlder(false);
      }
    } catch (error) {
      console.error('Failed to load older steps:', error);
    } finally {
      setIsLoadingOlder(false);
    }
  }, [sessionId, loadedOffset, isLoadingOlder, hasMoreOlder]);

  // Handle scroll events
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    // Check if at bottom (within 50px threshold)
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    setIsAtBottom(atBottom);

    // Load older when near top (within 100px)
    if (el.scrollTop < 100 && hasMoreOlder && !isLoadingOlder) {
      loadOlderSteps();
    }
  }, [hasMoreOlder, isLoadingOlder, loadOlderSteps]);

  // Listen to scroll
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  // Scroll to bottom on initial mount
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, []); // Only on mount

  // Auto-scroll when running and user is at bottom
  useEffect(() => {
    if (isRunning && isAtBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps, isRunning, isAtBottom]);

  if (steps.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-center py-scaled-4">
        {t('tasks.noSteps')}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filter bar - pill style buttons */}
      <div className="flex flex-wrap items-center gap-2 py-3 shrink-0">
        <span className="text-[13px] font-medium text-[var(--text-muted)]">{t('tasks.filter')}:</span>
        {filterableTypes.map(type => {
          const { Icon, labelKey } = getStepConfig(type);
          const label = t(labelKey);
          const isActive = activeFilters.has(type);
          const showAsActive = activeFilters.size === 0 || isActive;
          return (
            <button
              key={type}
              type="button"
              onClick={() => toggleFilter(type)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium transition-all ${
                showAsActive
                  ? 'bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'
                  : 'bg-transparent text-[var(--text-muted)] opacity-50 hover:opacity-100 hover:bg-[var(--bg-tertiary)]'
              }`}
              title={label}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{label}</span>
            </button>
          );
        })}
        <div className="flex-1" />
      </div>

      {/* Step list - internal scrolling */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
        {/* Loading older indicator */}
        {hasMoreOlder && (
          <div className="text-center py-scaled-2 text-scaled-xs text-[var(--text-muted)]">
            {isLoadingOlder ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="icon-scaled-sm animate-spin" />
                {t('tasks.loadingOlder')}
              </span>
            ) : (
              <span>{t('tasks.scrollUpToLoadMore')}</span>
            )}
          </div>
        )}

        <div className="flex flex-col gap-4 pb-4 pr-2">
          {displaySteps.map((displayStep) => {
            if (displayStep.type === 'paired') {
              // Render paired tool call and result
              return (
                <PairedToolStep
                  key={displayStep.key}
                  call={displayStep.call}
                  result={displayStep.result}
                />
              );
            }

            // Render single step using unified MessageCard
            const step = displayStep.step;
            const unifiedMessage = taskStepToUnifiedMessage(step);
            return (
              <MessageCard
                key={displayStep.key}
                message={unifiedMessage}
                showTypingIndicator={false}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
