import { describe, expect, it } from 'vitest'
import { CATEGORY_PALETTE, resolveCategoryColors } from '@/lib/categoryPalette'
import type { GalleryCategoryDef } from '@/lib/types'

const defs: GalleryCategoryDef[] = [
  { id: 1, name: 'Novel', color: 'teal', sort_order: 11, is_builtin: false, gallery_count: 0 },
]

describe('resolveCategoryColors', () => {
  it('uses the registry colour for a custom category, ignoring case', () => {
    expect(resolveCategoryColors('novel', defs)).toBe(CATEGORY_PALETTE.teal)
  })

  it('falls back to the built-in colour when the registry has not loaded', () => {
    expect(resolveCategoryColors('Cosplay')).toBe(CATEGORY_PALETTE.red)
    expect(resolveCategoryColors('Artist CG')).toBe(CATEGORY_PALETTE.yellow)
  })

  it('renders unknown and empty categories grey', () => {
    expect(resolveCategoryColors('illust', defs)).toBe(CATEGORY_PALETTE.gray)
    expect(resolveCategoryColors('', defs)).toBe(CATEGORY_PALETTE.gray)
    expect(resolveCategoryColors(null, defs)).toBe(CATEGORY_PALETTE.gray)
  })

  it('treats a registry colour key missing from the palette as grey', () => {
    const odd = [{ ...defs[0], color: 'chartreuse' }]
    expect(resolveCategoryColors('Novel', odd)).toBe(CATEGORY_PALETTE.gray)
  })
})
