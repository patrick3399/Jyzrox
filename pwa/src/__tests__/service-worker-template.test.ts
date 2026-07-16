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
    // Regression (BR-003): media/page caches (72h TTL) survived logout, so a
    // logged-out device could still read previously cached private media.
    const handler = source.indexOf("event.data?.type === 'SW_CLEAR_USER_CACHES'")
    expect(handler).toBeGreaterThan(-1)

    const mediaDelete = source.indexOf('caches.delete(MEDIA_CACHE_NAME)', handler)
    const pageDelete = source.indexOf('caches.delete(PAGE_CACHE_NAME)', handler)
    expect(mediaDelete).toBeGreaterThan(handler)
    expect(pageDelete).toBeGreaterThan(handler)
  })

  it('revalidates path-addressed media, whose URL can change or be revoked', () => {
    // /media/avatars/ and /media/libraries/ name a mutable path, and libraries
    // is authorized per-gallery on every request (services/media_authz.py), so
    // a 401/403 must never be masked by a previously authorized cached copy.
    // Content-addressed media is exempt — see the cache-first test below.
    const mediaBranch = source.indexOf("event.request.url.includes('/media/')")
    expect(mediaBranch).toBeGreaterThan(-1)
    expect(source.indexOf("fetch(event.request, { cache: 'no-cache' })", mediaBranch)).toBeGreaterThan(
      mediaBranch,
    )
  })

  it('serves content-addressed media cache-first without revalidating', () => {
    // Regression (91af972): flipping the whole media branch to network-first
    // with `cache: 'no-cache'` forced every thumbnail onto the network on every
    // render, defeating nginx's `immutable`/30d headers. cas/thumbs/image are
    // sha256 capability URLs — the bytes behind them can never change.
    // Behavior is covered in service-worker-media-cache.test.ts; this pins the
    // routing predicate that decides which media is exempt from revalidation.
    expect(source).toMatch(/const CONTENT_ADDRESSED_MEDIA = .*cas\|thumbs\|image/)

    const mediaBranch = source.indexOf("event.request.url.includes('/media/')")
    const predicate = source.indexOf('CONTENT_ADDRESSED_MEDIA.test', mediaBranch)
    const cached = source.indexOf('cache.match(event.request)', predicate)
    const network = source.indexOf('fetch(event.request)', predicate)
    expect(predicate).toBeGreaterThan(mediaBranch)
    expect(cached).toBeGreaterThan(predicate)
    expect(network).toBeGreaterThan(cached)
  })

  it('never walks the full media cache to enforce its storage budget', () => {
    // Regression (91af972): enforceMediaCacheLimit() ran on every media
    // response. Normal writes must first use StorageManager.estimate(), and
    // the background write must extend the worker lifetime without blocking
    // respondWith.
    const sweep = source.indexOf('function maybeEnforceMediaCacheLimit')
    const mediaBranch = source.indexOf("event.request.url.includes('/media/')")

    expect(sweep).toBeGreaterThan(-1)
    expect(source.slice(sweep)).toContain('navigator.storage?.estimate?.()')
    expect(source.slice(sweep)).toContain('caches.delete(MEDIA_CACHE_NAME)')
    expect(source.indexOf('maybeEnforceMediaCacheLimit', mediaBranch)).toBeGreaterThan(mediaBranch)
    expect(source).not.toContain('await cache.keys()')
    expect(source).not.toContain('await cache.put(event.request, stamped)')
    expect(source.indexOf('event.waitUntil(mediaResponse', mediaBranch)).toBeGreaterThan(mediaBranch)
  })

  it('rotates the legacy oversized media cache on activation', () => {
    expect(source).toContain("const MEDIA_CACHE_NAME = 'jyzrox-media-v2'")
    const activate = source.indexOf("self.addEventListener('activate'")
    expect(activate).toBeGreaterThan(-1)
    expect(source.slice(activate)).toContain('key !== MEDIA_CACHE_NAME')
  })

  it('caches immutable build assets so the app shell can hydrate offline', () => {
    // Regression: narrowing the fetch handler to only `mode === 'navigate'`
    // left /_next/static/* chunks uncached, so offline navigations served a
    // cached HTML shell with no JS/CSS and rendered blank.
    const staticBranch = source.indexOf("requestUrl.pathname.startsWith('/_next/static/')")
    expect(staticBranch).toBeGreaterThan(-1)

    // Cache-first: the cached chunk is returned before touching the network.
    const cacheOpen = source.indexOf('caches.open(CACHE_NAME)', staticBranch)
    const cacheMatch = source.indexOf('cache.match(event.request)', cacheOpen)
    expect(cacheOpen).toBeGreaterThan(staticBranch)
    expect(cacheMatch).toBeGreaterThan(cacheOpen)
  })
})
