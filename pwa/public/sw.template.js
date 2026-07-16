const CACHE_NAME = 'jyzrox-static-__BUILD_HASH__';
const OFFLINE_URL = '/offline.html';
// v2 intentionally rotates away from the legacy cache, which could grow to
// several GB and make cache.keys() fail before eviction could run.
const MEDIA_CACHE_NAME = 'jyzrox-media-v2';
const PAGE_CACHE_NAME = 'jyzrox-pages';

// sha256-addressed media: the same URL always denotes the same bytes.
const CONTENT_ADDRESSED_MEDIA = /^\/media\/(cas|thumbs|image)\//;
const MEDIA_CACHE_SWEEP_INTERVAL_MS = 10 * 60 * 1000;

// ── Cache Config (overridable via postMessage) ──
let cacheConfig = {
  mediaCacheTTLHours: 72,
  mediaCacheSizeMB: 8192,
  pageCacheTTLHours: 24,
};

// ── Offline Share Queue ──
const SHARE_QUEUE_DB = 'jyzrox-share-queue';
const SHARE_QUEUE_STORE = 'pending';

function openShareQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(SHARE_QUEUE_DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(SHARE_QUEUE_STORE, { autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function queueShareRequest(body, headers) {
  const db = await openShareQueueDB();
  const tx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  tx.objectStore(SHARE_QUEUE_STORE).add({ body, headers, timestamp: Date.now() });
  return new Promise((resolve) => { tx.oncomplete = resolve; });
}

// Reconnecting fires several replay triggers at once (client `online` →
// SW_REPLAY_QUEUE message, the SW's own `online` event, and the `sync` event).
// Without this guard they run concurrently, each reading the same not-yet-
// deleted queue snapshot and POSTing every item again — duplicate downloads.
let replayInProgress = false;

async function replayShareQueue() {
  if (replayInProgress) return;
  replayInProgress = true;
  try {
    await drainShareQueue();
  } finally {
    replayInProgress = false;
  }
}

async function drainShareQueue() {
  const db = await openShareQueueDB();
  const tx = db.transaction(SHARE_QUEUE_STORE, 'readonly');
  const store = tx.objectStore(SHARE_QUEUE_STORE);
  const [keys, items] = await Promise.all([
    new Promise((resolve, reject) => {
      const req = store.getAllKeys();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }),
    new Promise((resolve, reject) => {
      const req = store.getAll();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }),
  ]);

  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    const body = item.body || (item.url ? { url: item.url } : null);
    if (!body) continue;
    let response;
    try {
      response = await fetch('/api/download/', {
        method: 'POST',
        headers: item.headers || { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      });
    } catch (_) {
      return;
    }

    // fetch() only rejects on network errors. On an unsuccessful response,
    // keep the item and stop only for transient failures (auth expiry, rate
    // limiting, timeouts, server errors) so a later replay can succeed. A
    // permanent client rejection (e.g. 400/422 for an unsupported URL) would
    // otherwise wedge the queue forever, so drop that poison item and continue.
    if (!response.ok) {
      const transient =
        response.status === 401 ||
        response.status === 408 ||
        response.status === 429 ||
        response.status >= 500;
      if (transient) return;
    }

    await new Promise((resolve, reject) => {
      const deleteTx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
      const req = deleteTx.objectStore(SHARE_QUEUE_STORE).delete(keys[index]);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  }
}

async function registerShareQueueSync() {
  if (!self.registration.sync) return;
  try {
    await self.registration.sync.register('jyzrox-share-queue');
  } catch (_) {
    // Background Sync is optional; clients also request replay when online.
  }
}

function queueHeaders(request) {
  const headers = { 'Content-Type': 'application/json' };
  const csrfToken = request.headers.get('X-CSRF-Token');
  const language = request.headers.get('Accept-Language');
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  if (language) headers['Accept-Language'] = language;
  return headers;
}

self.addEventListener('sync', (event) => {
  if (event.tag === 'jyzrox-share-queue') {
    event.waitUntil(replayShareQueue());
  }
});

self.addEventListener('online', (event) => {
  event.waitUntil?.(replayShareQueue());
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SW_CACHE_CONFIG') {
    cacheConfig = { ...cacheConfig, ...event.data.config };
  }
  if (event.data?.type === 'SW_REPLAY_QUEUE') {
    event.waitUntil(replayShareQueue());
  }
  if (event.data?.type === 'SW_CLEAR_USER_CACHES') {
    // Logout: cached media/pages contain private user content and must not
    // outlive the session (BR-003). The static asset cache is content-neutral
    // and survives so the login page still hydrates offline.
    event.waitUntil(
      Promise.all([caches.delete(MEDIA_CACHE_NAME), caches.delete(PAGE_CACHE_NAME)])
    );
  }
});

function wrapResponseWithTimestamp(response) {
  const headers = new Headers(response.headers);
  headers.set('X-Cache-Time', String(Date.now()));
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function isExpired(cachedResponse, ttlHours) {
  if (!ttlHours || ttlHours <= 0) return false;
  const cacheTime = cachedResponse.headers.get('X-Cache-Time');
  if (!cacheTime) return false;
  const age = Date.now() - Number(cacheTime);
  return age > ttlHours * 3600 * 1000;
}

// A full CacheStorage walk is expensive and can itself fail once a cache grows
// into multiple GB. Use the browser's cheap origin estimate instead. If the
// configured budget is exceeded, reset the content-addressed cache as one
// background operation; individual image loads never enumerate its entries.
let lastMediaCacheSweepAt = 0;

async function maybeEnforceMediaCacheLimit() {
  if (!cacheConfig.mediaCacheSizeMB || cacheConfig.mediaCacheSizeMB <= 0) return;
  const now = Date.now();
  if (now - lastMediaCacheSweepAt < MEDIA_CACHE_SWEEP_INTERVAL_MS) return;
  lastMediaCacheSweepAt = now;

  try {
    const estimate = await navigator.storage?.estimate?.();
    const limitBytes = cacheConfig.mediaCacheSizeMB * 1024 * 1024;
    if (!estimate || !Number.isFinite(estimate.usage) || estimate.usage <= limitBytes) return;
    await caches.delete(MEDIA_CACHE_NAME);
  } catch (_) {
    // Quota enforcement is best-effort; browser origin eviction remains the
    // final storage bound.
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Pre-cache core static assets including offline fallback
      return cache.addAll(['/', OFFLINE_URL]);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME && key !== MEDIA_CACHE_NAME && key !== PAGE_CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => {
      // Try to replay any queued share requests that were stored while offline
      return replayShareQueue();
    }).then(() => {
      return self.clients.claim();
    }).then(() => {
      return self.clients.matchAll({ type: 'window' });
    }).then((clients) => {
      clients.forEach((client) => client.postMessage({ type: 'SW_UPDATED' }));
    })
  );
});

self.addEventListener('fetch', (event) => {
  const requestUrl = new URL(event.request.url);

  // Only the exact enqueue endpoint is safe to replay. Never queue cancel,
  // retry, quick-download, or other state-changing download routes.
  if (
    event.request.method === 'POST' &&
    requestUrl.origin === self.location.origin &&
    requestUrl.pathname === '/api/download/'
  ) {
    event.respondWith(
      fetch(event.request.clone()).catch(async () => {
        try {
          const body = await event.request.json();
          if (body.url) {
            await queueShareRequest(body, queueHeaders(event.request));
            await registerShareQueueSync();
            return new Response(JSON.stringify({
              job_id: 'offline-' + Date.now(),
              status: 'queued-offline',
            }), {
              status: 202,
              headers: { 'Content-Type': 'application/json' },
            });
          }
        } catch (_) {
          // body parse failed — fall through to 503
        }
        return new Response('', { status: 503 });
      })
    );
    return;
  }

  if (event.request.method !== 'GET') return;

  if (requestUrl.origin !== self.location.origin) return;

  // Authenticated API data is user-specific and must never enter a page cache
  // or be served stale while offline.
  if (requestUrl.pathname.startsWith('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Media split by addressing mode:
  //
  // - Content-addressed (/media/cas/, /media/thumbs/, /media/image/) are sha256
  //   capability URLs. The bytes behind one can never change, so revalidating
  //   buys nothing and cache-first is safe in the single-user-first model.
  //   Cached private media is cleared explicitly on logout and expires by TTL.
  // - Everything else (/media/avatars/, /media/libraries/) is path-addressed:
  //   the same URL can change content or be revoked per-gallery, so it stays
  //   network-first and revalidates, and a 401/403 is never masked by a
  //   previously authorized copy.
  if (event.request.url.includes('/media/') || event.request.url.includes('/thumbs/')) {
    let backgroundMediaWork = Promise.resolve();
    const mediaResponse =
      caches.open(MEDIA_CACHE_NAME).then(async (cache) => {
        const contentAddressed = CONTENT_ADDRESSED_MEDIA.test(requestUrl.pathname);
        if (contentAddressed) {
          const cached = await cache.match(event.request);
          if (cached && cached.status >= 200 && cached.status < 300) {
            if (!isExpired(cached, cacheConfig.mediaCacheTTLHours)) return cached;
            await cache.delete(event.request);
          }
        }
        try {
          const response = contentAddressed
            ? await fetch(event.request)
            : await fetch(event.request, { cache: 'no-cache' });
          if (response.status >= 200 && response.status < 300) {
            const stamped = wrapResponseWithTimestamp(response.clone());
            // The response does not await the write, while waitUntil below
            // keeps the worker alive long enough for it to finish reliably.
            backgroundMediaWork = cache
              .put(event.request, stamped)
              .then(maybeEnforceMediaCacheLimit, () => {});
          }
          return response;
        } catch (_) {
          const cached = await cache.match(event.request);
          if (cached && cached.status >= 200 && cached.status < 300) {
            if (!isExpired(cached, cacheConfig.mediaCacheTTLHours)) return cached;
            await cache.delete(event.request);
          }
          return new Response('', { status: 503 });
        }
      });
    event.respondWith(mediaResponse);
    event.waitUntil(mediaResponse.then(() => backgroundMediaWork, () => backgroundMediaWork));
  } else if (requestUrl.pathname.startsWith('/_next/static/')) {
    // Immutable, content-hashed build assets (JS/CSS chunks). Cache-first so
    // the app shell can still hydrate offline — without these a cached page
    // renders blank. Stored in the build-versioned static cache, which is
    // purged on the next activate, so stale chunks never linger.
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) => {
        return cache.match(event.request).then((cached) => {
          if (cached) return cached;
          return fetch(event.request).then((response) => {
            if (response.status >= 200 && response.status < 300) {
              cache.put(event.request, response.clone());
            }
            return response;
          });
        });
      })
    );
  } else if (event.request.mode === 'navigate') {
    // Network first for document navigations; fall back to the last rendered
    // page or the static offline document.
    event.respondWith(
      caches.open(PAGE_CACHE_NAME).then((cache) => {
        return fetch(event.request)
          .then((response) => {
            if (response.status >= 200 && response.status < 300) {
              const stamped = wrapResponseWithTimestamp(response.clone());
              cache.put(event.request, stamped);
            }
            return response;
          })
          .catch(async () => {
            const cached = await cache.match(event.request);
            if (cached && cached.status >= 200 && cached.status < 300) {
              if (!isExpired(cached, cacheConfig.pageCacheTTLHours)) return cached;
              cache.delete(event.request);
            }
            return caches.match(OFFLINE_URL);
          });
      })
    );
  }
});
