/**
 * Local time utilities.
 *
 * Backend convention: all timestamps are naive local-time ISO strings
 * (no timezone suffix). Frontend must match this when generating timestamps
 * that will coexist with backend data.
 */

/**
 * Returns the current local time as an ISO-like string without timezone suffix.
 * Example: "2026-03-24T14:30:05.123"
 */
export function localISOString(date: Date = new Date()): string {
  const pad = (n: number, len = 2) => String(n).padStart(len, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
    `.${pad(date.getMilliseconds(), 3)}`
  );
}
