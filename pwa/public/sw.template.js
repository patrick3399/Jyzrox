const CACHE_NAME = 'jyzrox-static-__BUILD_HASH__';
const OFFLINE_URL = '/offline.html';
const MEDIA_CACHE_NAME = 'jyzrox-media';
const PAGE_CACHE_NAME = 'jyzrox-pages';

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

async function replayShareQueue() {
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

    // fetch() only rejects on network errors. Retain the item unless the API
    // explicitly accepts it, including authentication and server failures.
    if (!response.ok) return;

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

async function enforceMediaCacheLimit() {
  if (!cacheConfig.mediaCacheSizeMB || cacheConfig.mediaCacheSizeMB <= 0) return;
  try {
    const cache = await caches.open(MEDIA_CACHE_NAME);
    const keys = await cache.keys();

    // Collect entries with their timestamps and sizes
    const entries = [];
    for (const request of keys) {
      const response = await cache.match(request);
      if (!response) continue;
      const cacheTime = Number(response.headers.get('X-Cache-Time') || '0');
      const size = Number(response.headers.get('Content-Length') || '0');
      entries.push({ request, cacheTime, size });
    }

    const totalSize = entries.reduce((sum, e) => sum + e.size, 0);
    const limitBytes = cacheConfig.mediaCacheSizeMB * 1024 * 1024;

    if (totalSize <= limitBytes) return;

    // Sort oldest first
    entries.sort((a, b) => a.cacheTime - b.cacheTime);

    let currentSize = totalSize;
    for (const entry of entries) {
      if (currentSize <= limitBytes) break;
      await cache.delete(entry.request);
      currentSize -= entry.size;
    }
  } catch (e) {
    // Non-critical, silently ignore
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

  // Cache-first for images/media if possible, otherwise network-first
  if (event.request.url.includes('/media/') || event.request.url.includes('/thumbs/')) {
    event.respondWith(
      caches.open(MEDIA_CACHE_NAME).then((cache) => {
        return cache.match(event.request).then((cached) => {
          if (cached && cached.status >= 200 && cached.status < 300) {
            if (!isExpired(cached, cacheConfig.mediaCacheTTLHours)) return cached;
            cache.delete(event.request);
          }
          return fetch(event.request).then((response) => {
            if (response.status >= 200 && response.status < 300) {
              const stamped = wrapResponseWithTimestamp(response.clone());
              cache.put(event.request, stamped);
              enforceMediaCacheLimit();
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
