// 설치 조건용 최소 서비스워커: 캐시를 거치지 않고 항상 새로 받음(GitHub 가 10분 캐시를 걸어서)
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request, {cache: 'no-store'})));
