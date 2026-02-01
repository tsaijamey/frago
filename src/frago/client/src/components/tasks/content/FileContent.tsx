import { File, FileEdit, FilePlus } from 'lucide-react';

interface FileContentProps {
  content: string;
  toolName: string;
  className?: string;
}

/**
 * Renders file operation content with path highlighting.
 * Supports Read, Write, Edit tool outputs.
 */
export default function FileContent({ content, toolName, className = '' }: FileContentProps) {
  const filePath = extractFilePath(content);
  const Icon = getIcon(toolName);

  return (
    <div className={`file-content ${className}`}>
      <div className="file-content-path">
        <Icon className="icon-scaled-sm file-content-icon" />
        <code className="file-path-text">{filePath}</code>
      </div>
      {content !== filePath && (
        <pre className="file-content-detail">{getDetail(content, filePath)}</pre>
      )}
    </div>
  );
}

function getIcon(toolName: string) {
  switch (toolName) {
    case 'Write':
      return FilePlus;
    case 'Edit':
      return FileEdit;
    default:
      return File;
  }
}

/**
 * Extracts file path from content.
 * Handles formats like "[Read] file_path=/path/to/file"
 */
function extractFilePath(content: string): string {
  // Match [ToolName] file_path=... pattern
  const match = content.match(/^\[(Read|Write|Edit)\]\s*file_path=([^\s]+)/);
  if (match) {
    return match[2];
  }

  // Try to find any path-like string
  const pathMatch = content.match(/(?:^|\s)(\/[^\s]+|[A-Za-z]:\\[^\s]+)/);
  if (pathMatch) {
    return pathMatch[1];
  }

  return content;
}

/**
 * Gets detail content excluding the file path.
 */
function getDetail(content: string, _filePath: string): string {
  // Remove the tool prefix and file path
  let detail = content;

  const prefixMatch = detail.match(/^\[(Read|Write|Edit)\]\s*/);
  if (prefixMatch) {
    detail = detail.slice(prefixMatch[0].length);
  }

  // Remove file_path=... part
  if (detail.startsWith('file_path=')) {
    const restMatch = detail.match(/^file_path=[^\s]+\s*(.*)/s);
    if (restMatch) {
      detail = restMatch[1];
    }
  }

  return detail.trim();
}
