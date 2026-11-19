/**
 * How far the proxy Reader (E-Hentai browse) prefetches, decided from how the
 * reader is moving through the gallery.
 *
 * Every proxied page costs an EH image-page request plus the image itself, and
 * pages the reader never reaches still spend EH's image quota. So the window is
 * sized to cover the time a fetch takes at the reader's pace, not the gallery:
 *
 * - before the first turn: a few pages ahead
 * - after a jump (thumbnail strip, grid, page picker): the next page only, until
 *   two steps in a row show the reader is reading from there
 * - while scrubbing (several turns within half a second): nothing, until the
 *   reader rests; the page they rest on is treated as a jump
 * - reading forward / backward: enough pages in that direction to cover the
 *   fetch latency at the measured dwell time
 *
 * Pure functions only — the hook in `hooks.ts` owns the timers and requests.
 */

/** A turn wider than this many pages is a jump, not a step. Two covers double-page spreads. */
export const SEEK_DISTANCE = 2
/** Turns closer together than this count toward a scrub. */
export const BURST_WINDOW_MS = 500
/** This many turns inside BURST_WINDOW_MS make a scrub. */
export const BURST_TURNS = 3
/** A scrub is over once the reader has rested this long. */
export const SCRUB_QUIET_MS = 300
/** Pages ahead before the reader has turned a page. */
export const INITIAL_AHEAD = 3
/** Steps ahead after a jump, until the reader's direction is known. */
export const SEEK_AHEAD = 1
/** Fewest steps a sequential reader keeps in the window. */
export const MIN_SEQUENTIAL_STEPS = 2
/** Most pages the window may hold in either direction. */
export const MAX_WINDOW_PAGES = 8
/** Fetch time assumed before any prefetch has completed. */
export const DEFAULT_LATENCY_MS = 1_500
/** A pause longer than this is the reader stopping, not reading slowly. */
export const MAX_DWELL_MS = 30_000
/** Most turns kept in the history. */
const MAX_TURNS = 8

/** Most prefetches the proxy Reader keeps in flight. */
export const MAX_PROXY_CONCURRENCY = 4
/** A prefetch faster than this earns back one slot. */
const FAST_PREFETCH_MS = 2_000
/** A prefetch slower than this halves the slots. */
const SLOW_PREFETCH_MS = 5_000

export interface PageTurn {
  /** When the turn happened (ms, same clock as `now`). */
  at: number
  /** Page number change; negative is backwards. */
  delta: number
  /** Part of a scrub: at least BURST_TURNS turns within BURST_WINDOW_MS. */
  burst: boolean
}

export type ProxyPrefetchPlan =
  | {
      kind: 'window'
      /** Pages after the current page to keep fetched, nearest first. */
      ahead: number
      /** Pages before the current page to keep fetched, nearest first. */
      behind: number
      reason: 'initial' | 'seek' | 'forward' | 'backward'
    }
  /** The reader is scrubbing: fetch nothing and look again at `resumeAt`. */
  | { kind: 'hold'; resumeAt: number }

/** Append a turn, marking it as part of a scrub when the turns before it were close. */
export function recordTurn(turns: readonly PageTurn[], at: number, delta: number): PageTurn[] {
  const recent = turns.filter((turn) => at - turn.at < BURST_WINDOW_MS).length
  const burst = recent + 1 >= BURST_TURNS
  return [...turns, { at, delta, burst }].slice(-MAX_TURNS)
}

function isStep(turn: PageTurn): boolean {
  return !turn.burst && turn.delta !== 0 && Math.abs(turn.delta) <= SEEK_DISTANCE
}

function directional(
  steps: number,
  delta: number,
  reason: 'initial' | 'seek' | 'forward' | 'backward',
): ProxyPrefetchPlan {
  const pages = Math.min(MAX_WINDOW_PAGES, steps * Math.abs(delta))
  return delta > 0
    ? { kind: 'window', ahead: pages, behind: 0, reason }
    : { kind: 'window', ahead: 0, behind: pages, reason }
}

/**
 * Decide the prefetch window from the turn history.
 *
 * @param latencyMs smoothed time a proxy prefetch takes, or null before any has completed
 */
export function planProxyPrefetch(
  turns: readonly PageTurn[],
  now: number,
  latencyMs: number | null,
): ProxyPrefetchPlan {
  const last = turns[turns.length - 1]
  if (!last) return { kind: 'window', ahead: INITIAL_AHEAD, behind: 0, reason: 'initial' }

  if (last.burst && now - last.at < SCRUB_QUIET_MS) {
    return { kind: 'hold', resumeAt: last.at + SCRUB_QUIET_MS }
  }
  // A jump, or the page a scrub came to rest on.
  if (!isStep(last)) return { kind: 'window', ahead: SEEK_AHEAD, behind: 0, reason: 'seek' }

  // The run of steps in the same direction that ends with the last turn.
  const sign = Math.sign(last.delta)
  let start = turns.length - 1
  while (start > 0 && isStep(turns[start - 1]) && Math.sign(turns[start - 1].delta) === sign) {
    start -= 1
  }
  const streak = turns.slice(start)
  const before = turns[start - 1]

  if (streak.length === 1) {
    // One step after a jump does not show a direction yet; one step after
    // nothing (or after turning around) gets the opening window that way.
    if (before && !isStep(before)) return directional(SEEK_AHEAD, last.delta, 'seek')
    return directional(INITIAL_AHEAD, last.delta, 'initial')
  }

  let total = 0
  for (let i = 1; i < streak.length; i++) {
    total += Math.min(MAX_DWELL_MS, streak[i].at - streak[i - 1].at)
  }
  const dwell = Math.max(1, total / (streak.length - 1))
  const latency = latencyMs ?? DEFAULT_LATENCY_MS
  const steps = Math.max(MIN_SEQUENTIAL_STEPS, Math.ceil(latency / dwell) + 1)
  return directional(steps, last.delta, sign > 0 ? 'forward' : 'backward')
}

/**
 * Concurrency after a prefetch settles: halve on failure or a slow fetch, so a
 * struggling EH backend gets fewer requests; recover one slot per fast fetch.
 */
export function nextProxyConcurrency(
  current: number,
  outcome: { ok: boolean; ms: number },
): number {
  if (!outcome.ok || outcome.ms > SLOW_PREFETCH_MS) return Math.max(1, Math.floor(current / 2))
  if (outcome.ms < FAST_PREFETCH_MS) return Math.min(MAX_PROXY_CONCURRENCY, current + 1)
  return current
}
