/**
 * timeUtils.ts — Vitest test suite
 *
 * Covers:
 *   timeAgo — returns empty string for null input
 *   timeAgo — returns 'just now' key when diff is less than 1 minute
 *   timeAgo — returns 'minutesAgo' key with correct count
 *   timeAgo — returns 'hoursAgo' key with correct count
 *   timeAgo — returns 'daysAgo' key with correct count
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── i18n mock — return a readable value so we can inspect the key and params ─

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) => {
    if (params) {
      return `${key}:${JSON.stringify(params)}`
    }
    return key
  },
}))

// ── Import after mock ─────────────────────────────────────────────────

import { timeAgo } from '@/lib/timeUtils'

// ── Helpers ───────────────────────────────────────────────────────────

/** Build an ISO date string that is `ms` milliseconds before now. */
function msAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString()
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('timeAgo', () => {
  it('test_timeAgo_nullInput_returnsEmptyString', () => {
    expect(timeAgo(null)).toBe('')
  })

  it('test_timeAgo_lessThanOneMinuteAgo_returnsJustNowKey', () => {
    const result = timeAgo(msAgo(30_000)) // 30 seconds ago
    expect(result).toBe('timeUtils.justNow')
  })

  it('test_timeAgo_45MinutesAgo_returnsMinutesAgoKeyWithCount', () => {
    const result = timeAgo(msAgo(45 * 60_000))
    expect(result).toContain('timeUtils.minutesAgo')
    expect(result).toContain('"n":"45"')
  })

  it('test_timeAgo_3HoursAgo_returnsHoursAgoKeyWithCount', () => {
    const result = timeAgo(msAgo(3 * 60 * 60_000))
    expect(result).toContain('timeUtils.hoursAgo')
    expect(result).toContain('"n":"3"')
  })

  it('test_timeAgo_5DaysAgo_returnsDaysAgoKeyWithCount', () => {
    const result = timeAgo(msAgo(5 * 24 * 60 * 60_000))
    expect(result).toContain('timeUtils.daysAgo')
    expect(result).toContain('"n":"5"')
  })
})
