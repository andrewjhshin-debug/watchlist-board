// 설치 조건용 최소 서비스워커: 항상 네트워크에서 새로 받음(시세가 늘 최신이도록)
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('fetch', e => e.respondWith(fetch(e.request)));
