/**
 * New subscriptions default to a weekly check. The default must be one of the
 * selectable presets so the create forms highlight it instead of showing an
 * unexplained custom value.
 */

import { describe, it, expect } from 'vitest'
import { CRON_PRESETS, DEFAULT_SUBSCRIPTION_CRON } from '@/components/subscriptions/constants'

describe('DEFAULT_SUBSCRIPTION_CRON', () => {
  it('is the weekly preset', () => {
    expect(DEFAULT_SUBSCRIPTION_CRON).toBe('0 0 * * 1')
    expect(CRON_PRESETS.find((p) => p.value === DEFAULT_SUBSCRIPTION_CRON)?.label).toBe('1w')
  })
})
