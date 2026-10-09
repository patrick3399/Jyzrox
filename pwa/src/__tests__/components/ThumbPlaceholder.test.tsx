import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThumbPlaceholder } from '@/components/library/ThumbPlaceholder'
import { CATEGORY_PALETTE } from '@/lib/categoryPalette'
import type { GalleryCategoryDef } from '@/lib/types'

describe('ThumbPlaceholder', () => {
  it('paints the category gradient instead of a flat fill when a page has no thumbnail', () => {
    render(<ThumbPlaceholder category="Cosplay">12</ThumbPlaceholder>)
    const el = screen.getByText('12')
    expect(el.className).toContain('bg-gradient-to-b')
    expect(el.className).toContain(CATEGORY_PALETTE.red.bg)
    expect(el.className).not.toContain('bg-vault-input')
  })

  it('falls back to the gray gradient for a gallery without a category', () => {
    render(<ThumbPlaceholder category="">3</ThumbPlaceholder>)
    expect(screen.getByText('3').className).toContain(CATEGORY_PALETTE.gray.bg)
  })

  it('uses the registry colour of a custom category', () => {
    const categories = [{ name: 'Photobook', color: 'teal' }] as GalleryCategoryDef[]
    render(
      <ThumbPlaceholder category="photobook" categories={categories}>
        1
      </ThumbPlaceholder>,
    )
    expect(screen.getByText('1').className).toContain(CATEGORY_PALETTE.teal.bg)
  })

  it('keeps the layout classes its caller passes', () => {
    render(
      <ThumbPlaceholder category="" className="w-40 h-56 rounded">
        cover
      </ThumbPlaceholder>,
    )
    expect(screen.getByText('cover').className).toContain('w-40 h-56 rounded')
  })
})
