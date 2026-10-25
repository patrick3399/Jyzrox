import { Suspense } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import { api } from '@/lib/api'
import FavoriteReaderPage from '@/app/reader/favorites/page'
import ArtistReaderPage from '@/app/reader/artist/[artistId]/page'
import PixivReaderPage from '@/app/reader/pixiv/[id]/page'
import EhReaderPage from '@/app/e-hentai/read/[gid]/[token]/page'

/**
 * Regression: the favourites, artist, Pixiv and E-Hentai readers had the same
 * dead ends the gallery reader was fixed for.
 *
 * Their loading, error and empty states render before `<Reader />` mounts, and
 * the only back control lives inside Reader. The global edge-swipe-back is
 * disarmed on reader routes, so an installed PWA had nothing to press.
 *
 * The control must also work when history has nothing to go back to (shared
 * link, new tab, PWA relaunch): a bare `router.back()` is a no-op there, so it
 * resolves through `smartBack` to the page's own detail route instead.
 */

const back = vi.fn()
const push = vi.fn()
const replace = vi.fn()
const swr = vi.hoisted(() => ({ data: undefined as unknown, error: undefined as unknown }))
const route = vi.hoisted(() => ({ gid: '123' }))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back, push, replace }),
  useParams: () => ({ artistId: 'ehentai%3Asomeone', gid: route.gid, token: 'abc' }),
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string) => key,
}))

vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => undefined }))

vi.mock('@/components/Reader', () => ({
  default: () => <div data-testid="reader" />,
}))

vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/hooks/useGalleries', () => ({
  useEhGallery: () => ({ data: undefined, error: undefined, isLoading: true }),
  useEhGalleryImagesPaginated: () => ({
    tokenMap: {},
    previewMap: {},
    error: undefined,
    isLoading: true,
    onPageChange: vi.fn(),
    fetchUpTo: vi.fn(),
  }),
}))

vi.mock('swr', () => ({
  default: () => ({ data: swr.data, error: swr.error, isLoading: false, mutate: vi.fn() }),
  mutate: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  api: {
    library: { browseImages: vi.fn(), getArtistImages: vi.fn(), deleteImage: vi.fn() },
    pixiv: { getIllustPages: vi.fn() },
  },
}))

const mocked = api as unknown as {
  library: { browseImages: ReturnType<typeof vi.fn>; getArtistImages: ReturnType<typeof vi.fn> }
}

const pending = () => new Promise(() => {})

let historyLength = 1

/** The escape hatch with nothing to history-back to must land on the fallback
 *  (a RegExp when the page has no valid id to build the exact route from). */
function expectWayBack(fallback: string | RegExp) {
  historyLength = 1
  fireEvent.click(screen.getByTitle('reader.goBack'))
  expect(push).toHaveBeenCalledTimes(1)
  if (typeof fallback === 'string') expect(push).toHaveBeenCalledWith(fallback)
  else expect(push.mock.calls[0][0]).toMatch(fallback)
  expect(back).not.toHaveBeenCalled()
}

/** Counterpart: with somewhere to go back to, the control walks history. */
function expectHistoryBack() {
  historyLength = 4
  fireEvent.click(screen.getByTitle('reader.goBack'))
  expect(back).toHaveBeenCalledTimes(1)
  expect(push).not.toHaveBeenCalled()
}

async function renderPixiv(id: string) {
  await act(async () => {
    render(
      <Suspense>
        <PixivReaderPage params={Promise.resolve({ id })} />
      </Suspense>,
    )
  })
}

describe('reader escape hatch on the other reader routes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    historyLength = 1
    Object.defineProperty(window.history, 'length', {
      configurable: true,
      get: () => historyLength,
    })
    swr.data = undefined
    swr.error = undefined
    route.gid = '123'
  })

  afterEach(() => {
    // Drop the instance override so other tests see jsdom's own getter.
    delete (window.history as unknown as { length?: number }).length
  })

  it('favourites reader offers a way back while the favourites are loading', async () => {
    mocked.library.browseImages.mockReturnValue(pending())

    render(<FavoriteReaderPage />)

    await screen.findByText('reader.loadingFavoriteImages')
    expectWayBack('/library')
  })

  it('favourites reader offers a way back when the favourites fail to load', async () => {
    mocked.library.browseImages.mockRejectedValue(new Error('boom'))

    render(<FavoriteReaderPage />)

    await screen.findByText('boom')
    expectWayBack('/library')
  })

  it('favourites reader offers a way back when there are no favourites', async () => {
    mocked.library.browseImages.mockResolvedValue({
      images: [],
      next_cursor: null,
      has_next: false,
      favorited_image_ids: [],
    })

    render(<FavoriteReaderPage />)

    await screen.findByText('reader.noFavoriteImages')
    expectWayBack('/library')
  })

  it('artist reader offers a way back while the artist images are loading', async () => {
    mocked.library.getArtistImages.mockReturnValue(pending())

    render(<ArtistReaderPage />)

    await screen.findByText('reader.loadingImages')
    expectWayBack('/library')
  })

  it('artist reader offers a way back when the artist images fail to load', async () => {
    mocked.library.getArtistImages.mockRejectedValue(new Error('boom'))

    render(<ArtistReaderPage />)

    await screen.findByText('boom')
    expectWayBack('/library')
  })

  it('pixiv reader offers a way back while the illustration is loading', async () => {
    await renderPixiv('123')

    screen.getByText('pixiv.loading')
    expectWayBack('/pixiv/illust/123')
  })

  it('pixiv reader offers a way back when the illustration fails to load', async () => {
    swr.error = new Error('boom')

    await renderPixiv('123')

    screen.getByText('boom')
    expectWayBack('/pixiv/illust/123')
  })

  it('pixiv reader offers a way back when the illustration id is not a number', async () => {
    await renderPixiv('nope')

    screen.getByText('common.invalidId')
    expectWayBack(/^\/pixiv/)
  })

  it('e-hentai reader offers a way back while the gallery metadata is loading', () => {
    render(<EhReaderPage />)

    screen.getByText('reader.loadingMetadata')
    expectWayBack('/e-hentai/123/abc')
  })

  it('e-hentai reader offers a way back when the gallery id is not a number', () => {
    route.gid = 'not-a-number'
    render(<EhReaderPage />)

    screen.getByText('common.invalidId')
    expectWayBack(/^\/e-hentai/)
  })

  it('pixiv reader walks history back when the stack has an entry to go back to', async () => {
    await renderPixiv('123')

    screen.getByText('pixiv.loading')
    expectHistoryBack()
  })

  it('e-hentai reader walks history back when the stack has an entry to go back to', () => {
    render(<EhReaderPage />)

    screen.getByText('reader.loadingMetadata')
    expectHistoryBack()
  })
})
