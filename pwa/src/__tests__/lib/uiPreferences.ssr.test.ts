// @vitest-environment node

import { describe, expect, it } from 'vitest'

import { loadLocalDisplayPreferences } from '@/lib/uiPreferences'

describe('loadLocalDisplayPreferences during server rendering', () => {
  it('returns defaults when localStorage is unavailable', () => {
    expect(loadLocalDisplayPreferences()).toEqual({
      gallery_grid_density: 'comfortable',
      gallery_grid_columns: 0,
      font_scale: 1,
    })
  })
})
