/**
 * proxyPrefetchPolicy — how far the EH proxy Reader prefetches, decided from
 * how the reader is moving through the gallery.
 *
 * Regression context: proxy prefetch used to chain pageNum + 1 with no forward
 * limit, so a reader resting on one page fetched the whole gallery from EH
 * (gallery 3333614: all 80 remaining pages in 70 s). The window is now bounded
 * and sized from page-turn history.
 */

import { describe, it, expect } from 'vitest'
import {
  BURST_WINDOW_MS,
  DEFAULT_LATENCY_MS,
  INITIAL_AHEAD,
  MAX_WINDOW_PAGES,
  SCRUB_QUIET_MS,
  nextProxyConcurrency,
  planProxyPrefetch,
  recordTurn,
  type PageTurn,
} from '../components/Reader/proxyPrefetchPolicy'

/** Build a turn history from [atMs, delta] pairs, classifying bursts as recorded. */
function history(...steps: Array<[number, number]>): PageTurn[] {
  return steps.reduce<PageTurn[]>((turns, [at, delta]) => recordTurn(turns, at, delta), [])
}

describe('planProxyPrefetch', () => {
  it('prefetches a small forward window before the first page turn', () => {
    expect(planProxyPrefetch([], 0, null)).toEqual({
      kind: 'window',
      ahead: INITIAL_AHEAD,
      behind: 0,
      reason: 'initial',
    })
  })

  it('narrows to the next page after a jump instead of filling the old window', () => {
    // 10 → 50: the reader has not shown which way they will read from here.
    const turns = history([0, 40])
    expect(planProxyPrefetch(turns, 100, null)).toEqual({
      kind: 'window',
      ahead: 1,
      behind: 0,
      reason: 'seek',
    })
  })

  it('stays narrow after a single step following a jump', () => {
    const turns = history([0, 40], [5_000, 1])
    const plan = planProxyPrefetch(turns, 5_100, null)
    expect(plan).toMatchObject({ kind: 'window', ahead: 1, behind: 0 })
  })

  it('keeps a slow sequential reader to a short forward window', () => {
    // One page every 10 s with 1.5 s fetches: a couple of pages is enough.
    const turns = history([0, 1], [10_000, 1], [20_000, 1])
    const plan = planProxyPrefetch(turns, 20_100, DEFAULT_LATENCY_MS)
    expect(plan).toEqual({ kind: 'window', ahead: 2, behind: 0, reason: 'forward' })
  })

  it('widens the window for a fast sequential reader', () => {
    // One page every 700 ms with 1.5 s fetches needs several pages in flight.
    const turns = history([0, 1], [700, 1], [1_400, 1])
    const plan = planProxyPrefetch(turns, 1_500, DEFAULT_LATENCY_MS)
    expect(plan).toMatchObject({ kind: 'window', behind: 0, reason: 'forward' })
    if (plan.kind !== 'window') throw new Error('expected a window')
    expect(plan.ahead).toBeGreaterThanOrEqual(4)
    expect(plan.ahead).toBeLessThanOrEqual(MAX_WINDOW_PAGES)
  })

  it('never exceeds the window cap however fast the reader turns', () => {
    const turns = history([0, 1], [600, 1], [1_200, 1])
    const plan = planProxyPrefetch(turns, 1_300, 60_000)
    if (plan.kind !== 'window') throw new Error('expected a window')
    expect(plan.ahead).toBe(MAX_WINDOW_PAGES)
  })

  it('prefetches behind, not ahead, while the reader pages backwards', () => {
    const turns = history([0, -1], [2_000, -1], [4_000, -1])
    const plan = planProxyPrefetch(turns, 4_100, DEFAULT_LATENCY_MS)
    expect(plan).toMatchObject({ kind: 'window', ahead: 0, reason: 'backward' })
    if (plan.kind !== 'window') throw new Error('expected a window')
    expect(plan.behind).toBeGreaterThanOrEqual(2)
  })

  it('counts a double-page spread step in pages', () => {
    const turns = history([0, 2], [10_000, 2], [20_000, 2])
    const plan = planProxyPrefetch(turns, 20_100, DEFAULT_LATENCY_MS)
    expect(plan).toEqual({ kind: 'window', ahead: 4, behind: 0, reason: 'forward' })
  })

  it('holds prefetch while the reader scrubs through pages', () => {
    // Dragging the thumbnail strip or holding an arrow key.
    const turns = history([0, 1], [100, 1], [200, 1], [300, 1])
    expect(planProxyPrefetch(turns, 350, null)).toEqual({
      kind: 'hold',
      resumeAt: 300 + SCRUB_QUIET_MS,
    })
  })

  it('treats the page a scrub stops on as a jump once the reader pauses', () => {
    const turns = history([0, 1], [100, 1], [200, 1], [300, 1])
    expect(planProxyPrefetch(turns, 300 + SCRUB_QUIET_MS, null)).toMatchObject({
      kind: 'window',
      ahead: 1,
      reason: 'seek',
    })
  })

  it('does not mistake ordinary reading turns for a scrub', () => {
    const turns = history([0, 1], [BURST_WINDOW_MS, 1], [BURST_WINDOW_MS * 2, 1])
    expect(turns.some((turn) => turn.burst)).toBe(false)
  })
})

describe('nextProxyConcurrency', () => {
  it('halves on a failed prefetch', () => {
    expect(nextProxyConcurrency(4, { ok: false, ms: 300 })).toBe(2)
  })

  it('halves on a slow prefetch', () => {
    expect(nextProxyConcurrency(4, { ok: true, ms: 8_000 })).toBe(2)
  })

  it('never drops below one request', () => {
    expect(nextProxyConcurrency(1, { ok: false, ms: 300 })).toBe(1)
  })

  it('recovers one slot at a time on fast prefetches, up to the cap', () => {
    expect(nextProxyConcurrency(2, { ok: true, ms: 500 })).toBe(3)
    expect(nextProxyConcurrency(4, { ok: true, ms: 500 })).toBe(4)
  })
})
