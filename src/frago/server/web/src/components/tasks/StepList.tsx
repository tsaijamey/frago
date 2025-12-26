import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import type { TaskStep, StepType } from '@/types/pywebview';
import { User, Bot, Wrench, ArrowRight, Settings, type LucideIcon } from 'lucide-react';
import { StepContent, PairedToolStep } from './content';

interface StepListProps {
  steps: TaskStep[];
}

// Step type configuration (corresponds to backend StepType enum)
const stepTypeConfig: Record<StepType, { Icon: LucideIcon; label: string; colorClass: string }> = {
  user_message: { Icon: User, label: 'User', colorClass: 'text-[var(--accent-primary)]' },
  assistant_message: { Icon: Bot, label: 'Assistant', colorClass: 'text-[var(--accent-success)]' },
  tool_call: { Icon: Wrench, label: 'Tool', colorClass: 'text-[var(--accent-warning)]' },
  tool_result: { Icon: ArrowRight, label: 'Result', colorClass: 'text-[var(--accent-warning)]' },
  system_event: { Icon: Settings, label: 'System', colorClass: 'text-[var(--accent-info)]' },
};

function getStepConfig(type: StepType) {
  return stepTypeConfig[type] || stepTypeConfig.system_event;
}

// Format timestamp to +8 timezone
function formatTimestamp(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString('en-US', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// Filterable types (corresponds to backend StepType enum)
const filterableTypes: StepType[] = ['user_message', 'assistant_message', 'tool_call', 'tool_result', 'system_event'];

// Render batch size
const RENDER_BATCH_SIZE = 50;

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

export default function StepList({ steps }: StepListProps) {
  // Empty set means show all, non-empty means only show selected types
  const [activeFilters, setActiveFilters] = useState<Set<StepType>>(new Set());
  const [renderCount, setRenderCount] = useState(RENDER_BATCH_SIZE);
  const scrollRef = useRef<HTMLDivElement>(null);

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
    // Reset render count
    setRenderCount(RENDER_BATCH_SIZE);
  };

  // Empty set shows all, otherwise only show selected types
  const filteredSteps = activeFilters.size === 0
    ? steps
    : steps.filter(step => activeFilters.has(step.type));

  // Pair tool calls with their results
  const displaySteps = useMemo(() => pairToolSteps(filteredSteps), [filteredSteps]);

  // Only render first N items
  const renderedSteps = displaySteps.slice(0, renderCount);
  const hasMore = renderCount < displaySteps.length;

  // Load more when scrolling to bottom
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const { scrollTop, scrollHeight, clientHeight } = el;
    // Load more when 100px from bottom
    if (scrollHeight - scrollTop - clientHeight < 100) {
      setRenderCount(prev => {
        if (prev >= displaySteps.length) return prev;
        return Math.min(prev + RENDER_BATCH_SIZE, displaySteps.length);
      });
    }
  }, [displaySteps.length]);

  // Listen to scroll
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => handleScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [handleScroll]);

  // Check if content is insufficient to scroll, if so load all directly
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    // If content height is less than container height, means cannot scroll, load all directly
    if (el.scrollHeight <= el.clientHeight && renderCount < displaySteps.length) {
      setRenderCount(displaySteps.length);
    }
  }, [renderCount, displaySteps.length]);

  // Reset render count when filter conditions change
  useEffect(() => {
    setRenderCount(RENDER_BATCH_SIZE);
  }, [activeFilters]);

  if (steps.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-center py-scaled-4">
        No steps
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filter bar - wrapping layout */}
      <div className="flex flex-wrap items-center gap-1 pb-scaled-2 border-b border-[var(--border-primary)] mb-scaled-2 shrink-0">
        <span className="text-scaled-xs text-[var(--text-muted)]">Filter:</span>
        {filterableTypes.map(type => {
          const { Icon, label, colorClass } = getStepConfig(type);
          const isActive = activeFilters.has(type);
          const showAsActive = activeFilters.size === 0 || isActive;
          return (
            <button
              key={type}
              onClick={() => toggleFilter(type)}
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-scaled-xs transition-opacity ${
                showAsActive ? 'opacity-100' : 'opacity-40'
              } hover:opacity-100`}
              title={label}
            >
              <Icon className="icon-scaled-sm" />
              <span className={showAsActive ? colorClass : 'text-[var(--text-muted)]'}>{label}</span>
            </button>
          );
        })}
        <span className="text-scaled-xs text-[var(--text-muted)] ml-auto">
          {filteredSteps.length}
        </span>
      </div>

      {/* Step list - internal scrolling */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
        <div className="flex flex-col gap-scaled-2">
          {renderedSteps.map((displayStep) => {
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

            // Render single step
            const step = displayStep.step;
            const { Icon, label, colorClass } = getStepConfig(step.type);
            return (
              <div key={displayStep.key} className="step-item-new">
                {/* First line: Icon + Type name + Timestamp */}
                <div className="flex items-center justify-between mb-scaled-1">
                  <div className="flex items-center gap-scaled-2">
                    <Icon className="icon-scaled-sm" />
                    <span className={`text-scaled-xs font-medium ${colorClass}`}>{label}</span>
                    {step.tool_name && (
                      <code className="text-scaled-xs px-scaled-2 py-0.5 bg-[var(--bg-secondary)] rounded font-mono">
                        {step.tool_name}
                      </code>
                    )}
                  </div>
                  <span className="text-scaled-xs text-[var(--text-muted)]">
                    {formatTimestamp(step.timestamp)}
                  </span>
                </div>
                {/* Second line: Message content */}
                <div className="text-scaled-sm text-[var(--text-secondary)] break-words pl-scaled-5">
                  <StepContent step={step} />
                </div>
              </div>
            );
          })}
        </div>
        {hasMore && (
          <div className="text-center py-scaled-2 text-scaled-xs text-[var(--text-muted)]">
            Scroll to load more...
          </div>
        )}
      </div>
    </div>
  );
}
