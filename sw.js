// 설치 조건용 최소 서비스워커(v2): 캐시를 거치지 않고 항상 새로 받음. 바뀌면 옛 화면 대신 바로 새 화면
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(clients.claim()));
self.addEventListener('fetch', e => e.respondWith(fetch(e.request, {cache: 'no-store'})));
