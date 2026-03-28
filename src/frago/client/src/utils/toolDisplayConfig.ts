/**
 * Tool display configuration — centralized mapping of tool_name to UI display.
 *
 * Used by SubAgentStep and humanize utilities to convert technical
 * tool_call content into human-readable text.
 */

interface ToolDisplayConfig {
  action: string;
  icon: string;
  extractTarget: (content: string) => string;
}

function extractBasename(content: string): string {
  const match = content.match(/(?:file_path|path)=([^\s]+)/);
  if (!match) return content.replace(/^\[.*?\]\s*/, '').slice(0, 60);
  const path = match[1];
  const parts = path.split('/');
  return parts[parts.length - 1];
}

function extractCommand(content: string): string {
  const match = content.match(/command=(.+)/);
  if (!match) return content.replace(/^\[.*?\]\s*/, '').slice(0, 60);
  return match[1].replace(/^uv run\s+/, '').slice(0, 60);
}

function extractPattern(content: string): string {
  const match = content.match(/pattern=([^\s]+)/);
  if (!match) {
    const queryMatch = content.match(/query=([^\s]+)/);
    return queryMatch ? queryMatch[1].slice(0, 60) : content.replace(/^\[.*?\]\s*/, '').slice(0, 60);
  }
  return match[1].slice(0, 60);
}

function extractHostname(content: string): string {
  const match = content.match(/url=([^\s]+)/);
  if (!match) return content.replace(/^\[.*?\]\s*/, '').slice(0, 60);
  try {
    return new URL(match[1]).hostname;
  } catch {
    return match[1].slice(0, 40);
  }
}

function extractQuery(content: string): string {
  const match = content.match(/query=(.+)/);
  return match ? match[1].slice(0, 60) : content.replace(/^\[.*?\]\s*/, '').slice(0, 60);
}

function extractFirstLine(content: string): string {
  return content.replace(/^\[.*?\]\s*/, '').split('\n')[0].slice(0, 60);
}

const TOOL_DISPLAY: Record<string, ToolDisplayConfig> = {
  // File operations
  Read:       { action: '读取',     icon: '→', extractTarget: extractBasename },
  Write:      { action: '写入',     icon: '→', extractTarget: extractBasename },
  Edit:       { action: '编辑',     icon: '→', extractTarget: extractBasename },
  Glob:       { action: '搜索文件', icon: '→', extractTarget: extractPattern },
  Grep:       { action: '搜索内容', icon: '→', extractTarget: extractPattern },
  // Execution
  Bash:       { action: '执行',     icon: '→', extractTarget: extractCommand },
  // Network
  WebFetch:   { action: '请求',     icon: '→', extractTarget: extractHostname },
  WebSearch:  { action: '搜索',     icon: '→', extractTarget: extractQuery },
  // Agent
  Agent:      { action: '子任务',   icon: '▸', extractTarget: extractFirstLine },
  // Other
  TodoWrite:  { action: '记录待办', icon: '→', extractTarget: extractFirstLine },
  NotebookEdit: { action: '编辑笔记', icon: '→', extractTarget: extractBasename },
};

export function getToolDisplay(toolName: string): ToolDisplayConfig {
  return TOOL_DISPLAY[toolName] ?? {
    action: toolName,
    icon: '→',
    extractTarget: (c: string) => c.replace(/^\[.*?\]\s*/, '').slice(0, 60),
  };
}

export function humanizeToolCall(toolName: string, content: string): string {
  const config = getToolDisplay(toolName);
  const target = config.extractTarget(content);
  return `${config.action} ${target}`;
}
