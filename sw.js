// v3: 화면·시세는 새로 받고, 폰트·스타일은 브라우저의 정상 캐시를 사용한다.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => {
  if(e.request.mode === 'navigate') e.respondWith(fetch(e.request, {cache: 'no-store'}));
});
