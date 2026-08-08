import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const source = fs.readFileSync(path.resolve(process.cwd(), 'src/app/library/page.tsx'), 'utf8')

describe('Library browse-session page wiring contract', () => {
  it('uses the shared browse session instead of the global persisted scroll fallback', () => {
    expect(source).toMatch(/use(?:Library)?BrowseSession/)
    expect(source).not.toContain('useScrollRestore')
    expect(source).not.toContain("'library_scrollY'")
  })

  it('has exactly one browse data owner after the page cutover', () => {
    expect(source).not.toContain('useSearchGalleries')
    expect(source).not.toContain('restoredPages')
    expect(source).not.toContain('fallbackData')
    expect(source).not.toContain('saveScroll(searchData')
  })

  it('refreshes session-owned items after Library mutations without search SWR invalidation', () => {
    expect(source).toMatch(/const\s+\{[\s\S]*?refresh[\s\S]*?}\s*=\s*useLibraryBrowseSession/)
    expect(source).not.toMatch(/\bmutate\(\)/)
    expect(source).not.toContain("key[0] === 'search/galleries'")

    const favorite = source.match(/const handleFavoriteToggle[\s\S]*?const handleDelete/)?.[0] ?? ''
    const deletion =
      source.match(/const handleDelete[\s\S]*?const handleReadingListToggle/)?.[0] ?? ''
    const reading = source.match(/const handleReadingListToggle[\s\S]*?\/\/ ── Keyboard/)?.[0] ?? ''
    expect(favorite).toMatch(/refresh\(/)
    expect(deletion).toMatch(/refresh\(/)
    expect(reading).toMatch(/refresh\(/)

    const batchSection =
      source.match(/\{selectMode && selectedIds\.size > 0[\s\S]*?\{batchTagMode &&/)?.[0] ?? ''
    const batchMutationCount = batchSection.match(/api\.library\.batchGalleries\(/g)?.length ?? 0
    const batchRefreshCount = batchSection.match(/refresh\(/g)?.length ?? 0
    expect(batchMutationCount).toBeGreaterThan(0)
    expect(batchRefreshCount).toBeGreaterThanOrEqual(batchMutationCount)
  })

  it('checkpoints synchronously before the centralized keyboard and pointer navigation push', () => {
    const handler = source.match(
      /const\s+(\w+)\s*=\s*useCallback\([\s\S]*?checkpoint\([\s\S]*?router\.push\([\s\S]*?\n\s*}\s*,\s*\[/,
    )

    expect(
      handler,
      'Library should define one checkpoint-before-push gallery opener',
    ).not.toBeNull()
    const handlerName = handler?.[1] ?? '__missing_library_gallery_opener__'
    expect(
      source.match(new RegExp(`\\b${handlerName}\\b`, 'g'))?.length ?? 0,
    ).toBeGreaterThanOrEqual(3)
    expect(handler?.[0].indexOf('checkpoint(')).toBeLessThan(
      handler?.[0].indexOf('router.push(') ?? -1,
    )
  })

  it('hands the restored item anchor to VirtualGrid and acknowledges measured restoration', () => {
    const grid = source.match(/<VirtualGrid[\s\S]*?\/>/)?.[0] ?? ''

    expect(grid).toContain('restoreRequest=')
    expect(grid).toContain('onRestoreApplied=')
    expect(grid).toContain('getItemKey=')
  })

  it('uses the session retry mode and stops VirtualGrid auto-load while session is errored', () => {
    const grid = source.match(/<VirtualGrid[\s\S]*?\/>/)?.[0] ?? ''

    expect(source).toContain("t('common.retry')")
    expect(source).toMatch(/onClick=\{[\s\S]{0,120}retry/)
    expect(source).toMatch(/const\s+isSessionLoading\s*=\s*[\s\S]{0,100}state\.status/)
    expect(grid).toContain('isLoading={isSessionLoading}')
    expect(grid).toMatch(
      /onLoadMore=\{[^\n]*state\.status === 'error'[^\n]*undefined[^\n]*loadMore/,
    )
  })

  it('checkpoints after scroll settles and on pagehide', () => {
    expect(source).toContain("window.addEventListener('pagehide'")
    expect(source).toMatch(/const save = \(\) => \{[\s\S]{0,240}checkpoint\(view\)/)
    expect(source).toContain('setTimeout(save, 250)')
    expect(source).toContain("window.removeEventListener('pagehide'")
  })

  it('cancels stale restores and acknowledges identity-tagged instructions exactly once', () => {
    expect(source).toContain('cancelAnimationFrame')
    expect(source).toContain('handledRestoreKeyRef')
    expect(source).toMatch(/restoreInstruction\.identityKey[\s\S]{0,120}state\.identityKey/)
    expect(source).toMatch(/acknowledgeRestore\(restoreInstruction\.key\)/)
  })
})
