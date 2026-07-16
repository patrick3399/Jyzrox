/**
 * wsPolling.ts — Vitest test suite
 *
 * Covers:
 *   pollingRefreshInterval — returns 0 when connected (event-driven, no polling)
 *   pollingRefreshInterval — returns the fallback interval when disconnected
 *   pollingRefreshInterval — regression: matches each page's demoted fallback value
 */

import { describe, it, expect } from 'vitest'
import { pollingRefreshInterval } from '@/lib/wsPolling'

describe('pollingRefreshInterval', () => {
  it('test_pollingRefreshInterval_connectedTrue_returnsZero', () => {
    expect(pollingRefreshInterval(true, 5000)).toBe(0)
  })

  it('test_pollingRefreshInterval_connectedFalse_returnsFallbackMs', () => {
    expect(pollingRefreshInterval(false, 5000)).toBe(5000)
  })

  it('test_pollingRefreshInterval_connectedTrue_ignoresFallbackMagnitude', () => {
    // Regardless of how large the fallback is, connected must always poll off.
    expect(pollingRefreshInterval(true, 60000)).toBe(0)
    expect(pollingRefreshInterval(true, 0)).toBe(0)
  })

  it('test_pollingRefreshInterval_dashboardJobsWidget_matchesDemotedFallback', () => {
    // app/page.tsx dashboard/jobs SWR — was a fixed refreshInterval: 5000.
    expect(pollingRefreshInterval(true, 5000)).toBe(0)
    expect(pollingRefreshInterval(false, 5000)).toBe(5000)
  })

  it('test_pollingRefreshInterval_subscriptionsSubJobs_matchesDemotedFallback', () => {
    // app/subscriptions/page.tsx sub-jobs SWR — was a fixed refreshInterval: 5000.
    expect(pollingRefreshInterval(true, 5000)).toBe(0)
    expect(pollingRefreshInterval(false, 5000)).toBe(5000)
  })

  it('test_pollingRefreshInterval_libraryActiveJob_matchesDemotedFallback', () => {
    // app/library/[source]/[sourceId]/page.tsx activeJob SWR — was refreshInterval: 3000.
    expect(pollingRefreshInterval(true, 3000)).toBe(0)
    expect(pollingRefreshInterval(false, 3000)).toBe(3000)
  })
})
