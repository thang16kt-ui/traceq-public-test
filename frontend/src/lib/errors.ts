// Gửi lỗi giao diện về máy chủ (giám sát). Giới hạn số lần, không gửi dữ liệu form.
let sent = 0;
export function reportError(message: string, detail = '') {
  if (sent >= 10) return;
  sent++;
  try {
    const csrf = (window as any).__traceqCsrf || '';
    fetch('/api/v1/client-errors', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, 'Idempotency-Key': String(Date.now()) + Math.random() },
      body: JSON.stringify({ message: message.slice(0, 2000), detail: detail.slice(0, 20000), path: location.hash.slice(0, 300) }) }).catch(() => {});
  } catch { /* bỏ qua */ }
}
export function installErrorReporting() {
  window.addEventListener('error', (e) => reportError(String(e.message || 'Lỗi JS'), e.error?.stack || ''));
  window.addEventListener('unhandledrejection', (e) => { const r: any = e.reason; if (r?.status) return; reportError('Promise: ' + String(r?.message || r), r?.stack || ''); });
}
