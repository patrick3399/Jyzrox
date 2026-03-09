const CACHE_NAME = 'jyzrox-static-v1';
const OFFLINE_URL = '/offline.html';

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

async function queueShareRequest(url) {
  const db = await openShareQueueDB();
  const tx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  tx.objectStore(SHARE_QUEUE_STORE).add({ url, timestamp: Date.now() });
  return new Promise((resolve) => { tx.oncomplete = resolve; });
}

async function replayShareQueue() {
  const db = await openShareQueueDB();
  const tx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  const store = tx.objectStore(SHARE_QUEUE_STORE);
  const items = await new Promise((resolve) => {
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
  });

  for (const item of items) {
    try {
      await fetch('/api/download/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ url: item.url }),
      });
    } catch (e) {
      // Still offline, stop trying
      return;
    }
  }

  // Clear all successfully replayed items
  const clearTx = db.transaction(SHARE_QUEUE_STORE, 'readwrite');
  clearTx.objectStore(SHARE_QUEUE_STORE).clear();
}

// Listen for online event to replay queue
self.addEventListener('online', () => {
  replayShareQueue();
});

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
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => {
      // Try to replay any queued share requests that were stored while offline
      return replayShareQueue();
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Intercept POST requests to /api/download/ to support offline queuing
  if (event.request.method === 'POST' && event.request.url.includes('/api/download/')) {
    event.respondWith(
      fetch(event.request.clone()).catch(async () => {
        try {
          const body = await event.request.json();
          if (body.url) {
            await queueShareRequest(body.url);
            return new Response(JSON.stringify({
              job_id: 'offline-' + Date.now(),
              status: 'queued-offline',
            }), {
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

  // Cache-first for images/media if possible, otherwise network-first
  if (event.request.url.includes('/media/') || event.request.url.includes('/thumbs/')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        // Only return cached response if it was a successful 2xx response
        if (cached && cached.status >= 200 && cached.status < 300) return cached;
        return fetch(event.request).then((response) => {
          // Only cache successful 2xx responses
          if (response.status >= 200 && response.status < 300) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        });
      })
    );
  } else {
    // Network first for other requests; fall back to cache or offline page
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Don't cache error responses from network
          if (response.status >= 200 && response.status < 300) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(event.request);
          // Only use cache if it contains a valid 2xx response
          if (cached && cached.status >= 200 && cached.status < 300) return cached;
          // For navigate requests show the offline fallback page
          if (event.request.mode === 'navigate') {
            return caches.match(OFFLINE_URL);
          }
          return new Response('', { status: 503 });
        })
    );
  }
});
