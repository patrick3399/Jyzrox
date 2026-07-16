/**
 * wsPolling.ts — shared helper for the BR-005/F5 polling-demotion pattern.
 *
 * Pages that used to poll on a fixed short interval now rely on WS
 * event-driven invalidation (`wsInvalidation.tsx`) while connected, and only
 * fall back to polling when the WS connection is down. Extracted as a pure
 * function so the fallback math is unit-testable without mounting a
 * component or a WS connection.
 */

/**
 * Returns the SWR `refreshInterval` to use given the current WS connection
 * state: `0` (no polling — rely on WS-driven invalidation) when connected,
 * or `fallbackMs` when disconnected.
 */
export function pollingRefreshInterval(connected: boolean, fallbackMs: number): number {
  return connected ? 0 : fallbackMs
}
