/**
 * Employee Most-Recently-Used (MRU) ordering & local persistence helpers.
 *
 * Combines two complementary truth sources:
 * 1. Server-computed `last_used_at` (derived from real historical sessions on this machine),
 *    so fresh browsers / new machines naturally surface the genuinely most active employees first.
 * 2. Browser `localStorage` MRU timestamps (`frago-workbench-employee-mru`), so picking an
 *    employee from the `All` popover or launching a session immediately promotes it and
 *    persists across page reloads.
 */

export const EMPLOYEE_MRU_KEY = 'frago-workbench-employee-mru';
const MAX_STORED_ENTRIES = 100;

export function parseEmployeeTimestampMs(iso: string | null | undefined): number {
  if (!iso) return 0;
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

export function readEmployeeMru(): Record<string, number> {
  try {
    const raw = localStorage.getItem(EMPLOYEE_MRU_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const result: Record<string, number> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof k === 'string' && k && typeof v === 'number' && Number.isFinite(v) && v > 0) {
        result[k] = v;
      }
    }
    return result;
  } catch {
    return {};
  }
}

export function touchEmployeeMru(memberPostId: string, tsMs?: number): Record<string, number> {
  const id = memberPostId.trim();
  const current = readEmployeeMru();
  if (!id) return current;
  const stamp = typeof tsMs === 'number' && Number.isFinite(tsMs) && tsMs > 0 ? tsMs : Date.now();
  const next: Record<string, number> = {
    ...current,
    [id]: Math.max(current[id] ?? 0, stamp),
  };

  // Cap persisted entries to avoid unbounded growth if posts are deleted over time.
  const entries = Object.entries(next)
    .sort((a, b) => b[1] - a[1])
    .slice(0, MAX_STORED_ENTRIES);
  const trimmed = Object.fromEntries(entries);
  try {
    localStorage.setItem(EMPLOYEE_MRU_KEY, JSON.stringify(trimmed));
  } catch {
    // Ignore privacy-mode or quota errors
  }
  return trimmed;
}

export function sortEmployeesByMru<
  T extends { member_post_id: string; last_used_at?: string | null },
>(employees: readonly T[], mruMap?: Record<string, number>): T[] {
  const local = mruMap ?? readEmployeeMru();
  const scored = employees.map((emp, idx) => ({
    emp,
    idx,
    score: Math.max(parseEmployeeTimestampMs(emp.last_used_at), local[emp.member_post_id] ?? 0),
  }));
  scored.sort((a, b) => {
    if (a.score !== b.score) return b.score - a.score;
    return a.idx - b.idx;
  });
  return scored.map((entry) => entry.emp);
}
