/**
 * Recent directories storage utility.
 *
 * Stores recently used directory paths in localStorage for @ autocomplete.
 */

const STORAGE_KEY = 'frago_recent_directories';
const MAX_ENTRIES = 20;

export interface RecentDirectoryEntry {
  path: string;
  lastUsed: number; // timestamp
}

/**
 * Get recent directories from localStorage, sorted by lastUsed descending.
 */
export function getRecentDirectories(): RecentDirectoryEntry[] {
  try {
    const data = localStorage.getItem(STORAGE_KEY);
    if (!data) return [];

    const entries: RecentDirectoryEntry[] = JSON.parse(data);
    return entries.sort((a, b) => b.lastUsed - a.lastUsed);
  } catch {
    return [];
  }
}

/**
 * Add or update a directory in the recent list.
 * Updates lastUsed timestamp if already exists.
 */
export function addRecentDirectory(path: string): void {
  if (!path || typeof path !== 'string') return;

  // Normalize path
  const normalizedPath = path.trim();
  if (!normalizedPath) return;

  try {
    const entries = getRecentDirectories();

    // Check if path already exists
    const existingIndex = entries.findIndex((e) => e.path === normalizedPath);

    if (existingIndex >= 0) {
      // Update timestamp
      entries[existingIndex].lastUsed = Date.now();
    } else {
      // Add new entry
      entries.unshift({
        path: normalizedPath,
        lastUsed: Date.now(),
      });
    }

    // Sort by lastUsed and trim to max entries
    const sorted = entries.sort((a, b) => b.lastUsed - a.lastUsed).slice(0, MAX_ENTRIES);

    localStorage.setItem(STORAGE_KEY, JSON.stringify(sorted));
  } catch {
    // Ignore storage errors
  }
}

/**
 * Extract @/path patterns from text and record them.
 */
export function recordDirectoriesFromText(text: string): void {
  if (!text) return;

  // Match @/path/to/dir or @C:\path\to\dir patterns
  // Stop at whitespace, quotes, or other common delimiters
  const pattern = /@([/\\][\w\-./\\:]+|[A-Za-z]:[/\\][\w\-./\\:]*)/g;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    const path = match[1];
    if (path) {
      addRecentDirectory(path);
    }
  }
}

/**
 * Clear all recent directories.
 */
export function clearRecentDirectories(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}
