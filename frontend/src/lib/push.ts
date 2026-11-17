// Đăng ký Web Push trên thiết bị này (cần HTTPS + quyền thông báo).
import { get, post } from './api';

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return null;
  try { return await navigator.serviceWorker.register('/sw.js', { scope: '/' }); } catch { return null; }
}

function keyBytes(base64: string) {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

export async function pushStatus(): Promise<'unsupported' | 'disabled' | 'denied' | 'on' | 'off'> {
  if (!('PushManager' in window) || !('serviceWorker' in navigator) || !window.isSecureContext) return 'unsupported';
  const config = await get('/push/public-key');
  if (!config.enabled) return 'disabled';
  if (Notification.permission === 'denied') return 'denied';
  const registration = await navigator.serviceWorker.getRegistration('/');
  const subscription = await registration?.pushManager.getSubscription();
  return subscription ? 'on' : 'off';
}

export async function enablePush() {
  const config = await get('/push/public-key');
  if (!config.enabled) throw new Error('Máy chủ chưa cấu hình thông báo đẩy');
  if (await Notification.requestPermission() !== 'granted') throw new Error('Bạn chưa cho phép thông báo trên trình duyệt này');
  const registration = (await registerServiceWorker()) || (await navigator.serviceWorker.ready);
  const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(config.public_key) });
  const json = subscription.toJSON();
  await post('/push/subscribe', { endpoint: json.endpoint, keys: json.keys });
}

export async function disablePush() {
  const registration = await navigator.serviceWorker.getRegistration('/');
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;
  const json = subscription.toJSON();
  await post('/push/unsubscribe', { endpoint: json.endpoint, keys: json.keys }).catch(() => {});
  await subscription.unsubscribe();
}
