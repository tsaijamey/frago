import { useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getTaskSteps } from '@/api/pywebview';
import StepList from './StepList';
import LoadingSpinner from '@/components/ui/LoadingSpinner';

// 格式化时间
function formatDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// 格式化持续时间
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export default function TaskDetail() {
  const { taskDetail, isLoading, switchPage, setTaskDetail } = useAppStore();
  const [loadingMore, setLoadingMore] = useState(false);

  const handleLoadMore = async () => {
    if (!taskDetail || loadingMore) return;

    setLoadingMore(true);
    try {
      const currentCount = taskDetail.steps.length;
      const result = await getTaskSteps(taskDetail.session_id, currentCount, 50);

      if (result.steps && result.steps.length > 0) {
        setTaskDetail({
          ...taskDetail,
          steps: [...taskDetail.steps, ...result.steps],
          has_more_steps: result.has_more,
        });
      }
    } catch (error) {
      console.error('Failed to load more steps:', error);
    } finally {
      setLoadingMore(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!taskDetail) {
    return (
      <div className="text-[var(--text-muted)] text-center py-8">
        任务不存在或已被删除
      </div>
    );
  }

  if (taskDetail.error) {
    return (
      <div className="text-[var(--accent-error)] text-center py-8">
        加载失败: {taskDetail.error}
      </div>
    );
  }

  return (
    <div className="page-scroll flex flex-col gap-4 h-full">
      {/* 返回按钮 */}
      <button
        className="btn btn-ghost self-start"
        onClick={() => switchPage('tasks')}
      >
        ← 返回任务列表
      </button>

      {/* 任务信息 */}
      <div className="card">
        <h2 className="text-lg font-medium mb-4 text-[var(--text-primary)]">
          {taskDetail.name}
        </h2>

        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">状态</span>
            <span className={`status-${taskDetail.status}`}>{taskDetail.status}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">开始时间</span>
            <span>{formatDateTime(taskDetail.started_at)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">持续时间</span>
            <span>{formatDuration(taskDetail.duration_ms)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">步骤数</span>
            <span>{taskDetail.step_count}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)]">工具调用</span>
            <span>{taskDetail.tool_call_count}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--text-muted)] shrink-0">项目路径</span>
            <span className="font-mono text-xs text-right break-all ml-4">{taskDetail.project_path}</span>
          </div>
        </div>
      </div>

      {/* 摘要统计 - 仅当有有效数据时显示 */}
      {taskDetail.summary && (
        taskDetail.summary.tool_success_count + taskDetail.summary.tool_error_count > 0 ||
        taskDetail.summary.most_used_tools.length > 0
      ) ? (
        <div className="card">
          <h3 className="font-medium mb-3 text-[var(--accent-primary)]">
            统计摘要
          </h3>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div className="text-center">
              <div className="text-2xl font-bold text-[var(--accent-success)]">
                {taskDetail.summary.tool_success_count}
              </div>
              <div className="text-[var(--text-muted)]">成功调用</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-[var(--accent-error)]">
                {taskDetail.summary.tool_error_count}
              </div>
              <div className="text-[var(--text-muted)]">失败调用</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-[var(--accent-primary)]">
                {taskDetail.summary.most_used_tools.length}
              </div>
              <div className="text-[var(--text-muted)]">使用工具</div>
            </div>
          </div>

          {taskDetail.summary.most_used_tools.length > 0 && (
            <div className="mt-4">
              <div className="text-sm text-[var(--text-muted)] mb-2">
                最常用工具:
              </div>
              <div className="flex flex-wrap gap-2">
                {taskDetail.summary.most_used_tools.slice(0, 5).map((tool) => (
                  <span
                    key={tool.name}
                    className="bg-[var(--bg-subtle)] px-2 py-1 rounded text-xs font-mono"
                  >
                    {tool.name} ({tool.count})
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}

      {/* 步骤列表 */}
      <div className="card">
        <h3 className="font-medium mb-3 text-[var(--accent-primary)]">
          执行步骤 ({taskDetail.steps.length}/{taskDetail.steps_total})
        </h3>
        <StepList steps={taskDetail.steps} />

        {taskDetail.has_more_steps && (
          <div className="text-center mt-4">
            <button
              className="btn btn-secondary"
              onClick={handleLoadMore}
              disabled={loadingMore}
            >
              {loadingMore ? (
                <>
                  <LoadingSpinner size="sm" />
                  <span className="ml-2">加载中...</span>
                </>
              ) : (
                `加载更多 (还有 ${taskDetail.steps_total - taskDetail.steps.length} 个步骤)`
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
