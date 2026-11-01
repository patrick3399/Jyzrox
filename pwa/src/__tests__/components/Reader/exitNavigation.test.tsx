/**
 * Regression: every way out of the Reader called a bare `router.back()`.
 *
 * With `window.history.length === 1` (a shared link, a new tab, a PWA relaunch
 * onto a reader URL) `router.back()` is a no-op, and reader routes have no app
 * chrome and no swipe-back — the user was trapped. A reader URL restored by a
 * nav tab also has an unrelated section as its previous history entry, so a
 * bare back flew out of the section (FE-T18).
 *
 * Every exit (the ✕ control, Escape, ArrowUp, the swipe-up gesture, the "all
 * images hidden" path and the pre-Reader fallback screen) must resolve through
 * `smartBack(router, backHref)`. `backHref` is required on both components, so
 * a reader route that forgets it fails the type-check instead of silently
 * falling back to an unrelated section.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import Reader from '@/components/Reader'
import { ReaderFallbackScreen } from '@/components/Reader/ReaderFallbackScreen'
import { markTabRestore } from '@/lib/navMemory'
import type { GalleryImage } from '@/lib/types'

const router = vi.hoisted(() => ({
  back: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => router,
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(''),
  usePathname: () => '/reader/pixiv/9',
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

vi.mock('@/lib/api', () => ({
  api: {
    library: {
      saveProgress: vi.fn().mockResolvedValue(undefined),
      deleteImage: vi.fn().mockResolvedValue(undefined),
      favoriteImage: vi.fn().mockResolvedValue(undefined),
      unfavoriteImage: vi.fn().mockResolvedValue(undefined),
      getProgress: vi.fn().mockResolvedValue(null),
    },
  },
}))

vi.mock('@/components/AppImage', () => ({
  AppImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

class AutoFireResizeObserver {
  private callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  observe(target: Element) {
    const rect = { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON() {} }
    this.callback(
      [{ target, contentRect: rect } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    )
  }
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal('ResizeObserver', AutoFireResizeObserver)
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 600 })
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 800 })
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({ width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON() {} }) as DOMRect
})

function makeGalleryImages(count: number): GalleryImage[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    gallery_id: 1,
    page_num: i + 1,
    filename: `${i + 1}.jpg`,
    width: 800,
    height: 1200,
    file_path: `/data/test/${i + 1}.jpg`,
    thumb_path: `/data/test/thumbs/${i + 1}.jpg`,
    file_size: 1000,
    file_hash: `hash${i + 1}`,
    media_type: 'image' as const,
    duration: null,
  }))
}

let historyLength = 1
function setHistoryLength(length: number) {
  historyLength = length
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  historyLength = 1
  Object.defineProperty(window.history, 'length', {
    configurable: true,
    get: () => historyLength,
  })
})

afterEach(() => {
  // Drop the instance override so other tests see jsdom's own getter.
  delete (window.history as unknown as { length?: number }).length
})

function renderReader(props: { backHref: string; images?: GalleryImage[]; onHideImage?: (page: number) => Promise<void> }) {
  const images = props.images ?? makeGalleryImages(5)
  return render(
    <Reader
      source="local"
      sourceId="1"
      downloadStatus="complete"
      images={images}
      totalPages={images.length}
      backHref={props.backHref}
      onHideImage={props.onHideImage}
    />,
  )
}

function swipeUp(el: Element) {
  fireEvent.touchStart(el, { touches: [{ clientX: 100, clientY: 500 }] })
  fireEvent.touchEnd(el, { changedTouches: [{ clientX: 100, clientY: 300 }] })
}

type Exit = { name: string; trigger: () => void }

const exits: Exit[] = [
  {
    name: 'the close control',
    trigger: () => fireEvent.click(screen.getByTitle('reader.goBack')),
  },
  {
    name: 'the Escape key',
    trigger: () => fireEvent.keyDown(window, { key: 'Escape' }),
  },
  {
    name: 'the ArrowUp key',
    trigger: () => fireEvent.keyDown(window, { key: 'ArrowUp' }),
  },
  {
    name: 'the swipe-up gesture',
    trigger: () => {
      const container = document.querySelector('.reader-container')
      if (!container) throw new Error('reader container missing')
      swipeUp(container)
    },
  },
]

describe('Reader exits when history has nothing to go back to', () => {
  it.each(exits)('$name goes to backHref instead of a no-op router.back()', ({ trigger }) => {
    setHistoryLength(1)
    renderReader({ backHref: '/pixiv/illust/9' })

    trigger()

    expect(router.push).toHaveBeenCalledTimes(1)
    expect(router.push).toHaveBeenCalledWith('/pixiv/illust/9')
    expect(router.back).not.toHaveBeenCalled()
  })

  it('leaves the reader through backHref after the last visible image is hidden', async () => {
    setHistoryLength(1)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onHideImage = vi.fn().mockResolvedValue(undefined)
    renderReader({ backHref: '/pixiv/illust/9', images: makeGalleryImages(1), onHideImage })

    const img = document.querySelector('.reader-container img')
    if (!img) throw new Error('page image missing')
    fireEvent.contextMenu(img, { clientX: 20, clientY: 20 })
    const hide = await screen.findByText('reader.hideImage')
    const item = hide.closest('button')
    if (!item) throw new Error('hide menu item missing')
    fireEvent.pointerDown(item)
    await act(async () => {
      fireEvent.click(item)
    })

    await waitFor(() => expect(onHideImage).toHaveBeenCalledWith(1))
    await waitFor(() => expect(router.push).toHaveBeenCalledWith('/pixiv/illust/9'))
    expect(router.back).not.toHaveBeenCalled()
    confirm.mockRestore()
  })
})

describe('Reader exits when there is history to walk back through', () => {
  it.each(exits)('$name still uses router.back()', ({ trigger }) => {
    setHistoryLength(4)
    renderReader({ backHref: '/pixiv/illust/9' })

    trigger()

    expect(router.back).toHaveBeenCalledTimes(1)
    expect(router.push).not.toHaveBeenCalled()
    expect(router.replace).not.toHaveBeenCalled()
  })
})

describe('Reader exit on a tab-restored reader URL', () => {
  it('climbs by replacing with backHref instead of history-backing out of the section', () => {
    setHistoryLength(6)
    markTabRestore(window.location.pathname + window.location.search)
    renderReader({ backHref: '/pixiv/illust/9' })

    fireEvent.keyDown(window, { key: 'Escape' })

    expect(router.replace).toHaveBeenCalledWith('/pixiv/illust/9')
    expect(router.back).not.toHaveBeenCalled()
  })
})

describe('ReaderFallbackScreen exit', () => {
  it('goes to backHref when history has nothing to go back to', () => {
    setHistoryLength(1)
    render(
      <ReaderFallbackScreen backHref="/e-hentai/123/abc">
        <p>waiting</p>
      </ReaderFallbackScreen>,
    )

    fireEvent.click(screen.getByTitle('reader.goBack'))

    expect(router.push).toHaveBeenCalledWith('/e-hentai/123/abc')
    expect(router.back).not.toHaveBeenCalled()
  })

  it('walks history back when there is somewhere to go', () => {
    setHistoryLength(3)
    render(
      <ReaderFallbackScreen backHref="/e-hentai/123/abc">
        <p>waiting</p>
      </ReaderFallbackScreen>,
    )

    fireEvent.click(screen.getByTitle('reader.goBack'))

    expect(router.back).toHaveBeenCalledTimes(1)
    expect(router.push).not.toHaveBeenCalled()
  })
})

describe('a mount without backHref', () => {
  // Checked by `npm run type-check`, not at runtime: each `@ts-expect-error`
  // turns into an "unused directive" error if backHref becomes optional again,
  // which is what let a reader route silently fall back to /library.
  it('does not type-check for Reader or ReaderFallbackScreen', () => {
    const mounts = [
      // @ts-expect-error backHref is required
      <Reader key="reader" source="local" sourceId="1" downloadStatus="complete" images={[]} totalPages={0} />,
      // @ts-expect-error backHref is required
      <ReaderFallbackScreen key="fallback">
        <p>waiting</p>
      </ReaderFallbackScreen>,
    ]

    expect(mounts.map((mount) => 'backHref' in mount.props)).toEqual([false, false])
  })
})
