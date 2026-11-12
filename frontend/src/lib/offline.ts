// Hàng đợi offline bền (IndexedDB): ảnh và đề xuất chờ gửi. Mỗi mục có UUID tạo ở client nên gửi lại
// nhiều lần không tạo bản ghi trùng (server trả về bản đã có). Xóa sạch khi đăng xuất.
import { api } from './api';

const DB_NAME = 'traceq-offline';
const STORES = ['photos', 'proposals'] as const;
type Store = typeof STORES[number];

export interface QueuedPhoto { id: string; caseId: string; itemId: string; kind: 'truoc' | 'sau'; blob: Blob; attempts?: number; error?: string }
export interface QueuedProposal { id: string; body: any; attempts?: number; error?: string; createdAt: string }

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) { reject(new Error('Trình duyệt không hỗ trợ lưu offline')); return; }
    const request = indexedDB.open(DB_NAME, 2);
    request.onupgradeneeded = () => { STORES.forEach((s) => { if (!request.result.objectStoreNames.contains(s)) request.result.createObjectStore(s, { keyPath: 'id' }); }); };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function tx<T>(store: Store, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const request = fn(t.objectStore(store));
    t.oncomplete = () => { db.close(); resolve(request ? request.result : undefined); };
    t.onerror = () => { db.close(); reject(t.error); };
  });
}

const all = <T,>(store: Store) => tx<T[]>(store, 'readonly', (s) => s.getAll() as IDBRequest<T[]>).then((x) => x || []);
const put = (store: Store, value: any) => tx(store, 'readwrite', (s) => { s.put(value); });
const remove = (store: Store, id: string) => tx(store, 'readwrite', (s) => { s.delete(id); });

function changed() { window.dispatchEvent(new Event('traceq:queue')); }

export async function enqueuePhoto(photo: QueuedPhoto) { await put('photos', { ...photo, attempts: 0 }); changed(); }
export async function enqueueProposal(item: QueuedProposal) { await put('proposals', { ...item, attempts: 0 }); changed(); }
export async function pendingCounts() {
  try { return { photos: (await all('photos')).length, proposals: (await all('proposals')).length }; }
  catch { return { photos: 0, proposals: 0 }; }
}
export async function pendingProposals(): Promise<QueuedProposal[]> { try { return await all<QueuedProposal>('proposals'); } catch { return []; } }

let flushing = false;
/** Gửi lần lượt các mục chờ. Trả số mục còn lại. */
export async function flushQueue(): Promise<number> {
  if (flushing || !navigator.onLine) return (await pendingCounts()).photos + (await pendingCounts()).proposals;
  flushing = true;
  try {
    for (const p of await all<QueuedProposal>('proposals')) {
      try { await api('/defect-cases', { method: 'POST', body: p.body, key: 'offline-' + p.id, retry: false }); await remove('proposals', p.id); }
      catch (e: any) { if (e?.code === 'NETWORK' || e?.code === 'SERVER_STARTING') break; await put('proposals', { ...p, attempts: (p.attempts || 0) + 1, error: e?.message }); }
    }
    for (const p of await all<QueuedPhoto>('photos')) {
      const form = new FormData();
      form.append('file', p.blob, 'anh.jpg'); form.append('kind', p.kind); form.append('photo_id', p.id);
      try { await api(`/defect-cases/${p.caseId}/items/${p.itemId}/photos`, { method: 'POST', body: form, key: p.id, retry: false }); await remove('photos', p.id); }
      catch (e: any) { if (e?.code === 'NETWORK' || e?.code === 'SERVER_STARTING') break; await put('photos', { ...p, attempts: (p.attempts || 0) + 1, error: e?.message }); }
    }
  } finally { flushing = false; changed(); }
  const counts = await pendingCounts();
  return counts.photos + counts.proposals;
}

export async function clearOffline() {
  try { for (const s of STORES) await tx(s, 'readwrite', (store) => { store.clear(); }); } catch { /* bỏ qua */ }
  try { indexedDB.deleteDatabase(DB_NAME); } catch { /* bỏ qua */ }
  changed();
}

export function startBackgroundSync() {
  const run = () => { flushQueue().catch(() => {}); };
  window.addEventListener('online', run);
  const timer = setInterval(run, 30000);
  run();
  return () => { window.removeEventListener('online', run); clearInterval(timer); };
}
