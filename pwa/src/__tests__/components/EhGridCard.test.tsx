/**
 * E-Hentai grid card rating — overflow on narrow phones.
 *
 * At 3 columns a phone card has ~93–98px inside its padding. Five 16px stars
 * plus the ♥ (local favourite) and ↓ (downloaded) marks on the same row need
 * ~95–110px, so the row ran past the card edge and the marks were clipped.
 * The grid card now shows one compact "★4.5" instead of five stars.
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GridCard } from '@/components/eh/EhBrowseCards'
import type { EhGallery } from '@/lib/types'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, params?: Record<string, string>) =>
    params ? `${key}:${Object.values(params).join(',')}` : key,
}))

const gallery = {
  gid: 12345,
  token: 'abcdef',
  title: 'Test Gallery',
  title_jpn: '',
  category: 'Doujinshi',
  pages: 30,
  rating: 4.43,
  tags: [],
  thumb: 'https://ehgt.org/thumb/001.jpg',
  uploader: 'tester',
  posted_at: 1700000000,
  expunged: false,
} as unknown as EhGallery

describe('EH GridCard rating', () => {
  it('test_grid_card_with_favourite_and_download_marks_shows_one_compact_star_instead_of_five', () => {
    const { container } = render(
      <GridCard
        gallery={gallery}
        status={{ is_local_favorite: true, downloaded: true } as never}
        onClick={vi.fn()}
        onUploaderClick={vi.fn()}
      />,
    )

    expect(container.textContent).not.toContain('☆')
    expect(container.textContent?.match(/★/g)).toHaveLength(1)
    expect(screen.getByText('★4.4')).toBeInTheDocument()
    expect(screen.getByText('♥')).toBeInTheDocument()
    expect(screen.getByText('↓')).toBeInTheDocument()
  })

  it('test_grid_card_rating_keeps_one_decimal_instead_of_rounding_to_whole_stars', () => {
    render(
      <GridCard gallery={{ ...gallery, rating: 3.5 }} onClick={vi.fn()} onUploaderClick={vi.fn()} />,
    )

    expect(screen.getByText('★3.5')).toBeInTheDocument()
  })

  it('test_grid_card_without_a_rating_shows_no_star', () => {
    const { container } = render(
      <GridCard gallery={{ ...gallery, rating: 0 }} onClick={vi.fn()} onUploaderClick={vi.fn()} />,
    )

    expect(container.textContent).not.toMatch(/[★☆]/)
  })
})
