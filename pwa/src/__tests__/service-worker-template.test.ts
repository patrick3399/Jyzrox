import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'public/sw.template.js'), 'utf8')

describe('service worker request safety', () => {
  it('never caches authenticated API GET responses', () => {
    const apiBypass = source.indexOf("requestUrl.pathname.startsWith('/api/')")
    const pageCache = source.indexOf('caches.open(PAGE_CACHE_NAME)', apiBypass)

    expect(apiBypass).toBeGreaterThan(-1)
    expect(pageCache).toBeGreaterThan(apiBypass)
    expect(source).toContain('event.respondWith(fetch(event.request))')
  })

  it('queues only the exact download enqueue endpoint and preserves its payload', () => {
    expect(source).toContain("requestUrl.pathname === '/api/download/'")
    expect(source).not.toContain("event.request.url.includes('/api/download/')")
    expect(source).toContain('queueShareRequest(body, queueHeaders(event.request))')
    expect(source).toContain('item.body || (item.url ? { url: item.url } : null)')
    expect(source).toContain('body: JSON.stringify(body)')
  })

  it('deletes queued entries individually only after a successful response', () => {
    const acceptedGuard = source.indexOf('if (!response.ok) return;')
    const individualDelete = source.indexOf('delete(keys[index])')

    expect(acceptedGuard).toBeGreaterThan(-1)
    expect(individualDelete).toBeGreaterThan(acceptedGuard)
    expect(source).not.toContain('objectStore(SHARE_QUEUE_STORE).clear()')
  })
})
