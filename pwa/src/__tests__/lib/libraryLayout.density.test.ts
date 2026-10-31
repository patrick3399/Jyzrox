import { describe, expect, it } from 'vitest'
import { getLibraryGridColumns, resolveLibraryGrid } from '@/lib/libraryLayout'

const BREAKPOINTS = ['base', 'sm', 'md', 'lg', 'xl', 'xxl'] as const

describe('auto columns per density', () => {
  it.each(BREAKPOINTS.filter((bp) => bp !== 'xl'))(
    'test_auto_columns_are_distinct_for_all_three_densities_at_%s',
    (breakpoint) => {
      const spacious = getLibraryGridColumns('spacious')[breakpoint]
      const comfortable = getLibraryGridColumns('comfortable')[breakpoint]
      const compact = getLibraryGridColumns('compact')[breakpoint]
      // Strictly increasing, so no two densities collapse to the same grid.
      expect(spacious).toBeLessThan(comfortable!)
      expect(comfortable).toBeLessThan(compact!)
    },
  )

  it('test_comfortable_phone_and_xxl_columns_differ_from_the_neighbouring_densities', () => {
    // Previously comfortable base was 4 (== compact) and xxl was 12 (== compact).
    expect(getLibraryGridColumns('spacious').base).toBe(2)
    expect(getLibraryGridColumns('comfortable').base).toBe(3)
    expect(getLibraryGridColumns('compact').base).toBe(4)
    expect(getLibraryGridColumns('spacious').xxl).toBe(7)
    expect(getLibraryGridColumns('comfortable').xxl).toBe(10)
    expect(getLibraryGridColumns('compact').xxl).toBe(12)
  })

  it('test_comfortable_and_compact_share_xl_only_where_documented', () => {
    // xl is the one breakpoint where comfortable and compact may meet (10 vs 12 today).
    expect(getLibraryGridColumns('comfortable').xl).toBeLessThanOrEqual(
      getLibraryGridColumns('compact').xl!,
    )
  })
})

describe('resolveLibraryGrid', () => {
  const settings = { gallery_grid_density: 'comfortable', gallery_grid_columns: 5 } as const

  it('test_override_ignores_a_fixed_settings_column_count', () => {
    const resolved = resolveLibraryGrid(settings, 'compact')

    expect(resolved.density).toBe('compact')
    // Auto columns of the overriding density, not the fixed 5-column clamp.
    expect(resolved.columns).toEqual(getLibraryGridColumns('compact'))
    expect(resolved.columns).not.toEqual(getLibraryGridColumns('compact', 5))
  })

  it('test_without_override_uses_settings_density_and_fixed_columns_exactly', () => {
    const resolved = resolveLibraryGrid(settings, null)

    expect(resolved.density).toBe('comfortable')
    expect(resolved.columns).toEqual(getLibraryGridColumns('comfortable', 5))
  })

  it('test_without_override_and_auto_settings_columns_uses_density_auto_table', () => {
    const resolved = resolveLibraryGrid(
      { gallery_grid_density: 'spacious', gallery_grid_columns: 0 },
      null,
    )

    expect(resolved).toEqual({ density: 'spacious', columns: getLibraryGridColumns('spacious') })
  })
})
