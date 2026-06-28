import { describe, it, expect, beforeEach } from 'vitest'
import { resolveTabRoot, rememberLocation, getTabHref, clearTabMemory } from '@/lib/navMemory'

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
