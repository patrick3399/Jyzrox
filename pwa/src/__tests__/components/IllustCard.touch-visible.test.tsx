import { readFileSync } from 'fs'
import { join } from 'path'
import { describe, it, expect } from 'vitest'

// Regression: card-grid overlay affordances (Pixiv Download / bookmark buttons,
// E-Hentai / collections / history delete buttons, artist hover scrim) used the
// hover-only pattern `opacity-0 group-hover:opacity-100`. Touch devices have no
// hover, so an interactive overlay stayed invisible yet remained laid out and
// tappable — on /pixiv?tab=bookmarks, tapping the bottom-right (where the hidden
// Download button sits) fired a download the user could not see.
//
// Fix: base `opacity-100` (visible on touch) + `can-hover:` guarded hide, so the
// hidden-until-hover behaviour only applies where the device can actually hover.
// This scan locks the whole class of bug out of every card page at once.

const SRC = join(__dirname, '../../')

function src(rel: string) {
  return readFileSync(join(SRC, rel), 'utf-8')
}

// Every page that renders hover-reveal overlays on a card/thumbnail.
const CARD_PAGES = [
  'app/pixiv/page.tsx',
  'app/pixiv/user/[id]/page.tsx',
  'app/e-hentai/page.tsx',
  'app/collections/page.tsx',
  'app/collections/[id]/page.tsx',
  'app/artists/[artistId]/page.tsx',
  'app/history/page.tsx',
]

describe('card overlays must not be invisible-but-tappable on touch devices', () => {
  it('the can-hover variant is registered', () => {
    expect(src('app/globals.css')).toContain('@custom-variant can-hover (@media (hover: hover))')
  })

  for (const page of CARD_PAGES) {
    it(`${page}: no unguarded hover-only reveal (opacity-0 group-hover:opacity-100)`, () => {
      const source = src(page)
      // The exact buggy signature: hidden by default, revealed only on :hover,
      // with no can-hover guard — invisible and tappable on touch.
      expect(source).not.toContain('opacity-0 group-hover:opacity-100')
    })

    it(`${page}: hover-reveal is guarded by can-hover`, () => {
      const source = src(page)
      // Any hover reveal present must go through the can-hover guard.
      if (source.includes('group-hover:opacity-100')) {
        expect(source).toContain('can-hover:group-hover:opacity-100')
      }
    })
  }
})
