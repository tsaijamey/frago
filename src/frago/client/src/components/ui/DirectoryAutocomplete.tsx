/**
 * Directory autocomplete component for @ mentions.
 *
 * Shows a popup with recent directories when user types @.
 * Supports keyboard navigation and filtering.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { Folder } from 'lucide-react';
import { getRecentDirectories, RecentDirectoryEntry } from '../../utils/recentDirectories';
import { getSystemDirectories } from '../../api/client';

interface DirectoryAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  textareaRef: React.RefObject<HTMLTextAreaElement>;
}

interface DirectoryItem {
  path: string;
  isDefault?: boolean; // true for system default directories
}

export default function DirectoryAutocomplete({
  value,
  onChange,
  textareaRef,
}: DirectoryAutocompleteProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [directories, setDirectories] = useState<DirectoryItem[]>([]);
  const [filterText, setFilterText] = useState('');
  const [triggerPosition, setTriggerPosition] = useState<number | null>(null);
  const popupRef = useRef<HTMLDivElement>(null);

  // Load directories (recent + system fallback)
  const loadDirectories = useCallback(async () => {
    const recent = getRecentDirectories();

    if (recent.length > 0) {
      setDirectories(recent.map((r: RecentDirectoryEntry) => ({ path: r.path })));
    } else {
      // Fallback to system directories
      try {
        const systemDirs = await getSystemDirectories();
        const items: DirectoryItem[] = [];
        if (systemDirs.home) {
          items.push({ path: systemDirs.home, isDefault: true });
        }
        if (systemDirs.cwd && systemDirs.cwd !== systemDirs.home) {
          items.push({ path: systemDirs.cwd, isDefault: true });
        }
        setDirectories(items);
      } catch {
        setDirectories([]);
      }
    }
  }, []);

  // Filter directories based on input after @
  const filteredDirectories = directories.filter((dir) => {
    if (!filterText) return true;
    return dir.path.toLowerCase().includes(filterText.toLowerCase());
  });

  // Detect @ trigger in value
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const cursorPos = textarea.selectionStart;
    const textBeforeCursor = value.slice(0, cursorPos);

    // Find the last @ that might be our trigger
    const lastAtIndex = textBeforeCursor.lastIndexOf('@');

    if (lastAtIndex === -1) {
      setIsOpen(false);
      setTriggerPosition(null);
      return;
    }

    // Check if @ is at start or preceded by whitespace
    const charBeforeAt = lastAtIndex > 0 ? textBeforeCursor[lastAtIndex - 1] : ' ';
    if (!/\s/.test(charBeforeAt) && lastAtIndex !== 0) {
      setIsOpen(false);
      setTriggerPosition(null);
      return;
    }

    // Get text after @
    const textAfterAt = textBeforeCursor.slice(lastAtIndex + 1);

    // If there's a space after @, the mention is complete
    if (/\s/.test(textAfterAt)) {
      setIsOpen(false);
      setTriggerPosition(null);
      return;
    }

    // Trigger autocomplete
    if (triggerPosition !== lastAtIndex) {
      setTriggerPosition(lastAtIndex);
      setSelectedIndex(0);
      loadDirectories();
    }

    setFilterText(textAfterAt);
    setIsOpen(true);
  }, [value, textareaRef, loadDirectories, triggerPosition]);

  // Handle keyboard events
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea || !isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      switch (e.key) {
        case 'ArrowUp':
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev > 0 ? prev - 1 : filteredDirectories.length - 1
          );
          break;

        case 'ArrowDown':
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev < filteredDirectories.length - 1 ? prev + 1 : 0
          );
          break;

        case 'Tab':
        case 'Enter':
          if (filteredDirectories.length > 0 && triggerPosition !== null) {
            e.preventDefault();
            selectDirectory(filteredDirectories[selectedIndex]);
          }
          break;

        case 'Escape':
          e.preventDefault();
          setIsOpen(false);
          break;
      }
    };

    textarea.addEventListener('keydown', handleKeyDown);
    return () => textarea.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, selectedIndex, filteredDirectories, triggerPosition]);

  // Select a directory
  const selectDirectory = useCallback(
    (dir: DirectoryItem) => {
      if (triggerPosition === null) return;

      const textarea = textareaRef.current;
      if (!textarea) return;

      const cursorPos = textarea.selectionStart;
      const before = value.slice(0, triggerPosition);
      const after = value.slice(cursorPos);

      // Insert @/path format
      const newValue = `${before}@${dir.path}${after}`;
      onChange(newValue);

      // Move cursor to end of inserted path
      const newCursorPos = triggerPosition + 1 + dir.path.length;
      setTimeout(() => {
        textarea.focus();
        textarea.setSelectionRange(newCursorPos, newCursorPos);
      }, 0);

      setIsOpen(false);
      setTriggerPosition(null);
    },
    [triggerPosition, value, onChange, textareaRef]
  );

  // Scroll selected item into view
  useEffect(() => {
    if (!isOpen || !popupRef.current) return;

    const selectedEl = popupRef.current.querySelector('.selected');
    if (selectedEl) {
      selectedEl.scrollIntoView({ block: 'nearest' });
    }
  }, [selectedIndex, isOpen]);

  if (!isOpen || filteredDirectories.length === 0) {
    return null;
  }

  return (
    <div ref={popupRef} className="directory-autocomplete">
      {filteredDirectories.map((dir, index) => (
        <div
          key={dir.path}
          className={`directory-autocomplete-item ${
            index === selectedIndex ? 'selected' : ''
          }`}
          onClick={() => selectDirectory(dir)}
          title={dir.path}
        >
          <Folder className="icon-scaled-sm flex-shrink-0" />
          <span className="truncate">{dir.path}</span>
          {dir.isDefault && (
            <span className="text-scaled-xs text-[var(--text-muted)] ml-auto flex-shrink-0">
              default
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
