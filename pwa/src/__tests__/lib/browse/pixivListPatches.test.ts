import { describe, expect, it } from 'vitest'
import {
  pixivBookmarkPatch,
  pixivFollowPatch,
  pixivIdentityKey,
  type PixivBrowseItem,
} from '@/lib/browse/pixiv'

const FEED = pixivIdentityKey({ surface: 'feed' })
const PUBLIC_BOOKMARKS = pixivIdentityKey({ surface: 'bookmarks', restrict: 'public' })
const PRIVATE_BOOKMARKS = pixivIdentityKey({ surface: 'bookmarks', restrict: 'private' })
const FOLLOWING = pixivIdentityKey({ surface: 'following', restrict: 'public' })

function work(
  id: number,
  fields: Record<string, unknown> = { is_bookmarked: false, total_bookmarks: 10 },
): PixivBrowseItem {
  return { kind: 'illust', illust: { id, title: `Work ${id}`, ...fields } }
}

function artist(id: number, fields: Record<string, unknown> = {}): PixivBrowseItem {
  return { kind: 'user', preview: { user: { id, name: `Artist ${id}`, ...fields }, illusts: [] } }
}

function ranked(id: number): PixivBrowseItem {
  return { kind: 'ranking', entry: { illust_id: id, title: `Ranked ${id}` } }
}

describe('pixivBookmarkPatch', () => {
  it('stars the bookmarked work and raises its count by one', () => {
    expect(pixivBookmarkPatch(7, true).updateItem(work(7), FEED)).toEqual(
      work(7, { is_bookmarked: true, total_bookmarks: 11 }),
    )
  })

  it('keeps an un-bookmarked work in a Bookmarks list with its star cleared', () => {
    expect(
      pixivBookmarkPatch(7, false).updateItem(
        work(7, { is_bookmarked: true, total_bookmarks: 3 }),
        PUBLIC_BOOKMARKS,
      ),
    ).toEqual(work(7, { is_bookmarked: false, total_bookmarks: 2 }))
  })

  it('returns other items and a work already in the target state unchanged', () => {
    const patch = pixivBookmarkPatch(7, true)
    const other = work(8)
    const already = work(7, { is_bookmarked: true, total_bookmarks: 11 })
    const rankedWork = ranked(7)

    expect(patch.updateItem(other, FEED)).toBe(other)
    expect(patch.updateItem(already, FEED)).toBe(already)
    expect(patch.updateItem(rankedWork, FEED)).toBe(rankedWork)
  })

  it('sets the star without touching the count when the work did not report its bookmark state', () => {
    expect(pixivBookmarkPatch(7, true).updateItem(work(7, { total_bookmarks: 10 }), FEED)).toEqual(
      work(7, { total_bookmarks: 10, is_bookmarked: true }),
    )
  })

  it('discards only a saved public Bookmarks list that lacks a new bookmark', () => {
    const patch = pixivBookmarkPatch(7, true)

    expect(patch.invalidates?.(PUBLIC_BOOKMARKS, [work(1)])).toBe(true)
    expect(patch.invalidates?.(PUBLIC_BOOKMARKS, [work(7)])).toBe(false)
    expect(patch.invalidates?.(PRIVATE_BOOKMARKS, [work(1)])).toBe(false)
    expect(patch.invalidates?.(FEED, [work(1)])).toBe(false)
    expect(pixivBookmarkPatch(7, false).invalidates?.(PUBLIC_BOOKMARKS, [work(1)])).toBe(false)
  })
})

describe('pixivFollowPatch', () => {
  it('keeps an unfollowed artist in the Following list with the follow flag cleared', () => {
    expect(
      pixivFollowPatch(5, false).updateItem(artist(5, { is_followed: true }), FOLLOWING),
    ).toEqual(artist(5, { is_followed: false }))
  })

  it('treats a Following item without the flag as followed', () => {
    const item = artist(5)

    expect(pixivFollowPatch(5, true).updateItem(item, FOLLOWING)).toBe(item)
    expect(pixivFollowPatch(5, false).updateItem(item, FOLLOWING)).toEqual(
      artist(5, { is_followed: false }),
    )
  })

  it('marks a re-followed artist as followed again', () => {
    expect(
      pixivFollowPatch(5, true).updateItem(artist(5, { is_followed: false }), FOLLOWING),
    ).toEqual(artist(5, { is_followed: true }))
  })

  it('discards a saved Following list that lacks a newly followed artist', () => {
    const patch = pixivFollowPatch(5, true)

    expect(patch.invalidates?.(FOLLOWING, [artist(1)])).toBe(true)
    expect(patch.invalidates?.(FOLLOWING, [artist(5)])).toBe(false)
    expect(patch.invalidates?.(FEED, [work(1)])).toBe(false)
    expect(pixivFollowPatch(5, false).invalidates?.(FOLLOWING, [artist(1)])).toBe(false)
  })
})
