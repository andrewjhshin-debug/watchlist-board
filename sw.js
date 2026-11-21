const PAGE_CACHE = 'watchlist-board-page-v1';
const home = new URL('./', self.registration.scope);

async function savedPage() {
  try {
    const cache = await caches.open(PAGE_CACHE);
    return await cache.match(home.href);
  } catch {
    return undefined;
  }
}

async function savePage(response) {
  if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) return;
  const cache = await caches.open(PAGE_CACHE);
  await cache.put(home.href, response);
}

self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => {
  event.waitUntil(clients.claim());
  event.waitUntil((async () => {
    if (!(await savedPage())) await savePage(await fetch(home, {cache: 'no-cache'}));
  })().catch(() => {}));
});

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.mode !== 'navigate' || request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== home.origin || (url.pathname !== home.pathname && url.pathname !== home.pathname + 'index.html')) return;

  const cached = savedPage();
  const reload = url.search || request.cache === 'reload' || request.cache === 'no-cache';
  const network = fetch(request, {cache: reload ? 'no-store' : 'no-cache'});
  event.waitUntil(network.then(response => savePage(response.clone())).catch(() => {}));
  event.respondWith((async () => {
    const saved = await cached;
    if (saved && !reload) return saved;
    try {
      const response = await network;
      return response.ok || !saved ? response : saved;
    } catch (error) {
      if (saved) return saved;
      throw error;
    }
  })());
});
