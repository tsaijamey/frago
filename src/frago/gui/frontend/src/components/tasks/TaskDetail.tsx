import { useState, useEffect, useRef } from 'react';
import { useAppStore } from '@/stores/appStore';
import { getTaskDetail, continueAgentTask } from '@/api/pywebview';
import StepList from './StepList';
import LoadingSpinner from '@/components/ui/LoadingSpinner';
import { Send, MessageSquarePlus } from 'lucide-react';

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
  const { taskDetail, isLoading, switchPage, setTaskDetail, showToast } = useAppStore();

  // Continue 功能状态
  const [showContinue, setShowContinue] = useState(false);
  const [continuePrompt, setContinuePrompt] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 是否可以继续对话（仅 completed 和 error 状态）
  const canContinue = taskDetail?.status === 'completed' || taskDetail?.status === 'error';

  // 自动刷新详情（running 状态 3 秒，其他状态 10 秒）
  useEffect(() => {
    if (!taskDetail) return;

    const refreshInterval = taskDetail.status === 'running' ? 3000 : 10000;

    const refreshDetail = async () => {
      try {
        const updated = await getTaskDetail(taskDetail.session_id);
        setTaskDetail(updated);
      } catch (error) {
        console.error('Failed to refresh task detail:', error);
      }
    };

    const interval = setInterval(refreshDetail, refreshInterval);
    return () => clearInterval(interval);
  }, [taskDetail?.session_id, taskDetail?.status, setTaskDetail]);

  // 展开输入框时自动聚焦
  useEffect(() => {
    if (showContinue && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [showContinue]);

  // 继续对话提交
  const handleContinueSubmit = async () => {
    const trimmed = continuePrompt.trim();
    if (!trimmed || isSubmitting || !taskDetail) return;

    setIsSubmitting(true);
    try {
      const result = await continueAgentTask(taskDetail.session_id, trimmed);
      if (result.status === 'ok') {
        setContinuePrompt('');
        setShowContinue(false);
        showToast('已发送继续对话请求', 'success');
        // 刷新详情以获取新状态
        const updated = await getTaskDetail(taskDetail.session_id);
        setTaskDetail(updated);
      } else {
        showToast(result.error || '发送失败', 'error');
      }
    } catch (error) {
      console.error('Failed to continue task:', error);
      showToast('发送失败', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleContinueKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleContinueSubmit();
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
    <div className="flex flex-col h-full overflow-hidden gap-4">
      {/* 固定头部区域 */}
      <div className="shrink-0 flex flex-col gap-4">
        {/* 返回按钮 */}
        <button
          className="btn btn-ghost self-start"
          onClick={() => switchPage('tasks')}
        >
          ← 返回任务列表
        </button>

        {/* 任务信息卡片 - 保持原样式 */}
        <div className="card">
          <div className="flex justify-between items-start mb-4">
            <h2 className="text-lg font-medium text-[var(--text-primary)] flex-1">
              {taskDetail.name}
            </h2>
            {/* Continue 按钮 - 放在标题右侧 */}
            {canContinue && !showContinue && (
              <button
                className="btn btn-primary flex items-center gap-2 ml-4 shrink-0"
                onClick={() => setShowContinue(true)}
              >
                <MessageSquarePlus size={16} />
                继续对话
              </button>
            )}
            {/* Running 状态提示 */}
            {taskDetail.status === 'running' && (
              <div className="flex items-center gap-2 text-sm text-[var(--accent-warning)] ml-4 shrink-0">
                <LoadingSpinner size="sm" />
                运行中
              </div>
            )}
          </div>

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

        {/* Continue 输入区域 */}
        {showContinue && (
          <div className="card">
            <div className="task-input-wrapper">
              <textarea
                ref={textareaRef}
                className="task-input"
                placeholder="输入要继续的对话内容..."
                value={continuePrompt}
                onChange={(e) => setContinuePrompt(e.target.value)}
                onKeyDown={handleContinueKeyDown}
              />
              <button
                className={`task-input-btn ${continuePrompt.trim() ? 'visible' : ''}`}
                onClick={handleContinueSubmit}
                disabled={isSubmitting || !continuePrompt.trim()}
              >
                {isSubmitting ? (
                  <div className="spinner" />
                ) : (
                  <Send size={16} />
                )}
              </button>
            </div>
            <div className="text-xs text-[var(--text-muted)] mt-2">
              Ctrl+Enter 发送 ·
              <button
                className="text-[var(--accent-primary)] hover:underline ml-1"
                onClick={() => setShowContinue(false)}
              >
                取消
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 步骤列表区域 - 占据剩余空间，内部滚动 */}
      <div className="card flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h3 className="font-medium text-[var(--accent-primary)]">
            执行步骤
          </h3>
        </div>

        {/* StepList 占据剩余空间 */}
        <div className="flex-1 min-h-0">
          <StepList steps={[...taskDetail.steps].reverse()} />
        </div>
      </div>
    </div>
  );
}
