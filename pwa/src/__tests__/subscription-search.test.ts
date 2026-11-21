import { describe, expect, it } from 'vitest'
import type { DownloadJob, Subscription } from '@/lib/types'
import { matchesSubscriptionSearch } from '@/lib/subscriptionSearch'

const baseSub = {
  id: 1,
  name: null,
  url: 'https://example.com/users/123456',
  source: 'pixiv',
  gallery_title: null,
} as unknown as Subscription

const withTitle = (title: string | null) => ({ ...baseSub, gallery_title: title }) as Subscription

describe('matchesSubscriptionSearch', () => {
  it('matches a UID-only subscription by its gallery title, case-insensitively', () => {
    expect(matchesSubscriptionSearch(withTitle('Some Artist'), null, 'some artist')).toBe(true)
  })

  it('matches via the latest job gallery title', () => {
    const job = { gallery_title: 'Job Gallery Name' } as unknown as DownloadJob
    expect(matchesSubscriptionSearch(baseSub, job, 'gallery name')).toBe(true)
  })

  it('matches name, url and source', () => {
    const sub = { ...baseSub, name: 'Alice' } as Subscription
    expect(matchesSubscriptionSearch(sub, null, 'ALICE')).toBe(true)
    expect(matchesSubscriptionSearch(sub, null, '123456')).toBe(true)
    expect(matchesSubscriptionSearch(sub, null, 'pixiv')).toBe(true)
  })

  it('returns false when nothing matches', () => {
    expect(matchesSubscriptionSearch(withTitle('Some Artist'), null, 'zzz-nope')).toBe(false)
  })

  it('treats an empty or whitespace query as a match', () => {
    expect(matchesSubscriptionSearch(baseSub, null, '')).toBe(true)
    expect(matchesSubscriptionSearch(baseSub, undefined, '   ')).toBe(true)
  })

  it('does not throw when name, gallery_title and job are null/undefined', () => {
    expect(() => matchesSubscriptionSearch(baseSub, undefined, 'zzz-no-match')).not.toThrow()
    expect(matchesSubscriptionSearch(baseSub, null, 'zzz-no-match')).toBe(false)
  })
})
