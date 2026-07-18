/**
 * Regression test for the animated hover preview on LibraryGalleryCard.
 *
 * The card mounts a <video> (preview.webm) when hovered. Wiring the pointer
 * directly to `setHovered(true)` on mouseEnter meant that sweeping the pointer
 * across a grid kicked off a webm fetch + decode for every card the pointer
 * merely passed over. The preview must now wait for the pointer to rest on a
 * card past HOVER_PREVIEW_DELAY_MS before the <video> mounts, and a pointer
 * that leaves before the delay must never trigger a load.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, act } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

import { LibraryGalleryCard } from '@/components/GalleryCard'
import type { Gallery } from '@/lib/types'

// Contract: must match HOVER_PREVIEW_DELAY_MS in GalleryCard.
const HOVER_PREVIEW_DELAY_MS = 180

const gallery: Gallery = {
  id: 1,
  source: 'local',
  source_id: 'abc',
  title: 'Sample',
  title_jpn: '',
  category: 'Manga',
  language: 'en',
  pages: 12,
  posted_at: null,
  added_at: '2026-01-01',
  rating: 0,
  favorited: false,
  is_favorited: false,
  my_rating: null,
  in_reading_list: false,
  uploader: '',
  artist_id: null,
  download_status: 'complete',
  import_mode: null,
  tags_array: [],
}

// thumbUrl must end in thumb_160.webp so the card derives a preview.webm URL.
const thumbUrl = '/media/thumbs/aa/bb/hash/thumb_160.webp'

describe('LibraryGalleryCard animated preview loads only after a hover delay', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('does not mount the <video> immediately on mouseEnter', () => {
    const { container } = render(<LibraryGalleryCard gallery={gallery} thumbUrl={thumbUrl} />)
    fireEvent.mouseEnter(container.querySelector('article')!)
    expect(container.querySelector('video')).toBeNull()
  })

  it('mounts the <video> once the pointer rests past the delay', () => {
    const { container } = render(<LibraryGalleryCard gallery={gallery} thumbUrl={thumbUrl} />)
    fireEvent.mouseEnter(container.querySelector('article')!)
    act(() => {
      vi.advanceTimersByTime(HOVER_PREVIEW_DELAY_MS)
    })
    const video = container.querySelector('video')
    expect(video).not.toBeNull()
    expect(video).toHaveAttribute('src', '/media/thumbs/aa/bb/hash/preview.webm')
  })

  it('cancels the pending load when the pointer leaves before the delay', () => {
    const { container } = render(<LibraryGalleryCard gallery={gallery} thumbUrl={thumbUrl} />)
    const article = container.querySelector('article')!
    fireEvent.mouseEnter(article)
    act(() => {
      vi.advanceTimersByTime(HOVER_PREVIEW_DELAY_MS - 1)
    })
    fireEvent.mouseLeave(article)
    act(() => {
      vi.advanceTimersByTime(HOVER_PREVIEW_DELAY_MS)
    })
    expect(container.querySelector('video')).toBeNull()
  })
})
