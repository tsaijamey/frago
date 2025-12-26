import { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';

interface JsonContentProps {
  content: string;
  className?: string;
}

/**
 * Renders JSON content with formatted display.
 * Attempts to parse and pretty-print JSON, falls back to raw display.
 */
export default function JsonContent({ content, className = '' }: JsonContentProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const { parsed, isValid } = tryParseJson(content);

  if (!isValid) {
    // Fallback to preformatted display
    return <pre className={`step-content-pre ${className}`}>{content}</pre>;
  }

  const formatted = JSON.stringify(parsed, null, 2);
  const preview = getJsonPreview(parsed);

  return (
    <div className={`json-content ${className}`}>
      <button
        type="button"
        className="json-content-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded ? "true" : "false"}
      >
        {isExpanded ? (
          <ChevronDown className="icon-scaled-xs" />
        ) : (
          <ChevronRight className="icon-scaled-xs" />
        )}
        <span className="json-preview">{preview}</span>
      </button>
      {isExpanded && (
        <pre className="json-content-code">{formatted}</pre>
      )}
    </div>
  );
}

function tryParseJson(content: string): { parsed: unknown; isValid: boolean } {
  try {
    // Find JSON start
    const jsonStart = content.search(/[{\[]/);
    if (jsonStart === -1) {
      return { parsed: null, isValid: false };
    }

    const jsonStr = content.slice(jsonStart);
    const parsed = JSON.parse(jsonStr);
    return { parsed, isValid: true };
  } catch {
    return { parsed: null, isValid: false };
  }
}

function getJsonPreview(obj: unknown): string {
  if (Array.isArray(obj)) {
    return `Array[${obj.length}]`;
  }
  if (obj && typeof obj === 'object') {
    const keys = Object.keys(obj);
    if (keys.length <= 3) {
      return `{ ${keys.join(', ')} }`;
    }
    return `Object { ${keys.slice(0, 3).join(', ')}, ... }`;
  }
  return String(obj);
}
