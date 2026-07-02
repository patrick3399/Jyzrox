import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, it, expect } from 'vitest'

const SRC = join(__dirname, '../')

function src(rel: string) {
  return readFileSync(join(SRC, rel), 'utf-8')
}

describe('structural-nav-audit — BackButton', () => {
  it('test_backButton_noLgStaticClass', () => {
    expect(src('components/BackButton.tsx')).not.toContain('lg:static')
  })

  it('test_backButton_hasFixedClass', () => {
    expect(src('components/BackButton.tsx')).toContain('fixed')
  })
})

describe('structural-nav-audit — useScrollRestore hook shape', () => {
  it('test_useScrollRestore_exportsRestoredPages', () => {
    const hook = src('hooks/useScrollRestore.ts')
    expect(hook).toContain('restoredPages')
    expect(hook).toContain('useState')
  })

  it('test_useScrollRestore_saveScrollAcceptsPages', () => {
    const hook = src('hooks/useScrollRestore.ts')
    // saveScroll callback must declare a pages parameter (optional or required)
    expect(hook).toContain('saveScroll')
    expect(hook).toContain('pages?: T[]')
  })
})

describe('structural-nav-audit — Pixiv saveScroll call sites pass data', () => {
  it('test_pixiv_noZeroArgSaveScrollCalls', () => {
    const page = src('app/pixiv/page.tsx')
    const zeroArgMatches = page.match(/saveScroll\(\)/g) ?? []
    // Only SearchResults uses zero-arg saveScroll (one occurrence acceptable)
    expect(zeroArgMatches.length).toBeLessThanOrEqual(1)
  })

  it('test_pixiv_illustCard_hasOnNavigateProp', () => {
    expect(src('app/pixiv/page.tsx')).toContain('onNavigate')
  })
})

describe('structural-nav-audit — Library saveScroll passes data', () => {
  it('test_library_noZeroArgSaveScrollCalls', () => {
    const page = src('app/library/page.tsx')
    const zeroArgMatches = page.match(/saveScroll\(\)/g) ?? []
    expect(zeroArgMatches.length).toBe(0)
  })
})

describe('structural-nav-audit — E-hentai browse state architecture', () => {
  // The e-hentai browse page runs on a single reducer (lib/ehBrowseState.ts) driven
  // by useEhBrowse (hooks/useEhBrowse.ts). These assertions pin the memory/restore
  // invariants that back-navigation and tab round-trips depend on.

  it('test_ehentai_persistsSnapshotOnPageLifecycle', () => {
    const hook = src('hooks/useEhBrowse.ts')
    expect(hook).toContain('SNAPSHOT_KEY')
    expect(hook).toContain("window.addEventListener('pagehide'")
    expect(hook).toContain("document.addEventListener('visibilitychange'")
  })

  it('test_ehentai_restoreIsScopedToMatchingQueryKey', () => {
    // A snapshot only restores when its persisted identity matches the requested
    // identity (store lookup filters on queryKey equality).
    expect(src('lib/ehBrowseState.ts')).toContain('x.queryKey === currentKey')
    expect(src('hooks/useEhBrowse.ts')).toContain('parseSnapshot(')
  })

  it('test_ehentai_emptyUrlResetsToHome', () => {
    const hook = src('hooks/useEhBrowse.ts')
    expect(hook).toContain('searchStr')
    expect(hook).toContain("dispatch({ type: 'RESET' })")
  })

  it('test_ehentai_urlCarriesIdentityNotView', () => {
    // URL serialisation lives in identityToUrlParams and must not leak the view buffer/cursor/scroll.
    const stateLib = src('lib/ehBrowseState.ts')
    expect(stateLib).toContain('export function identityToUrlParams')
    const fnBody = stateLib.slice(
      stateLib.indexOf('export function identityToUrlParams'),
      stateLib.indexOf('export function parseUrlToIdentity'),
    )
    expect(fnBody).not.toMatch(/\bitems\b|scrollY|nextGid/)
  })
})

describe('structural-nav-audit — browser-native back gesture', () => {
  it('test_useSwipeBack_onlyRunsInStandaloneApp', () => {
    const hook = src('hooks/useSwipeBack.ts')
    expect(hook).toContain('isStandaloneApp')
    expect(hook).toContain("window.matchMedia('(display-mode: standalone)').matches")
    expect(hook).toContain('!enabled || !isStandaloneApp()')
  })
})
