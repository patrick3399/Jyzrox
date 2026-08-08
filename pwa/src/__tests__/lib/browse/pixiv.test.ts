import { describe, expect, it } from 'vitest'
import {
  isPixivBrowseItem,
  isPixivCursor,
  parsePixivIdentity,
  pixivIdentityKey,
  serializePixivIdentity,
} from '@/lib/browse/pixiv'

describe('Pixiv browse identity', () => {
  it('makes search a first-class URL surface with sort, duration, and backend identity', () => {
    const identity = parsePixivIdentity(
      new URLSearchParams(
        'tab=search&q=blue+archive&sort=popular_desc&duration=within_last_week',
      ),
      'authenticated',
    )

    expect(identity).toEqual({
      surface: 'search',
      query: 'blue archive',
      sort: 'popular_desc',
      duration: 'within_last_week',
      backend: 'authenticated',
    })
    expect(serializePixivIdentity(identity).toString()).toBe(
      'tab=search&q=blue+archive&sort=popular_desc&duration=within_last_week',
    )
    expect(pixivIdentityKey(identity)).not.toBe(
      pixivIdentityKey({ ...identity, backend: 'public' }),
    )
  })

  it('canonicalizes ranking mode, content, and R18 combinations', () => {
    expect(
      parsePixivIdentity(
        new URLSearchParams('tab=ranking&mode=weekly&content=manga&r18=1'),
        'authenticated',
      ),
    ).toEqual({ surface: 'ranking', mode: 'weekly', content: 'all', r18: true })

    expect(
      parsePixivIdentity(
        new URLSearchParams('tab=ranking&mode=monthly&content=ugoira'),
        'authenticated',
      ),
    ).toEqual({ surface: 'ranking', mode: 'monthly', content: 'ugoira', r18: false })
  })

  it('keeps bookmark visibility in canonical identity', () => {
    const publicBookmarks = parsePixivIdentity(
      new URLSearchParams('tab=bookmarks&restrict=public'),
      'authenticated',
    )
    const privateBookmarks = parsePixivIdentity(
      new URLSearchParams('tab=bookmarks&restrict=private'),
      'authenticated',
    )

    expect(publicBookmarks).toEqual({ surface: 'bookmarks', restrict: 'public' })
    expect(privateBookmarks).toEqual({ surface: 'bookmarks', restrict: 'private' })
    expect(pixivIdentityKey(publicBookmarks)).not.toBe(pixivIdentityKey(privateBookmarks))
  })

  it.each([
    ['', { surface: 'ranking', mode: 'daily', content: 'all', r18: false }],
    [
      'tab=unknown&mode=bogus&content=bogus&r18=yes',
      { surface: 'ranking', mode: 'daily', content: 'all', r18: false },
    ],
    [
      'tab=ranking&mode=monthly&content=invalid&r18=1',
      { surface: 'ranking', mode: 'daily', content: 'all', r18: true },
    ],
    ['tab=bookmarks&restrict=invalid', { surface: 'bookmarks', restrict: 'public' }],
    [
      'tab=search&q=+++&sort=invalid&duration=forever',
      { surface: 'ranking', mode: 'daily', content: 'all', r18: false },
    ],
  ])('normalizes invalid/default URL input: %s', (raw, expected) => {
    expect(parsePixivIdentity(new URLSearchParams(raw), 'public')).toEqual(expected)
  })

  it('round-trips every valid surface through URL serialization', () => {
    const identities = [
      { surface: 'ranking', mode: 'daily', content: 'all', r18: false },
      { surface: 'feed' },
      { surface: 'following', restrict: 'public' },
      { surface: 'bookmarks', restrict: 'private' },
      {
        surface: 'search',
        query: 'miku',
        sort: 'date_asc',
        duration: 'within_last_month',
        backend: 'authenticated',
      },
    ] as const

    for (const identity of identities) {
      const parsed = parsePixivIdentity(
        serializePixivIdentity(identity),
        identity.surface === 'search' ? identity.backend : 'authenticated',
      )
      expect(parsed).toEqual(identity)
    }
  })
})

describe('Pixiv cursor and item snapshot validators', () => {
  it.each([
    [{ kind: 'offset', value: 0 }, true],
    [{ kind: 'offset', value: 30 }, true],
    [{ kind: 'page', value: 1 }, true],
    [{ kind: 'offset', value: -1 }, false],
    [{ kind: 'page', value: 0 }, false],
    [{ kind: 'page', value: 1.5 }, false],
    [null, false],
  ])('validates cursor %j', (cursor, valid) => {
    expect(isPixivCursor(cursor)).toBe(valid)
  })

  it.each([
    [{ kind: 'illust', illust: { id: 1 } }, true],
    [{ kind: 'ranking', entry: { illust_id: 2 } }, true],
    [{ kind: 'user', preview: { user: { id: 3 } } }, true],
    [{ kind: 'illust', illust: { id: 0 } }, false],
    [{ kind: 'ranking', entry: {} }, false],
    [{ kind: 'user', preview: { user: { id: '3' } } }, false],
    [{ id: 1 }, false],
  ])('validates discriminated item %j', (item, valid) => {
    expect(isPixivBrowseItem(item)).toBe(valid)
  })
})
