import { useState, useRef, useCallback, useEffect } from 'react';
import type { TaskStep, StepType } from '@/types/pywebview.d';
import { User, Bot, Wrench, ArrowRight, Settings, type LucideIcon } from 'lucide-react';

interface StepListProps {
  steps: TaskStep[];
}

// 步骤类型配置（与后端 StepType 枚举对应）
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

// 格式化时间戳为 +8 时区
function formatTimestamp(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// 可筛选的类型（与后端 StepType 枚举对应）
const filterableTypes: StepType[] = ['user_message', 'assistant_message', 'tool_call', 'tool_result', 'system_event'];

// 每次渲染的数量
const RENDER_BATCH_SIZE = 50;

export default function StepList({ steps }: StepListProps) {
  // 空集合表示显示全部，非空则只显示选中的类型
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
    // 重置渲染数量
    setRenderCount(RENDER_BATCH_SIZE);
  };

  // 空集合显示全部，否则只显示选中的类型
  const filteredSteps = activeFilters.size === 0
    ? steps
    : steps.filter(step => activeFilters.has(step.type));

  // 只渲染前 N 条
  const renderedSteps = filteredSteps.slice(0, renderCount);
  const hasMore = renderCount < filteredSteps.length;

  // 滚动到底部时加载更多
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;

    const { scrollTop, scrollHeight, clientHeight } = el;
    // 距离底部 100px 时加载更多
    if (scrollHeight - scrollTop - clientHeight < 100) {
      setRenderCount(prev => {
        if (prev >= filteredSteps.length) return prev;
        return Math.min(prev + RENDER_BATCH_SIZE, filteredSteps.length);
      });
    }
  }, [filteredSteps.length]);

  // 监听滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => handleScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, [handleScroll]);

  // 检查内容是否不足以滚动，如果是则直接加载全部
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    // 如果内容高度小于容器高度，说明无法滚动，直接加载全部
    if (el.scrollHeight <= el.clientHeight && renderCount < filteredSteps.length) {
      setRenderCount(filteredSteps.length);
    }
  }, [renderCount, filteredSteps.length]);

  // 当筛选条件变化时重置渲染数量
  useEffect(() => {
    setRenderCount(RENDER_BATCH_SIZE);
  }, [activeFilters]);

  if (steps.length === 0) {
    return (
      <div className="text-[var(--text-muted)] text-center py-4">
        暂无步骤
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* 筛选栏 */}
      <div className="flex items-center gap-2 pb-3 border-b border-[var(--border-primary)] mb-3 shrink-0">
        <span className="text-xs text-[var(--text-muted)]">筛选:</span>
        {filterableTypes.map(type => {
          const { Icon, label, colorClass } = getStepConfig(type);
          const isActive = activeFilters.has(type);
          const showAsActive = activeFilters.size === 0 || isActive;
          return (
            <button
              key={type}
              onClick={() => toggleFilter(type)}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs transition-opacity ${
                showAsActive ? 'opacity-100' : 'opacity-40'
              } hover:opacity-100`}
              title={label}
            >
              <Icon size={14} className={colorClass} />
              <span className={showAsActive ? colorClass : 'text-[var(--text-muted)]'}>{label}</span>
            </button>
          );
        })}
        <span className="text-xs text-[var(--text-muted)] ml-auto">
          {filteredSteps.length}/{steps.length}
        </span>
      </div>

      {/* 步骤列表 - 内部滚动 */}
      <div ref={scrollRef} className="step-list-scroll flex-1 overflow-y-auto min-h-0">
        <div className="flex flex-col gap-2">
          {renderedSteps.map((step) => {
            const { Icon, label, colorClass } = getStepConfig(step.type);
            return (
              <div key={step.step_id} className="step-item-new">
                {/* 第一行：图标 + 类型名称 + 时间戳 */}
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <Icon size={14} className={colorClass} />
                    <span className={`text-xs font-medium ${colorClass}`}>{label}</span>
                    {step.tool_name && (
                      <code className="text-xs px-1.5 py-0.5 bg-[var(--bg-secondary)] rounded font-mono">
                        {step.tool_name}
                      </code>
                    )}
                  </div>
                  <span className="text-xs text-[var(--text-muted)]">
                    {formatTimestamp(step.timestamp)}
                  </span>
                </div>
                {/* 第二行：消息内容 */}
                <div className="text-sm text-[var(--text-secondary)] break-words pl-5">
                  {step.content}
                </div>
              </div>
            );
          })}
        </div>
        {hasMore && (
          <div className="text-center py-2 text-xs text-[var(--text-muted)]">
            滚动加载更多...
          </div>
        )}
      </div>
    </div>
  );
}
