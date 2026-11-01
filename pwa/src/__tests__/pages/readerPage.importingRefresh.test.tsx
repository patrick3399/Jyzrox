/**
 * Reader page — refresh while a link gallery is `importing`.
 *
 * The reader keeps its data in useState (no SWR), so WsInvalidationBridge
 * cannot refresh it. It must refetch itself on this gallery's gallery.* /
 * import.* events, and treat `importing` like `downloading` in the FE-T14
 * checks (waiting screen, fallback poll, job-update refresh).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act } from '@testing-library/react'
import type { Gallery, GalleryImage, WsMessage } from '@/lib/types'

const h = vi.hoisted(() => ({
  getGallery: vi.fn(),
  getImages: vi.fn(),
  lastEvent: null as WsMessage | null,
  connected: true,
  lastJobUpdate: null as unknown,
  readerProps: [] as Array<Record<string, unknown>>,
}))

vi.mock('next/navigation', () => ({
  useParams: () => ({ source: 'local', sourceId: 'folder' }),
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/api', () => ({
  api: {
    library: {
      getGallery: h.getGallery,
      getImages: h.getImages,
      getProgress: vi.fn().mockResolvedValue(null),
    },
    history: { record: vi.fn().mockResolvedValue(undefined) },
  },
}))
vi.mock('@/lib/ws', () => ({
  useWsConnection: () => ({ connected: h.connected }),
  useWsJobs: () => ({ lastJobUpdate: h.lastJobUpdate }),
  useWsEvents: () => ({ lastEvent: h.lastEvent }),
}))
vi.mock('swr', () => ({ mutate: vi.fn() }))
vi.mock('@/components/Reader', () => ({
  default: (props: Record<string, unknown>) => {
    h.readerProps.push(props)
    return <div data-testid="reader" />
  },
}))
vi.mock('@/components/ErrorBoundary', () => ({
  ErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import ReaderPage from '@/app/reader/[source]/[sourceId]/page'

function gallery(over: Partial<Gallery> = {}): Gallery {
  return {
    id: 7,
    title: 'Folder',
    source: 'local',
    source_id: 'folder',
    pages: 2,
    download_status: 'importing',
    cover_thumb: null,
    ...over,
  } as Gallery
}

function pendingImage(id: number, page: number): GalleryImage {
  return {
    id,
    gallery_id: 7,
    page_num: page,
    file_path: `/media/libraries/folder/${page}.jpg`,
    thumb_path: null,
    file_hash: null,
    media_type: 'image',
    visibility: 'active',
    pending: true,
  } as GalleryImage
}

function galleryEvent(eventType: string, galleryId: number): WsMessage {
  return {
    type: 'event',
    event: { event_type: eventType, resource_type: 'gallery', resource_id: galleryId, data: {} },
  } as WsMessage
}

const images = [pendingImage(1, 1), pendingImage(2, 2)]

describe('reader page importing refresh', () => {
  beforeEach(() => {
    h.getGallery.mockReset().mockResolvedValue(gallery())
    h.getImages.mockReset().mockResolvedValue({ images, favorited_image_ids: [] })
    h.lastEvent = null
    h.connected = true
    h.lastJobUpdate = null
    h.readerProps.length = 0
    localStorage.setItem('history_enabled', 'false')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('refetches gallery and images when gallery.updated arrives for this gallery', async () => {
    const { rerender } = render(<ReaderPage />)
    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())
    expect(h.getImages).toHaveBeenCalledTimes(1)

    h.getGallery.mockResolvedValue(gallery({ download_status: 'complete' }))
    h.lastEvent = galleryEvent('gallery.updated', 7)
    rerender(<ReaderPage />)

    await waitFor(() => expect(h.getImages).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(h.readerProps[h.readerProps.length - 1]?.downloadStatus).toBe('complete'),
    )
  })

  it('does not refetch for a gallery.updated event of another gallery', async () => {
    const { rerender } = render(<ReaderPage />)
    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())

    h.lastEvent = galleryEvent('gallery.updated', 99)
    rerender(<ReaderPage />)
    await act(async () => {
      await Promise.resolve()
    })

    expect(h.getImages).toHaveBeenCalledTimes(1)
  })

  it('shows the waiting screen, not an empty reader, for an importing gallery with no images yet', async () => {
    h.getImages.mockResolvedValue({ images: [], favorited_image_ids: [] })
    render(<ReaderPage />)

    await waitFor(() =>
      expect(screen.getByText('Downloading — waiting for first image...')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('reader')).not.toBeInTheDocument()
  })

  it('polls while importing and the WebSocket is down', async () => {
    h.connected = false
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<ReaderPage />)
    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())
    expect(h.getImages).toHaveBeenCalledTimes(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100)
    })

    expect(h.getImages.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('does not poll a complete gallery when the WebSocket is down', async () => {
    h.connected = false
    h.getGallery.mockResolvedValue(gallery({ download_status: 'complete' }))
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<ReaderPage />)
    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())

    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000)
    })

    expect(h.getImages).toHaveBeenCalledTimes(1)
  })

  it('refetches on a job update whose progress belongs to this importing gallery', async () => {
    const { rerender } = render(<ReaderPage />)
    await waitFor(() => expect(screen.getByTestId('reader')).toBeInTheDocument())
    expect(h.getImages).toHaveBeenCalledTimes(1)

    h.lastJobUpdate = { job_id: 'j', progress: { gallery_id: 7 } }
    rerender(<ReaderPage />)

    await waitFor(() => expect(h.getImages).toHaveBeenCalledTimes(2))
  })
})
