import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const source = fs.readFileSync(path.resolve(process.cwd(), 'src/app/pixiv/page.tsx'), 'utf8')

describe('Pixiv Phase 2 single-owner wiring', () => {
  it('removes every SWR/scroll fallback browse owner and all four fixed legacy keys', () => {
    expect(source).toContain('usePixivBrowseSession')
    expect(source).not.toContain('useSWRInfinite')
    expect(source).not.toContain('useScrollRestore')
    expect(source).not.toContain('swrFallback')
    expect(source).not.toContain('restoredPages')
    expect(source).not.toContain('saveScroll')
    for (const key of [
      'pixiv_ranking_scrollY',
      'pixiv_feed_scrollY',
      'pixiv_bookmarks_scrollY',
      'pixiv_search_scrollY',
    ]) {
      expect(source).not.toContain(key)
    }
  })

  it('uses one synchronous anchor checkpoint opener for illustration and user navigation on every surface', () => {
    expect(source).toMatch(
      /const\s+openPixivItem\s*=\s*useCallback\([\s\S]*?checkpoint\([\s\S]*?(?:router\.push|href)/,
    )
    expect(source).toMatch(
      /const\s+openPixivUser\s*=\s*useCallback\([\s\S]*?checkpoint\([\s\S]*?(?:router\.push|href)/,
    )
    expect(source.match(/openPixivItem\(/g)?.length ?? 0).toBeGreaterThanOrEqual(5)
    expect(source.match(/openPixivUser\(/g)?.length ?? 0).toBeGreaterThanOrEqual(2)
  })

  it('wires stable discriminated keys and measured anchor restoration into the shared VirtualGrid', () => {
    const gridCount = source.match(/<VirtualGrid/g)?.length ?? 0
    expect(gridCount).toBeGreaterThan(0)
    expect(source.match(/getItemKey=/g)?.length ?? 0).toBe(gridCount)
    expect(source.match(/restoreRequest=/g)?.length ?? 0).toBe(gridCount)
    expect(source.match(/onRestoreApplied=/g)?.length ?? 0).toBe(gridCount)
    expect(source).toContain('onVisibleRangeChange=')
    expect(source).toContain('onLayoutChange=')
  })

  it('stops automatic append on session error and provides an explicit retry without hiding loaded items', () => {
    expect(source).toContain("t('common.retry')")
    expect(source).toMatch(/onClick=\{[\s\S]{0,120}loadMore/)
    expect(source).toMatch(/onLoadMore=\{[^\n]*state\.status === 'error'[^\n]*undefined/)
    expect(source).toMatch(/isLoading=\{[^\n]*(?:state\.status|isSessionLoading)/)
  })

  it('refreshes or patches session-owned items after bookmark and follow mutations', () => {
    expect(source).toMatch(/(?:patchItem|replacePage)/)
    expect(source).toMatch(
      /(?:handleBookmark|onBookmark)[\s\S]*?(?:refresh|patchItem|replacePage)\(/,
    )
    expect(source).toMatch(
      /(?:handleToggleFollow|onFollow)[\s\S]*?(?:refresh|patchItem|replacePage)\(/,
    )
  })
})
