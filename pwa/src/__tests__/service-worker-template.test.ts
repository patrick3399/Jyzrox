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

  it('deletes queued entries individually, halting only on transient failures', () => {
    // Regression: a blanket `if (!response.ok) return` retained permanent 4xx
    // poison items (e.g. 400/422 for an unsupported URL) forever, wedging every
    // later queued download. Only transient failures should halt the replay.
    expect(source).not.toContain('if (!response.ok) return;')

    const transientGuard = source.indexOf('if (transient) return;')
    const individualDelete = source.indexOf('delete(keys[index])')

    expect(transientGuard).toBeGreaterThan(-1)
    expect(individualDelete).toBeGreaterThan(transientGuard)
    expect(source).not.toContain('objectStore(SHARE_QUEUE_STORE).clear()')
  })

  it('treats auth/rate-limit/timeout/server errors as transient, others as permanent', () => {
    expect(source).toContain('response.status === 401')
    expect(source).toContain('response.status === 408')
    expect(source).toContain('response.status === 429')
    expect(source).toContain('response.status >= 500')
  })

  it('guards replay against concurrent triggers so items are not re-sent', () => {
    // Regression: reconnecting fires client `online` (SW_REPLAY_QUEUE), the SW's
    // own `online`, and the `sync` event near-simultaneously. Without a guard,
    // each reads the same not-yet-deleted snapshot and POSTs every item again.
    const flag = source.indexOf('let replayInProgress = false;')
    const earlyReturn = source.indexOf('if (replayInProgress) return;', flag)
    const setTrue = source.indexOf('replayInProgress = true;', earlyReturn)
    const reset = source.indexOf('replayInProgress = false;', setTrue)

    expect(flag).toBeGreaterThan(-1)
    expect(earlyReturn).toBeGreaterThan(flag)
    expect(setTrue).toBeGreaterThan(earlyReturn)
    // Reset happens in a finally block so early returns cannot leave it stuck.
    expect(reset).toBeGreaterThan(setTrue)
    expect(source.slice(setTrue, reset)).toContain('finally')
  })

  it('clears user content caches on SW_CLEAR_USER_CACHES message', () => {
    // Regression (BR-003): cached pages/media survived logout, so a logged-out
    // device could still read previously cached private content. Media is no
    // longer stored, but a device that never re-activated may still hold the
    // legacy media cache, so logout deletes it by name too.
    const handler = source.indexOf("event.data?.type === 'SW_CLEAR_USER_CACHES'")
    expect(handler).toBeGreaterThan(-1)

    const pageDelete = source.indexOf('caches.delete(PAGE_CACHE_NAME)', handler)
    const legacyMediaDelete = source.indexOf('caches.delete(LEGACY_MEDIA_CACHE_NAME)', handler)
    expect(pageDelete).toBeGreaterThan(handler)
    expect(legacyMediaDelete).toBeGreaterThan(handler)
  })

  it('revalidates path-addressed media, whose URL can change or be revoked', () => {
    // /media/avatars/ and /media/libraries/ name a mutable path, and libraries
    // is authorized per-gallery on every request (services/media_authz.py), so
    // a 401/403 must never be masked by a previously authorized cached copy.
    // Content-addressed media is exempt — see the hot-path test below.
    const mediaBranch = source.indexOf("event.request.url.includes('/media/')")
    expect(mediaBranch).toBeGreaterThan(-1)
    expect(
      source.indexOf("fetch(event.request, { cache: 'no-cache' })", mediaBranch),
    ).toBeGreaterThan(mediaBranch)
  })

  it('leaves content-addressed media to the browser without forcing revalidation', () => {
    // Content-addressed media is answered by the browser's immutable HTTP
    // cache; the worker returns before respondWith. Behavioral coverage is in
    // service-worker-media-cache.test.ts; this pins the routing order.
    expect(source).toMatch(/const CONTENT_ADDRESSED_MEDIA = .*cas\|thumbs\|image/)
    const caBypass = source.indexOf(
      'if (CONTENT_ADDRESSED_MEDIA.test(requestUrl.pathname)) return;',
    )
    const pathBranch = source.indexOf("event.request.url.includes('/media/')")
    expect(caBypass).toBeGreaterThan(-1)
    expect(caBypass).toBeLessThan(pathBranch)
  })

  it('never stores media in CacheStorage', () => {
    // Regression: a worker-managed media cache duplicated the HTTP cache and
    // its budget/TTL enforcement was lost on every worker restart. The only
    // caches the worker writes are the static shell and the page cache.
    const opened = [...source.matchAll(/caches\.open\((\w+)\)/g)].map((m) => m[1])
    expect(new Set(opened)).toEqual(new Set(['CACHE_NAME', 'PAGE_CACHE_NAME']))
    expect(source).not.toContain('navigator.storage')
  })

  it('drops the legacy media cache on activation', () => {
    const activate = source.indexOf("self.addEventListener('activate'")
    expect(activate).toBeGreaterThan(-1)
    expect(source.slice(activate)).toContain(
      'keys.filter((key) => key !== CACHE_NAME && key !== PAGE_CACHE_NAME)',
    )
  })

  it('keeps immutable build assets off the service-worker startup hot path', () => {
    const staticBypass = source.indexOf(
      "if (requestUrl.pathname.startsWith('/_next/static/')) return;",
    )
    expect(staticBypass).toBeGreaterThan(-1)

    // The bypass must run before API/media/navigation CacheStorage work and
    // there must be no later static-asset respondWith branch.
    const apiBranch = source.indexOf("requestUrl.pathname.startsWith('/api/')")
    expect(staticBypass).toBeLessThan(apiBranch)
    expect(source.indexOf("else if (requestUrl.pathname.startsWith('/_next/static/'))")).toBe(-1)
  })

  it('keeps the installed-app home navigation off the iOS CacheStorage hot path', () => {
    const homeBypass = source.indexOf(
      "if (event.request.mode === 'navigate' && requestUrl.pathname === '/') return;",
    )
    const pageCacheBranch = source.indexOf("else if (event.request.mode === 'navigate')")
    const pageCacheOpen = source.indexOf('caches.open(PAGE_CACHE_NAME)', pageCacheBranch)

    expect(homeBypass).toBeGreaterThan(-1)
    expect(pageCacheBranch).toBeGreaterThan(homeBypass)
    expect(pageCacheOpen).toBeGreaterThan(pageCacheBranch)
  })
})
