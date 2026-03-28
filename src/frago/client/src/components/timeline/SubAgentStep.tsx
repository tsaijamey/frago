/**
 * SubAgentStep — Renders a single step within a sub-agent block.
 *
 * Visual weight varies by step type:
 * - sa_thinking: 48px, double line, white
 * - sa_tool_ok: 32px, single line, dim
 * - sa_tool_err: 40px, double line, red
 * - sa_running: 32px, single line, yellow
 * - sa_result: 64px, double line, green highlight
 * - sa_complete: 40px, single line, green
 */

import type { StepData } from './SubAgentBlock';

interface SubAgentStepProps {
  step: StepData;
  baseTimestamp?: string;
  expanded?: boolean;
}

function getStepDisplay(step: StepData) {
  const { type, content, tool_name, success } = step;

  // assistant message — thinking/decision
  if (type === 'assistant') {
    const firstLine = content?.split('\n')[0] || '';
    return {
      icon: '◇',
      iconClass: 'tl-icon--white',
      title: firstLine.slice(0, 80) || '思考中...',
      subtitle: content && content.length > 80 ? content.slice(80, 200) : undefined,
      rowClass: 'tl-step--thinking',
    };
  }

  // tool_call — executing a tool
  if (type === 'tool_call') {
    const toolAction = getToolAction(tool_name || '');
    const target = extractTarget(content || '');
    return {
      icon: '→',
      iconClass: 'tl-icon--yellow',
      title: `${toolAction} ${target}`,
      subtitle: undefined,
      rowClass: 'tl-step--tool-call',
    };
  }

  // tool_result — result of tool execution
  if (type === 'tool_result') {
    const isError = success === false || /error|Error|failed|exception/i.test(content || '');
    if (isError) {
      return {
        icon: '✗',
        iconClass: 'tl-icon--error',
        title: `失败`,
        subtitle: content?.slice(0, 100),
        rowClass: 'tl-step--tool-err',
      };
    }
    return {
      icon: '✓',
      iconClass: 'tl-icon--dim',
      title: `完成`,
      subtitle: undefined,
      rowClass: 'tl-step--tool-ok',
    };
  }

  // system message
  if (type === 'system') {
    return {
      icon: '■',
      iconClass: 'tl-icon--accent',
      title: content?.slice(0, 80) || 'system',
      subtitle: undefined,
      rowClass: 'tl-step--complete',
    };
  }

  // fallback
  return {
    icon: '•',
    iconClass: 'tl-icon--dim',
    title: content?.slice(0, 80) || type,
    subtitle: undefined,
    rowClass: '',
  };
}

function getToolAction(toolName: string): string {
  const actions: Record<string, string> = {
    Read: '读取',
    Write: '写入',
    Edit: '编辑',
    Glob: '搜索文件',
    Grep: '搜索内容',
    Bash: '执行',
    WebFetch: '请求',
    WebSearch: '搜索',
    Agent: '子任务',
    TodoWrite: '记录待办',
  };
  return actions[toolName] || toolName;
}

function extractTarget(content: string): string {
  // Format: "[ToolName] key=value"
  const match = content.match(/^\[.*?\]\s*(?:\w+=)?(.*)/);
  if (!match) return content.slice(0, 60);
  const value = match[1];

  // Extract basename for file paths
  if (value.includes('/')) {
    const parts = value.split('/');
    return parts[parts.length - 1].slice(0, 60);
  }

  // Extract hostname for URLs
  try {
    if (value.startsWith('http')) {
      return new URL(value).hostname;
    }
  } catch { /* ignore */ }

  return value.slice(0, 60);
}

function formatDelta(stepTs: string, baseTs?: string): string {
  if (!baseTs) return '';
  const delta = (new Date(stepTs).getTime() - new Date(baseTs).getTime()) / 1000;
  if (delta < 0) return '';
  if (delta < 60) return `+${Math.round(delta)}s`;
  return `+${Math.floor(delta / 60)}m${Math.round(delta % 60)}s`;
}

export default function SubAgentStep({ step, baseTimestamp, expanded }: SubAgentStepProps) {
  const display = getStepDisplay(step);

  return (
    <div className={`tl-row tl-row--sub ${display.rowClass}`}>
      <span className="tl-ts tl-ts--delta">
        {formatDelta(step.timestamp, baseTimestamp)}
      </span>
      <span className={`tl-icon ${display.iconClass}`}>{display.icon}</span>
      <span className="tl-content">
        <span className="tl-text tl-text--secondary">{display.title}</span>
        {display.subtitle && expanded && (
          <span className="tl-subtitle">{display.subtitle}</span>
        )}
      </span>
    </div>
  );
}
