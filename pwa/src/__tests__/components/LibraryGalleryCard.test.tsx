import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Gallery } from '@/lib/types'
import { LibraryGalleryCard } from '@/components/GalleryCard'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/lib/i18n', () => ({
  t: (key: string) => key,
}))

const gallery: Gallery = {
  id: 1,
  source: 'local',
  source_id: 'gallery',
  title: 'Gallery',
  title_jpn: '',
  category: 'Manga',
  language: 'English',
  pages: 10,
  posted_at: null,
  added_at: '2026-07-18T00:00:00Z',
  tags_array: [],
  rating: 0,
  favorited: false,
  my_rating: null,
  is_favorited: false,
  in_reading_list: false,
  uploader: '',
  artist_id: null,
  download_status: 'complete',
  import_mode: 'copy',
}

describe('LibraryGalleryCard media loading', () => {
  it('does not guess or request a preview.webm when the card is hovered', () => {
    const { container } = render(
      <LibraryGalleryCard
        gallery={gallery}
        thumbUrl="/media/thumbs/aa/bb/hash/thumb_160.webp"
        onClick={() => {}}
      />,
    )

    fireEvent.mouseEnter(screen.getByRole('button'))

    expect(container.querySelector('video')).toBeNull()
    expect(container.innerHTML).not.toContain('preview.webm')
    expect(screen.getByRole('img', { name: 'Gallery' })).toHaveAttribute(
      'src',
      '/media/thumbs/aa/bb/hash/thumb_160.webp',
    )
  })
})
