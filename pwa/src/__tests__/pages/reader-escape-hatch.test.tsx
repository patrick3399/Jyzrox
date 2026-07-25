import { beforeEach, describe, expect, it, vi } from 'vitest'
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
 * Each state must carry its own escape hatch, and it must call router.back().
 */

const back = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({ back, push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ source: 'ehentai', sourceId: '123' }),
  useSearchParams: () => new URLSearchParams(''),
}))

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: true }),
  useWsJobs: () => ({ lastJobUpdate: null }),
}))

vi.mock('@/components/Reader', () => ({
  default: () => <div data-testid="reader" />,
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

describe('reader escape hatch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.library.getProgress.mockResolvedValue(null)
    mocked.history.record.mockResolvedValue(undefined)
  })

  it('offers a way back when the gallery fails to load', async () => {
    mocked.library.getGallery.mockRejectedValue(new Error('boom'))
    mocked.library.getImages.mockRejectedValue(new Error('boom'))

    render(<ReaderPage />)

    const backButton = await screen.findByTitle('reader.goBack')
    fireEvent.click(backButton)
    expect(back).toHaveBeenCalledTimes(1)
  })

  it('offers a way back while the gallery is still loading', async () => {
    // Never resolves: the component sits at `!data` for the whole test.
    mocked.library.getGallery.mockReturnValue(new Promise(() => {}))
    mocked.library.getImages.mockReturnValue(new Promise(() => {}))

    render(<ReaderPage />)

    const backButton = await screen.findByTitle('reader.goBack')
    expect(screen.getByText('reader.loadingGallery')).toBeInTheDocument()
    fireEvent.click(backButton)
    expect(back).toHaveBeenCalledTimes(1)
  })

  it('offers a way back while waiting for the first page of a live download', async () => {
    // The longest-lived of the three: this state persists for as long as the
    // download takes to import its first page.
    mocked.library.getGallery.mockResolvedValue(gallery('downloading'))
    mocked.library.getImages.mockResolvedValue({ images: [], favorited_image_ids: [] })

    render(<ReaderPage />)

    await waitFor(() => expect(screen.getByText('reader.downloadingWait')).toBeInTheDocument())
    fireEvent.click(screen.getByTitle('reader.goBack'))
    expect(back).toHaveBeenCalledTimes(1)
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
})
