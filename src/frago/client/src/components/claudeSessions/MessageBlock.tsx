import MarkdownContent from '../ui/MarkdownContent';
import { Wrench, Terminal, Brain } from 'lucide-react';
import type { ClaudeSessionBlock } from '@/api/client';

export default function MessageBlock({ block }: { block: ClaudeSessionBlock }) {
  switch (block.type) {
    case 'text':
      return (
        <MarkdownContent content={block.text ?? ''} className="cs-msg-text cs-msg-markdown" />
      );
    case 'thinking':
      return (
        <details className="cs-block cs-block--thinking">
          <summary className="cs-block-summary"><Brain size={12} /> thinking</summary>
          <pre className="cs-block-body">{block.text}</pre>
        </details>
      );
    case 'tool_use': {
      const input = typeof block.tool_input === 'string'
        ? block.tool_input
        : JSON.stringify(block.tool_input ?? {}, null, 2);
      return (
        <details className="cs-block cs-block--tool">
          <summary className="cs-block-summary"><Wrench size={12} /> {block.name || 'tool'}</summary>
          <pre className="cs-block-body">{input}</pre>
        </details>
      );
    }
    case 'tool_result':
      return (
        <details className={`cs-block cs-block--result ${block.is_error ? 'cs-block--error' : ''}`}>
          <summary className="cs-block-summary">
            <Terminal size={12} /> {block.is_error ? 'tool error' : 'tool result'}
          </summary>
          <pre className="cs-block-body">{block.content}</pre>
        </details>
      );
    case 'image':
      return <div className="cs-msg-text cs-block-image">[image]</div>;
    default:
      return null;
  }
}
