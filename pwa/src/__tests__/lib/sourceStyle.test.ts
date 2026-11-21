/**
 * Guards: every site badge (library, artists, subscriptions) takes its colour
 * from one place; common sites never share a colour (the old hash put pixiv and
 * instagram both on cyan, local and facebook both on teal); unlisted sites
 * still get a stable palette colour; a missing source gets the neutral style.
 */

import { describe, it, expect, vi } from 'vitest'
import {
  SOURCE_COLOR_PALETTE,
  UNKNOWN_SOURCE_COLOR,
  sourceColorClass,
  sourceDisplayName,
} from '@/lib/sourceStyle'
import { getSourceStyle } from '@/lib/galleryUtils'
import { sourceLabel } from '@/components/subscriptions/sourceGrouping'

vi.mock('@/lib/i18n', () => ({ t: (key: string) => key }))

const COMMON_SITES = ['pixiv', 'twitter', 'ehentai', 'weibo', 'instagram', 'facebook', 'fanbox']

describe('sourceColorClass', () => {
  it('gives each common site its own colour, including pixiv vs instagram and local vs facebook', () => {
    const colours = [...COMMON_SITES, 'local'].map(sourceColorClass)
    expect(new Set(colours).size).toBe(colours.length)
    expect(sourceColorClass('pixiv')).not.toBe(sourceColorClass('instagram'))
    expect(sourceColorClass('local')).not.toBe(sourceColorClass('facebook'))
  })

  it('colours pixiv blue and both E-Hentai hosts alike', () => {
    expect(sourceColorClass('pixiv')).toContain('bg-blue-900/50')
    expect(sourceColorClass('exhentai')).toBe(sourceColorClass('ehentai'))
  })

  it('hashes an unlisted site into the palette, the same way every call', () => {
    const colour = sourceColorClass('danbooru')
    expect(SOURCE_COLOR_PALETTE).toContain(colour)
    expect(sourceColorClass('danbooru')).toBe(colour)
  })

  it('uses the neutral style when no source was detected', () => {
    expect(sourceColorClass(null)).toBe(UNKNOWN_SOURCE_COLOR)
    expect(sourceColorClass('')).toBe(UNKNOWN_SOURCE_COLOR)
  })

  it('gives a library gallery the same colour as a subscription of that site', () => {
    for (const site of COMMON_SITES) {
      expect(getSourceStyle({ source: site, import_mode: null }).className).toBe(
        sourceColorClass(site),
      )
    }
  })
})

describe('sourceDisplayName', () => {
  it('names listed sites and capitalises unlisted ones, the same in library and subscriptions', () => {
    expect(sourceDisplayName('ehentai')).toBe('E-Hentai')
    expect(sourceDisplayName('danbooru')).toBe('Danbooru')
    expect(getSourceStyle({ source: 'twitter', import_mode: null }).label).toBe('Twitter')
    expect(sourceLabel('twitter')).toBe('Twitter')
    expect(sourceLabel('danbooru')).toBe(
      getSourceStyle({ source: 'danbooru', import_mode: null }).label,
    )
  })
})
