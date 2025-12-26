import type { TaskStep } from '@/types/pywebview';
import MarkdownContent from '@/components/ui/MarkdownContent';
import PreformattedContent from './PreformattedContent';
import CollapsibleContent from './CollapsibleContent';
import BashContent from './BashContent';
import FileContent from './FileContent';
import JsonContent from './JsonContent';

interface StepContentProps {
  step: TaskStep;
}

/**
 * Dispatcher component for rendering step content.
 * Chooses the appropriate renderer based on step type and content.
 */
export default function StepContent({ step }: StepContentProps) {
  const { type, content, tool_name } = step;

  // Assistant messages use Markdown rendering
  if (type === 'assistant_message') {
    return (
      <CollapsibleContent content={content} maxLines={10} maxChars={500}>
        <MarkdownContent content={content} />
      </CollapsibleContent>
    );
  }

  // Tool-specific rendering for tool_call type
  if (type === 'tool_call' && tool_name) {
    // Bash commands
    if (tool_name === 'Bash') {
      return (
        <CollapsibleContent content={content} maxLines={5} maxChars={300}>
          <BashContent content={content} />
        </CollapsibleContent>
      );
    }

    // File operations
    if (tool_name === 'Read' || tool_name === 'Write' || tool_name === 'Edit') {
      return (
        <CollapsibleContent content={content} maxLines={5} maxChars={300}>
          <FileContent content={content} toolName={tool_name} />
        </CollapsibleContent>
      );
    }
  }

  // Tool results - check for JSON content
  if (type === 'tool_result' && looksLikeJson(content)) {
    return (
      <CollapsibleContent content={content} maxLines={5} maxChars={300}>
        <JsonContent content={content} />
      </CollapsibleContent>
    );
  }

  // Default: preformatted with collapsible
  return (
    <CollapsibleContent content={content} maxLines={5} maxChars={300}>
      <PreformattedContent content={content} />
    </CollapsibleContent>
  );
}

/**
 * Heuristic to detect if content looks like JSON.
 */
function looksLikeJson(content: string): boolean {
  const trimmed = content.trim();
  // Check if starts with { or [
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      JSON.parse(trimmed);
      return true;
    } catch {
      return false;
    }
  }
  return false;
}
