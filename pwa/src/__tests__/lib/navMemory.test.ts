import { describe, it, expect, beforeEach } from 'vitest'
import {
  resolveTabRoot,
  rememberLocation,
  getTabHref,
  getListHref,
  clearTabMemory,
  markTabRestore,
  consumeTabRestore,
} from '@/lib/navMemory'

const ROOTS = ['/e-hentai', '/pixiv', '/library', '/queue']

describe('resolveTabRoot', () => {
  it('matches the exact root', () => {
    expect(resolveTabRoot(ROOTS, '/pixiv')).toBe('/pixiv')
  })
  it('matches a nested path to its owning root', () => {
    expect(resolveTabRoot(ROOTS, '/e-hentai/123/abc')).toBe('/e-hentai')
  })
  it('returns the longest matching root', () => {
    expect(resolveTabRoot(['/library', '/library/source'], '/library/source/x')).toBe(
      '/library/source',
    )
  })
  it('does not match a path outside any root', () => {
    expect(resolveTabRoot(ROOTS, '/settings/general')).toBeNull()
  })
  it('does not treat a prefix-but-not-segment as a match', () => {
    expect(resolveTabRoot(['/lib'], '/library')).toBeNull()
  })
})

describe('rememberLocation / getTabHref / clearTabMemory', () => {
  beforeEach(() => sessionStorage.clear())

  it('falls back to the bare root when nothing stored', () => {
    expect(getTabHref('/e-hentai')).toBe('/e-hentai')
  })
  it('stores and returns the full url including query', () => {
    rememberLocation(ROOTS, '/e-hentai', 'fav=1&page=3')
    expect(getTabHref('/e-hentai')).toBe('/e-hentai?fav=1&page=3')
  })
  it('stores a nested path under its owning root', () => {
    rememberLocation(ROOTS, '/e-hentai/123/abc', '')
    expect(getTabHref('/e-hentai')).toBe('/e-hentai/123/abc')
  })
  it('ignores paths outside any root', () => {
    rememberLocation(ROOTS, '/settings/general', 'x=1')
    expect(getTabHref('/settings')).toBe('/settings')
  })
  it('clearTabMemory removes the entry', () => {
    rememberLocation(ROOTS, '/pixiv', 'tab=feed')
    clearTabMemory('/pixiv')
    expect(getTabHref('/pixiv')).toBe('/pixiv')
  })
  it('survives malformed storage without throwing', () => {
    sessionStorage.setItem('nav_memory_v1', '{not json')
    expect(getTabHref('/pixiv')).toBe('/pixiv')
  })
})

describe('getListHref — last list-level URL per tab root', () => {
  beforeEach(() => sessionStorage.clear())

  it('records the root-level URL separately from the deep URL', () => {
    rememberLocation(ROOTS, '/e-hentai', 'tab=favorites')
    rememberLocation(ROOTS, '/e-hentai/123/abc', 'fav=1')
    // Deep entry wins for the tab restore…
    expect(getTabHref('/e-hentai')).toBe('/e-hentai/123/abc?fav=1')
    // …but the list-level entry still knows where "up" is.
    expect(getListHref('/e-hentai')).toBe('/e-hentai?tab=favorites')
  })

  it('falls back to the bare root when the list level was never visited', () => {
    rememberLocation(ROOTS, '/e-hentai/123/abc', 'fav=1')
    expect(getListHref('/e-hentai')).toBe('/e-hentai')
  })

  it('clearTabMemory drops the list-level entry too', () => {
    rememberLocation(ROOTS, '/e-hentai', 'tab=favorites')
    clearTabMemory('/e-hentai')
    expect(getListHref('/e-hentai')).toBe('/e-hentai')
  })
})

describe('markTabRestore / consumeTabRestore', () => {
  beforeEach(() => sessionStorage.clear())

  it('consumes only when the current URL matches the marked destination', () => {
    markTabRestore('/e-hentai/123/abc?fav=1')
    expect(consumeTabRestore('/e-hentai/999/zzz')).toBe(false)
    expect(consumeTabRestore('/e-hentai/123/abc?fav=1')).toBe(true)
    // one-shot: consumed
    expect(consumeTabRestore('/e-hentai/123/abc?fav=1')).toBe(false)
  })

  it('returns false when nothing was marked', () => {
    expect(consumeTabRestore('/e-hentai/123/abc?fav=1')).toBe(false)
  })
})
