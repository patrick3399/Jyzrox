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

describe('structural-nav-audit — E-hentai paginated favorites snapshot', () => {
  it('test_ehentai_saveBrowseState_hasFavPaginatedGalleries', () => {
    expect(src('app/e-hentai/page.tsx')).toContain('favPaginatedGalleries')
  })

  it('test_ehentai_persistsBrowseStateOnPageLifecycle', () => {
    const page = src('app/e-hentai/page.tsx')
    expect(page).toContain('BROWSE_STATE_KEY')
    expect(page).toContain("window.addEventListener('pagehide', saveBrowseState)")
    expect(page).toContain("document.addEventListener('visibilitychange', handleVisibilityChange)")
    expect(page).toContain('saveBrowseState()')
  })

  it('test_ehentai_restoreDoesNotConsumeValidBrowseStateImmediately', () => {
    const page = src('app/e-hentai/page.tsx')
    expect(page).not.toContain('sessionStorage.removeItem(BROWSE_STATE_KEY)\n    try')
  })

  it('test_ehentai_restoreIsScopedToMatchingNonEmptyUrlState', () => {
    const page = src('app/e-hentai/page.tsx')
    expect(page).toContain('const urlStateKey = searchParams.toString()')
    expect(page).toContain('(parsed as { urlStateKey?: unknown }).urlStateKey === urlStateKey')
    expect(page).toContain("urlStateKey !== ''")
    expect(page).toContain('sessionStorage.removeItem(BROWSE_STATE_KEY)')
    expect(page).toContain('urlStateKey,')
  })

  it('test_ehentai_emptyUrlResetsBrowseStateToHome', () => {
    const page = src('app/e-hentai/page.tsx')
    expect(page).toContain('previousUrlStateKeyRef')
    expect(page).toContain("if (urlStateKey !== '') return")
    expect(page).toContain("setActiveTab('popular')")
    expect(page).toContain('sessionStorage.removeItem(BROWSE_STATE_KEY)')
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
