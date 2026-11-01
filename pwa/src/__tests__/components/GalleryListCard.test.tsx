/**
 * GalleryListCard — the Library's list view runs on fixed rows, so the card's
 * height may not depend on its content. It used to grow with the title and up
 * to three rows of tags, to about 191px in a 150px row, and covered the next card.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Gallery } from '@/lib/types'
import { GalleryListCard } from '@/components/GalleryListCard'
import { estimateLibraryListRowHeight } from '@/lib/gridRowHeight'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const TAGS = Array.from({ length: 14 }, (_, i) => `female:a-rather-long-tag-name-${i}`)

function gallery(overrides: Partial<Gallery> = {}): Gallery {
  return {
    id: 1,
    source: 'ehentai',
    source_id: '123',
    title: 'Gallery',
    title_jpn: 'ギャラリー',
    category: 'Manga',
    language: 'English',
    pages: 10,
    posted_at: null,
    added_at: '2026-07-18T00:00:00Z',
    tags_array: TAGS,
    rating: 0,
    favorited: false,
    my_rating: null,
    is_favorited: false,
    in_reading_list: false,
    uploader: '',
    artist_id: null,
    download_status: 'complete',
    import_mode: 'copy',
    ...overrides,
  } as Gallery
}

describe('GalleryListCard fixed height', () => {
  it('sets an explicit height that matches the row estimate when the tags would otherwise wrap', () => {
    render(<GalleryListCard gallery={gallery()} onClick={() => {}} />)

    const classes = screen.getByRole('button').className
    const height = classes.match(/h-\[calc\(([\d.]+)rem\+(\d+)px\)\]/)
    expect(height, 'card has no calc() height class').not.toBeNull()

    // jsdom has no layout, so compare the class against the row estimate directly.
    const cardHeight = Number(height?.[1]) * 16 + Number(height?.[2])
    const row = estimateLibraryListRowHeight()
    expect(row).toBeGreaterThanOrEqual(cardHeight)
    expect(row - cardHeight).toBeLessThan(1)
  })

  it('limits a long tag list to four half-width chips so they cannot reach a third row', () => {
    render(<GalleryListCard gallery={gallery()} onClick={() => {}} />)

    const chips = screen.getAllByText(/^female:/)
    expect(chips).toHaveLength(4)
    for (const chip of chips) {
      expect(chip.className).toContain('max-w-[min(120px,calc(50%-0.125rem))]')
    }
  })

  it('counts every tag it does not show in the overflow badge', () => {
    render(<GalleryListCard gallery={gallery()} onClick={() => {}} />)

    expect(screen.getByText('+10')).toBeInTheDocument()
  })

  it('keeps the meta row on one line while a download badge is showing', () => {
    render(<GalleryListCard gallery={gallery({ download_status: 'downloading' })} onClick={() => {}} />)

    const pages = screen.getByText('10p')
    expect(pages.parentElement).not.toHaveClass('flex-wrap')
    // Stars, badge and page count together overflow a phone-width column.
    expect(screen.getByText('Downloading...')).toBeInTheDocument()
    expect(pages.parentElement?.textContent).not.toContain('☆')
  })
})
