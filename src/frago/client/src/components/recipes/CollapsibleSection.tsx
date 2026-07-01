import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface CollapsibleSectionProps {
  title: string;
  icon: React.ReactNode;
  defaultExpanded?: boolean;
  children: React.ReactNode;
}

export default function CollapsibleSection({ title, icon, defaultExpanded = true, children }: CollapsibleSectionProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div className="border border-[var(--border-color)] rounded-lg overflow-hidden">
      <button
        type="button"
        className="flex items-center gap-2 w-full text-left px-4 py-3 bg-[var(--bg-subtle)] hover:bg-[var(--bg-hover)] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown size={16} className="text-[var(--text-muted)]" />
        ) : (
          <ChevronRight size={16} className="text-[var(--text-muted)]" />
        )}
        {icon}
        <span className="font-medium text-[var(--text-primary)]">{title}</span>
      </button>
      {expanded && (
        <div className="p-4 border-t border-[var(--border-color)]">
          {children}
        </div>
      )}
    </div>
  );
}
