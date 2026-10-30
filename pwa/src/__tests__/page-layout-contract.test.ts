import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const APP = path.resolve(__dirname, '../app')

type Kind = 'primary' | 'secondary' | 'settings' | 'exempt'

// Every route must be listed. Primary = browse surfaces, unbounded width.
const LAYOUT: Record<string, Kind> = {
  '/': 'primary',
  '/library': 'primary',
  '/library/[source]/[sourceId]': 'primary',
  '/e-hentai': 'primary',
  '/e-hentai/[gid]/[token]': 'primary',
  '/pixiv': 'primary',
  '/pixiv/following': 'primary',
  '/pixiv/illust/[id]': 'primary',
  '/pixiv/user/[id]': 'primary',
  '/explorer': 'primary',
  '/images': 'primary',
  '/artists': 'primary',
  '/artists/[artistId]': 'primary',
  '/collections': 'primary',
  '/collections/[id]': 'primary',
  '/datasets': 'primary',
  '/datasets/[id]': 'primary',
  '/history': 'primary',
  '/tags': 'primary',
  '/queue': 'primary',
  '/admin/dashboard': 'secondary',
  '/admin/queue': 'secondary',
  '/admin/sites': 'secondary',
  '/admin/users': 'secondary',
  '/dedup': 'secondary',
  '/logs': 'secondary',
  '/stats': 'secondary',
  '/export': 'secondary',
  '/import': 'secondary',
  '/plugins': 'secondary',
  '/credentials': 'secondary',
  '/subscriptions': 'secondary',
  '/trash': 'secondary',
  '/reading-list': 'secondary',
  '/scheduled-tasks': 'secondary',
  '/novels': 'secondary',
  '/novels/search': 'secondary',
  '/novels/graph': 'secondary',
  '/novels/notes': 'secondary',
  '/novels/note/[...path]': 'secondary',
  '/novels/[work]': 'secondary',
  '/novels/[work]/[chapter]': 'secondary',
  // Outside LayoutShell (auth/public) or full-screen.
  '/login': 'exempt',
  '/setup': 'exempt',
  '/share/[token]': 'exempt',
  '/share-target': 'exempt',
  '/forbidden': 'exempt',
  '/e-hentai/read/[gid]/[token]': 'exempt',
  '/reader/[source]/[sourceId]': 'exempt',
  '/reader/artist/[artistId]': 'exempt',
  '/reader/favorites': 'exempt',
  '/reader/gallery/[source]/[sourceId]': 'exempt',
  '/reader/pixiv/[id]': 'exempt',
}

function pageFiles(dir = APP, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    if (statSync(full).isDirectory()) pageFiles(full, out)
    else if (name === 'page.tsx') out.push(full)
  }
  return out
}

function routeOf(file: string): string {
  const rel = path.relative(APP, path.dirname(file)).split(path.sep).join('/')
  return `/${rel}`.replace(/\/$/, '') || '/'
}

const pages = pageFiles().map((file) => ({ file, route: routeOf(file), src: readFileSync(file, 'utf8') }))
const kindOf = (route: string): Kind => (route.startsWith('/settings') ? 'settings' : LAYOUT[route])

// LayoutShell already pads the page; a page adding horizontal + vertical page padding doubles it.
const DOUBLE_PADDING = /className=["'`{][^"'`]*(?:\b(?:px-4|p-4)\b[^"'`]*\b(?:py-6|py-8|md:p-6|md:p-8)\b|\b(?:py-6|py-8)\b[^"'`]*\bpx-4\b)/
// app/images/page.tsx re-creates the shell padding inside its own fixed full-screen panel.
const PADDING_ALLOWLIST = new Set(['/images'])

describe('page layout contract', () => {
  it('classifies every page (add new routes to LAYOUT)', () => {
    const missing = pages.filter((p) => !kindOf(p.route)).map((p) => p.route)
    expect(missing).toEqual([])
    const stale = Object.keys(LAYOUT).filter((route) => !pages.some((p) => p.route === route))
    expect(stale).toEqual([])
  })

  it.each(pages.filter((p) => kindOf(p.route) === 'primary').map((p) => [p.route, p.src]))(
    '%s uses an unbounded PageContainer',
    (_route, src) => {
      expect(src).toMatch(/<PageContainer(?![^>]*variant="secondary")/)
    },
  )

  it.each(pages.filter((p) => kindOf(p.route) === 'secondary').map((p) => [p.route, p.src]))(
    '%s uses the secondary PageContainer',
    (_route, src) => {
      expect(src).toContain('<PageContainer variant="secondary"')
    },
  )

  it.each(pages.filter((p) => kindOf(p.route) === 'settings').map((p) => [p.route, p.src]))(
    '%s stays inside the settings shell and uses PageHeader',
    (_route, src) => {
      expect(src).toContain('<PageHeader')
      expect(src).not.toContain('<PageContainer')
    },
  )

  it.each(pages.filter((p) => kindOf(p.route) !== 'exempt' && !PADDING_ALLOWLIST.has(p.route)).map((p) => [p.route, p.src]))(
    '%s does not add its own page padding',
    (_route, src) => {
      expect(src).not.toMatch(DOUBLE_PADDING)
    },
  )
})
