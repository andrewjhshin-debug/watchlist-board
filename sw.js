// v4: 화면은 열 때마다 주소에 꼬리표를 붙여 서버 캐시(10분) 없이 새로 받는다. 폰트·스타일은 정상 캐시.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => {
  if(e.request.mode !== 'navigate') return;
  const u = new URL(e.request.url); u.searchParams.set('_', Date.now());
  e.respondWith(fetch(u, {cache: 'no-store'}).catch(() => fetch(e.request)));
});
