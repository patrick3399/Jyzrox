/**
 * Source contracts for the lists that must use fixed, width-derived row heights.
 *
 * A hard-coded numeric `estimateHeight` with measured rows leaves every row above
 * a restored scroll position at the guess, so scrolling up corrects scrollTop by
 * the guess error once per row and the list stutters backwards. These pages must
 * pass `measureRows={false}` plus an estimator function, and their cards must
 * keep a height that is a pure function of the column width (no text that can
 * wrap, no inline-block baseline gap), otherwise fixed rows overlap or gap.
 *
 * Each assertion isolates the relevant opening tag / JSX first so an unrelated
 * match elsewhere in the file cannot satisfy it.
 */
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(process.cwd(), relativePath), 'utf8')
}

/** Top-level props of every `<VirtualGrid ...>` opening tag in `source`, by prop name. */
function virtualGridTags(source: string): Array<Map<string, string>> {
  const tags: Array<Map<string, string>> = []
  let from = 0
  for (;;) {
    const start = source.indexOf('<VirtualGrid', from)
    if (start === -1) break
    let i = start + '<VirtualGrid'.length
    const props = new Map<string, string>()
    while (i < source.length) {
      const rest = source.slice(i)
      const ws = /^\s+/.exec(rest)
      if (ws) {
        i += ws[0].length
        continue
      }
      if (rest.startsWith('/>')) {
        i += 2
        break
      }
      if (rest.startsWith('>')) {
        i += 1
        break
      }
      const name = /^([A-Za-z_][\w-]*)/.exec(rest)
      if (!name) throw new Error(`cannot parse VirtualGrid props near: ${rest.slice(0, 60)}`)
      i += name[1].length
      if (source[i] !== '=') {
        props.set(name[1], 'true')
        continue
      }
      i += 1
      if (source[i] === '{') {
        let depth = 0
        const valueStart = i + 1
        for (; i < source.length; i += 1) {
          if (source[i] === '{') depth += 1
          else if (source[i] === '}') {
            depth -= 1
            if (depth === 0) break
          }
        }
        props.set(name[1], source.slice(valueStart, i).trim())
        i += 1
      } else {
        const quote = source[i]
        const end = source.indexOf(quote, i + 1)
        props.set(name[1], source.slice(i + 1, end))
        i = end + 1
      }
    }
    tags.push(props)
    from = i
  }
  return tags
}

function singleGrid(source: string, which = 0): Map<string, string> {
  const tags = virtualGridTags(source)
  const tag = tags[which]
  if (!tag) throw new Error(`VirtualGrid #${which} not found`)
  // Sanity: the parser reached the end of the opening tag, not into a child.
  expect(tag.has('items')).toBe(true)
  expect(tag.has('renderItem')).toBe(true)
  return tag
}

function expectFixedRows(grid: Map<string, string>, estimator: string) {
  expect(grid.get('measureRows')).toBe('false')
  expect(grid.get('estimateHeight')).toBe(estimator)
  expect(grid.get('estimateHeight')).not.toMatch(/^\d+$/)
}

/** The class template literal of the first className that contains every given token. */
function classTemplateContaining(source: string, tokens: string[]): string | undefined {
  const pattern = /className=\{`([^`]*)`\}/g
  for (const match of source.matchAll(pattern)) {
    const classes = match[1]
    if (tokens.every((token) => new RegExp(`(^|[\\s\`])${token}($|[\\s\`$])`).test(classes))) {
      return classes
    }
  }
  return undefined
}

describe('artists page grids use fixed width-derived row heights', () => {
  const source = read('src/app/artists/page.tsx')

  it('passes measureRows={false} and the artist row estimator to both grids instead of a numeric estimate', () => {
    expect(virtualGridTags(source)).toHaveLength(2)
    for (const which of [0, 1]) {
      expectFixedRows(singleGrid(source, which), 'estimateArtistRowHeight')
    }
  })

  it('truncates the all-artists card stats line so it cannot wrap and outgrow the fixed row on phones', () => {
    const stats =
      /<p className="[^"]*\btext-sm\b[^"]*\btruncate\b[^"]*">\s*\{a\.artist_name[\s\S]*?<\/p>\s*<p className="([^"]*)">/.exec(
        source,
      )

    expect(stats, 'stats <p> after the truncated title not found').not.toBeNull()
    expect(stats?.[1]).toMatch(/\btext-xs\b/)
    expect(stats?.[1]).toMatch(/\btruncate\b/)
  })
})

describe('artist detail page gallery grid uses fixed width-derived row heights', () => {
  const source = read('src/app/artists/[artistId]/page.tsx')

  it('passes measureRows={false} and the artist gallery estimator instead of a numeric estimate', () => {
    expect(virtualGridTags(source)).toHaveLength(1)
    expectFixedRows(singleGrid(source), 'estimateArtistGalleryRowHeight')
  })
})

describe('history page grid uses fixed width-derived row heights', () => {
  const source = read('src/app/history/page.tsx')

  it('passes measureRows={false} and the history estimator instead of a numeric estimate', () => {
    expect(virtualGridTags(source)).toHaveLength(1)
    expectFixedRows(singleGrid(source), 'estimateHistoryRowHeight')
  })

  it('keeps the HistoryCard meta row to one line: the source label truncates and the time label never wraps', () => {
    const card = /function HistoryCard\([\s\S]*?\n}\n/.exec(source)?.[0] ?? ''
    const row =
      /<div className="(?=[^"]*\bjustify-between\b)(?=[^"]*\bmt-1\.5\b)[^"]*">\s*<span className="([^"]*)">[\s\S]*?<\/span>\s*<span className="([^"]*)">/.exec(
        card,
      )

    expect(row, 'HistoryCard meta row not found').not.toBeNull()
    const [, sourceClasses, timeClasses] = row ?? []
    expect(sourceClasses).toMatch(/\btext-\[10px\]/)
    expect(timeClasses).toMatch(/\btext-\[10px\]/)
    expect(sourceClasses).toMatch(/\btruncate\b/)
    expect(sourceClasses).toMatch(/\bmin-w-0\b/)
    expect(timeClasses).toMatch(/\bwhitespace-nowrap\b/)
    expect(timeClasses).toMatch(/\bshrink-0\b/)
  })
})

describe('library gallery detail thumbnail grid uses fixed width-derived row heights', () => {
  const source = read('src/app/library/[source]/[sourceId]/page.tsx')

  it('passes measureRows={false} and the gallery thumbnail estimator instead of a numeric estimate', () => {
    const grids = virtualGridTags(source)
    const thumbnails = grids.findIndex((props) => props.get('items') === 'images')

    expect(thumbnails, 'image thumbnail VirtualGrid not found').toBeGreaterThanOrEqual(0)
    expectFixedRows(singleGrid(source, thumbnails), 'estimateGalleryThumbRowHeight')
  })

  it('makes the select-mode thumbnail button a full-width block so it does not sit on a text baseline', () => {
    const classes = classTemplateContaining(source, [
      'relative',
      'group',
      'rounded',
      'border-2',
      'select-none',
    ])

    expect(classes, 'select-mode wrapper button className not found').toBeDefined()
    expect(classes).toMatch(/(^|\s)block(\s|$)/)
    expect(classes).toMatch(/(^|\s)w-full(\s|$)/)
  })
})

describe('JustifiedGrid rows keep their exact computed heights', () => {
  const source = read('src/components/JustifiedGrid.tsx')

  it('does not measure rows through measureElement because their heights are already exact', () => {
    expect(source).not.toMatch(/ref=\{[^}]*measureElement/)
  })

  it('re-measures the virtualizer when row heights change so cached sizes by row index cannot go stale', () => {
    expect(source).toMatch(/\.measure\(\)/)
  })
})
