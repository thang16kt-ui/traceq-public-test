/* TraceQ service worker.
 * - Vỏ ứng dụng (index, manifest, biểu tượng, /assets/* đã băm tên) được lưu đệm để mở được khi mất mạng.
 * - KHÔNG lưu đệm dữ liệu API (tránh lộ/sai dữ liệu); dữ liệu offline nằm trong IndexedDB và bị xóa khi đăng xuất.
 * - Web Push: hiển thị thông báo và mở đúng đề xuất.
 */
const CACHE = 'traceq-shell-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/health/')) return; // luôn đi mạng
  if (request.mode === 'navigate') {
    // Trang: ưu tiên mạng (bản mới nhất), mất mạng thì dùng vỏ đã lưu.
    event.respondWith(fetch(request).then((response) => {
      const copy = response.clone(); caches.open(CACHE).then((c) => c.put('/index.html', copy)); return response;
    }).catch(() => caches.match('/index.html')));
    return;
  }
  if (url.pathname.startsWith('/assets/') || SHELL.includes(url.pathname) || url.pathname.endsWith('.png')) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((response) => {
      if (response.ok) { const copy = response.clone(); caches.open(CACHE).then((c) => c.put(request, copy)); }
      return response;
    })));
  }
});
self.addEventListener('message', (event) => {
  if (event.data === 'clear-cache') event.waitUntil(caches.delete(CACHE));
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'TraceQ', body: event.data && event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'TraceQ', {
    body: data.body || '', tag: data.id || data.tag, data: { url: data.url || '/#/thong-bao' },
    icon: '/icon-192.png', badge: '/icon-192.png', requireInteraction: data.tag === 'uu_tien',
  }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/#/thong-bao';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    for (const client of list) { if ('focus' in client) { client.navigate(url); return client.focus(); } }
    return self.clients.openWindow(url);
  }));
});
