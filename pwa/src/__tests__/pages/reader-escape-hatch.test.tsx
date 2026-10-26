import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { api } from '@/lib/api'
import ReaderPage from '@/app/reader/[source]/[sourceId]/page'

/**
 * Regression: the reader's three pre-Reader states were dead ends.
 *
 * `error`, `!data` (loading) and "downloading with no pages yet" all render
 * their own full-screen div and return before `<Reader />` mounts — and the
 * only back control lives inside Reader. On a full-screen route with no app
 * chrome that leaves the user with nothing to press: the waiting state in
 * particular can persist for as long as a download takes (FE-T14), so this is
 * not a momentary flash.
 *
 * Each state must carry its own escape hatch, and it must work when history
 * has nothing to go back to (shared link, new tab, PWA relaunch): a bare
 * `router.back()` is a no-op there, so every exit — these and Reader's own —
 * resolves through `smartBack` to the gallery's library detail page.
 */

const back = vi.fn()
const push = vi.fn()
const replace = vi.fn()
const route = vi.hoisted(() => ({ source: 'ehentai', sourceId: '123' }))
const readerProps = vi.hoisted(() => ({ current: null as null | { backHref?: string } }))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back, push, replace }),
  useParams: () => route,
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: true }),
  useWsJobs: () => ({ lastJobUpdate: null }),
  useWsEvents: () => ({ lastEvent: null }),
}))

vi.mock('@/components/Reader', () => ({
  default: (props: { backHref?: string }) => {
    readerProps.current = props
    return <div data-testid="reader" />
  },
}))

vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/lib/api', () => ({
  api: {
    library: { getGallery: vi.fn(), getImages: vi.fn(), getProgress: vi.fn() },
    history: { record: vi.fn() },
  },
}))

const DETAIL_HREF = '/library/ehentai/123'

const gallery = (download_status: string) => ({
  id: 1,
  source: 'ehentai',
  source_id: '123',
  title: 'Gallery',
  pages: 10,
  download_status,
  cover_thumb: null,
})

const image = {
  id: 1,
  page_num: 1,
  file_path: '/media/cas/a.jpg',
  thumb_path: '/media/thumbs/a/thumb_160.webp',
  media_type: 'image',
  visibility: 'active',
}

const mocked = api as unknown as {
  library: {
    getGallery: ReturnType<typeof vi.fn>
    getImages: ReturnType<typeof vi.fn>
    getProgress: ReturnType<typeof vi.fn>
  }
  history: { record: ReturnType<typeof vi.fn> }
}

let historyLength = 1

/** With a one-entry history the control must land on the detail page. */
function expectWayBack(href = DETAIL_HREF) {
  historyLength = 1
  fireEvent.click(screen.getByTitle('reader.goBack'))
  expect(push).toHaveBeenCalledTimes(1)
  expect(push).toHaveBeenCalledWith(href)
  expect(back).not.toHaveBeenCalled()
}

describe('reader escape hatch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    route.source = 'ehentai'
    route.sourceId = '123'
    readerProps.current = null
    historyLength = 1
    Object.defineProperty(window.history, 'length', {
      configurable: true,
      get: () => historyLength,
    })
    mocked.library.getProgress.mockResolvedValue(null)
    mocked.history.record.mockResolvedValue(undefined)
  })

  afterEach(() => {
    delete (window.history as unknown as { length?: number }).length
  })

  it('offers a way back to the gallery when it fails to load with a one-entry history', async () => {
    mocked.library.getGallery.mockRejectedValue(new Error('boom'))
    mocked.library.getImages.mockRejectedValue(new Error('boom'))

    render(<ReaderPage />)

    await screen.findByText('boom')
    expectWayBack()
  })

  it('offers a way back to the gallery while it is still loading with a one-entry history', async () => {
    // Never resolves: the component sits at `!data` for the whole test.
    mocked.library.getGallery.mockReturnValue(new Promise(() => {}))
    mocked.library.getImages.mockReturnValue(new Promise(() => {}))

    render(<ReaderPage />)

    await screen.findByText('reader.loadingGallery')
    expectWayBack()
  })

  it('offers a way back to the gallery while waiting for the first page of a live download with a one-entry history', async () => {
    // The longest-lived of the three: this state persists for as long as the
    // download takes to import its first page.
    mocked.library.getGallery.mockResolvedValue(gallery('downloading'))
    mocked.library.getImages.mockResolvedValue({ images: [], favorited_image_ids: [] })

    render(<ReaderPage />)

    await waitFor(() => expect(screen.getByText('reader.downloadingWait')).toBeInTheDocument())
    expectWayBack()
  })

  it('walks history back when the stack has an entry to go back to', async () => {
    mocked.library.getGallery.mockReturnValue(new Promise(() => {}))
    mocked.library.getImages.mockReturnValue(new Promise(() => {}))

    render(<ReaderPage />)

    await screen.findByText('reader.loadingGallery')
    historyLength = 4
    fireEvent.click(screen.getByTitle('reader.goBack'))
    expect(back).toHaveBeenCalledTimes(1)
    expect(push).not.toHaveBeenCalled()
  })

  it('falls back to the library when the route has no gallery id', async () => {
    route.sourceId = ''

    render(<ReaderPage />)

    await screen.findByText('Invalid gallery source or ID.')
    expectWayBack('/library')
  })

  it('encodes an opaque collection id into the detail href of the /reader/gallery alias', async () => {
    // `/reader/gallery/pixiv/user%3A5` re-exports this page for author collections.
    route.source = 'pixiv'
    route.sourceId = 'user%3A5'
    mocked.library.getGallery.mockReturnValue(new Promise(() => {}))
    mocked.library.getImages.mockReturnValue(new Promise(() => {}))

    render(<ReaderPage />)

    await screen.findByText('reader.loadingGallery')
    expectWayBack('/library/pixiv/user%3A5')
  })

  it('does not add its own control once Reader takes over', async () => {
    // Reader owns the back affordance in the loaded state; a second one here
    // would sit on top of it.
    mocked.library.getGallery.mockResolvedValue(gallery('complete'))
    mocked.library.getImages.mockResolvedValue({ images: [image], favorited_image_ids: [] })

    render(<ReaderPage />)

    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())
    expect(screen.queryByTitle('reader.goBack')).not.toBeInTheDocument()
  })

  it("hands Reader the gallery's detail page as its exit instead of the /library default", async () => {
    mocked.library.getGallery.mockResolvedValue(gallery('complete'))
    mocked.library.getImages.mockResolvedValue({ images: [image], favorited_image_ids: [] })

    render(<ReaderPage />)

    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())
    expect(readerProps.current?.backHref).toBe(DETAIL_HREF)
  })
})
