import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { join } from 'path'

const PAGE = readFileSync(join(__dirname, '../app/subscriptions/page.tsx'), 'utf8')

describe('subscriptions page latest-job loading', () => {
  it('fetches latest jobs with one batched request instead of one call per subscription', () => {
    // A per-subscription fan-out (76 requests at once) tripped nginx's api_zone burst → 503.
    expect(PAGE).toContain('api.subscriptions.latestJobs()')
    expect(PAGE).not.toMatch(/api\.subscriptions\.jobs\(/)
  })
})
