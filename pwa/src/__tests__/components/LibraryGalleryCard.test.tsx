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

describe('LibraryGalleryCard category colours', () => {
  it('colours the badge from the registry for a custom category', () => {
    const { container } = render(
      <LibraryGalleryCard
        gallery={{ ...gallery, category: 'Novel' }}
        categories={[
          { id: 1, name: 'Novel', color: 'teal', sort_order: 11, is_builtin: false, gallery_count: 1 },
        ]}
        onClick={() => {}}
      />,
    )
    // Library cards without a cover render the category gradient placeholder.
    expect(container.innerHTML).toContain('from-teal-950')
  })

  it('keeps the built-in colour when no registry data is available', () => {
    const { container } = render(
      <LibraryGalleryCard
        gallery={{ ...gallery, category: 'Manga' }}
        onClick={() => {}}
      />,
    )
    expect(container.innerHTML).toContain('from-orange-950')
  })

  it('renders an unregistered category grey', () => {
    const { container } = render(
      <LibraryGalleryCard
        gallery={{ ...gallery, category: 'illust' }}
        onClick={() => {}}
      />,
    )
    expect(container.innerHTML).toContain('from-gray-900')
  })
})

describe('LibraryGalleryCard info block', () => {
  it('test_unrated_card_renders_no_rating_stars_and_keeps_the_page_count_visible', () => {
    const { container } = render(<LibraryGalleryCard gallery={gallery} onClick={() => {}} />)

    // Five empty stars overflowed a ~60px phone card, clipped the fifth star and
    // pushed the page count out of the card entirely.
    expect(container.textContent).not.toMatch(/[★☆]/)
    expect(screen.getByText('10p')).toBeInTheDocument()
  })

  it('test_rated_card_shows_one_compact_rating_instead_of_five_stars', () => {
    const { container } = render(
      <LibraryGalleryCard gallery={{ ...gallery, my_rating: 4 }} onClick={() => {}} />,
    )

    expect(container.textContent).not.toContain('☆')
    expect(container.textContent?.match(/★/g)).toHaveLength(1)
    expect(screen.getByText('★4')).toBeInTheDocument()
    expect(screen.getByText('10p')).toBeInTheDocument()
  })

  it('test_card_without_my_rating_falls_back_to_the_rounded_source_rating', () => {
    render(<LibraryGalleryCard gallery={{ ...gallery, rating: 3.6 }} onClick={() => {}} />)

    expect(screen.getByText('★4')).toBeInTheDocument()
  })

  it('test_card_title_is_a_single_truncated_line_so_the_fixed_row_has_no_empty_second_line', () => {
    render(<LibraryGalleryCard gallery={gallery} onClick={() => {}} />)

    const title = screen.getByRole('heading', { name: 'Gallery' })
    expect(title.className).toMatch(/\btruncate\b/)
    expect(title.className).not.toMatch(/line-clamp/)
  })
})
