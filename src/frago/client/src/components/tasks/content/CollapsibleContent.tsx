import { useState, useMemo } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

interface CollapsibleContentProps {
  children: React.ReactNode;
  content: string;
  maxLines?: number;
  maxChars?: number;
}

/**
 * Wraps content with collapse/expand functionality.
 * Collapses if content exceeds maxLines or maxChars threshold.
 */
export default function CollapsibleContent({
  children,
  content,
  maxLines = 5,
  maxChars = 300,
}: CollapsibleContentProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const { shouldCollapse, lineCount } = useMemo(() => {
    const lines = content.split('\n');
    const lineCount = lines.length;
    const charCount = content.length;

    return {
      shouldCollapse: lineCount > maxLines || charCount > maxChars,
      lineCount,
    };
  }, [content, maxLines, maxChars]);

  if (!shouldCollapse) {
    return <>{children}</>;
  }

  return (
    <div className="collapsible-content">
      <div className={isExpanded ? '' : 'collapsible-collapsed'}>
        {children}
      </div>
      <button
        type="button"
        className="collapsible-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded ? "true" : "false"}
      >
        {isExpanded ? (
          <>
            <ChevronUp className="icon-scaled-xs inline-block mr-1" />
            Show less
          </>
        ) : (
          <>
            <ChevronDown className="icon-scaled-xs inline-block mr-1" />
            Show more ({lineCount} lines)
          </>
        )}
      </button>
    </div>
  );
}
