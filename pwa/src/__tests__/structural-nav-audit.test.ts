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

describe('structural-nav-audit — Pixiv reader progress identity', () => {
  it('test_pixiv_reader_usesIllustIdForProgress', () => {
    const page = src('app/reader/pixiv/[id]/page.tsx')
    expect(page).toContain('sourceId={String(illustId)}')
    expect(page).not.toContain('sourceId={title}')
  })
})

describe('structural-nav-audit — Library saveScroll passes data', () => {
  it('test_library_noZeroArgSaveScrollCalls', () => {
    const page = src('app/library/page.tsx')
    const zeroArgMatches = page.match(/saveScroll\(\)/g) ?? []
    expect(zeroArgMatches.length).toBe(0)
  })
})

describe('structural-nav-audit — Library Dataset selection', () => {
  it('wires selected galleries to the Dataset membership API', () => {
    const page = src('app/library/page.tsx')
    expect(page).toContain('useAddDatasetMembers')
    expect(page).toContain('selection: { gallery_ids: [...selectedIds] }')
    expect(page).toContain("t('datasets.addToDataset')")
  })
})

describe('structural-nav-audit — Dataset automatic filters', () => {
  it('wires preview, apply, and exclusion provenance into the review page', () => {
    const page = src('app/datasets/[id]/page.tsx')
    expect(page).toContain('usePreviewDatasetFilters')
    expect(page).toContain('useApplyDatasetFilters')
    expect(page).toContain('image.exclusion_reason')
    expect(page).toContain("t('datasets.previewFilters')")
  })
})

describe('structural-nav-audit — E-hentai browse state architecture', () => {
  // The e-hentai browse page runs on a single reducer (lib/ehBrowseState.ts) driven
  // by useEhBrowse (hooks/useEhBrowse.ts). These assertions pin the memory/restore
  // invariants that back-navigation and tab round-trips depend on.

  it('test_ehentai_persistsSnapshotOnPageLifecycle', () => {
    const hook = src('hooks/useEhBrowse.ts')
    const kernel = src('hooks/useBrowseSession.ts')
    const page = src('app/e-hentai/page.tsx')
    const lifecycle = page.slice(
      page.indexOf('// This page is the sole owner of the E-Hentai scroll lifecycle'),
      page.indexOf('const openItem'),
    )
    expect(hook).toContain("import { useBrowseSession } from '@/hooks/useBrowseSession'")
    expect(hook).toContain('createBrowseSnapshotStore<EhGallery, Cursor>({')
    expect(hook).toContain('validateCursor: isValidEhCursor')
    expect(hook).toContain('validateItem: isEhGallery')
    expect(hook).toContain('validateMeta: isEhFavCategoryMeta')
    expect(kernel).toContain('saveState(\n        store,')
    expect(hook).not.toContain("window.addEventListener('scroll'")
    expect(lifecycle).toContain("window.addEventListener('pagehide', save)")
    expect(lifecycle).toContain('timer = setTimeout(save, 250)')
    expect(lifecycle).not.toContain('clearTimeout(timer)\n      save()')
  })

  it('clears an obsolete E-Hentai grid request before same-key fallback restore', () => {
    const page = src('app/e-hentai/page.tsx')
    const restoreLifecycle = page.slice(
      page.indexOf('if (!restoreInstruction || restoreInstruction.identityKey !== seedKey)'),
      page.indexOf('const handleGridRestoreApplied'),
    )
    const fallback = restoreLifecycle.slice(restoreLifecycle.indexOf('if (scheduledRestoreKeyRef'))
    expect(fallback).toContain('pendingRestoreRef.current = null')
    expect(fallback).toContain('setRestoreRequest(undefined)')
  })

  it('test_ehentai_restoreIsScopedToMatchingQueryKey', () => {
    // A snapshot only restores when its persisted identity matches the requested
    // identity (store lookup filters on queryKey equality).
    expect(src('lib/ehBrowseState.ts')).toContain('x.queryKey === currentKey')
    expect(src('hooks/useEhBrowse.ts')).toContain('parseSnapshot(')
  })

  it('test_ehentai_emptyUrlResetsToHome', () => {
    const hook = src('hooks/useEhBrowse.ts')
    expect(hook).toContain('const searchString = searchParams.toString()')
    expect(hook).toContain('const params = new URLSearchParams(searchString)')
    expect(hook).toContain('...parseUrlToIdentity(params)')
    expect(hook).toContain("identityDispatch({ type: 'APPLY_IDENTITY', identity })")

    const stateLib = src('lib/ehBrowseState.ts')
    const parser = stateLib.slice(
      stateLib.indexOf('export function parseUrlToIdentity'),
      stateLib.indexOf('export function serializeEhSavedSearchParams'),
    )
    expect(parser).toContain(": 'popular'")
    expect(parser).toContain('...initialFilters')
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

describe('structural-nav-audit — AI subsystem removal', () => {
  it('does not register a training page', async () => {
    const { PAGE_REGISTRY } = await import('@/lib/pageRegistry')
    expect(PAGE_REGISTRY.find((page) => page.href === '/training')).toBeUndefined()
  })
})
