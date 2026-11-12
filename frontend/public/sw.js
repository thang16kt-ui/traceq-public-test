/* TraceQ service worker: Web Push + (hạng mục 13) bộ nhớ đệm ứng dụng. */
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
