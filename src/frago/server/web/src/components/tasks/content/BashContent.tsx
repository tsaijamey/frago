import { Copy, Check } from 'lucide-react';
import { useState } from 'react';

interface BashContentProps {
  content: string;
  className?: string;
}

/**
 * Renders Bash command content with syntax highlighting.
 * Parses content format: "[Bash] command=..."
 */
export default function BashContent({ content, className = '' }: BashContentProps) {
  const [copied, setCopied] = useState(false);

  // Extract command from content format: "[Bash] command=ls -la"
  const command = extractCommand(content);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API not available
    }
  };

  return (
    <div className={`bash-content ${className}`}>
      <div className="bash-content-header">
        <span className="bash-content-label">Shell</span>
        <button
          type="button"
          className="bash-content-copy"
          onClick={handleCopy}
          title="Copy command"
        >
          {copied ? (
            <Check className="icon-scaled-xs" />
          ) : (
            <Copy className="icon-scaled-xs" />
          )}
        </button>
      </div>
      <pre className="bash-content-code">
        <span className="bash-prompt">$</span> {command}
      </pre>
    </div>
  );
}

/**
 * Extracts command from content string.
 * Handles formats like "[Bash] command=ls -la" or plain command.
 */
function extractCommand(content: string): string {
  // Try to match "[Bash] command=..." pattern
  const match = content.match(/^\[Bash\]\s*(.+)$/);
  if (match) {
    const rest = match[1];
    // Check if it's "command=..." format
    if (rest.startsWith('command=')) {
      return rest.slice(8).trim();
    }
    return rest.trim();
  }

  // Return as-is if no pattern matched
  return content.trim();
}
