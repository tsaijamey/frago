interface PreformattedContentProps {
  content: string;
  className?: string;
}

/**
 * Renders content with preserved whitespace and line breaks.
 * Uses CSS white-space: pre-wrap for proper formatting.
 */
export default function PreformattedContent({ content, className = '' }: PreformattedContentProps) {
  return (
    <pre className={`step-content-pre ${className}`}>
      {content}
    </pre>
  );
}
