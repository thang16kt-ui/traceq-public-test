// Hàng đợi offline bền (IndexedDB): ảnh và đề xuất chờ gửi. Mỗi mục có UUID tạo ở client nên gửi lại
// nhiều lần không tạo bản ghi trùng (server trả về bản đã có). Xóa sạch khi đăng xuất.
import { api } from './api';

const DB_NAME = 'traceq-offline';
const STORES = ['photos', 'proposals'] as const;
type Store = typeof STORES[number];

export interface QueuedPhoto { id: string; caseId: string; itemId: string; kind: 'truoc' | 'sau'; blob: Blob; attempts?: number; error?: string }
export interface QueuedPhotoForDraft { id: string; defectTypeId: string; blob: Blob }
export interface QueuedProposal { id: string; body: any; photos?: QueuedPhotoForDraft[]; attempts?: number; error?: string; createdAt: string }

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

// Lưu ảnh dạng ArrayBuffer (Safari từng lỗi khi lưu Blob trong IndexedDB).
async function packBlob(blob: Blob) { return { data: await blob.arrayBuffer(), type: blob.type || 'image/jpeg' }; }
function unpack(item: any): Blob { return item.blob instanceof Blob ? item.blob : new Blob([item.data], { type: item.type || 'image/jpeg' }); }

export async function enqueuePhoto(photo: QueuedPhoto) {
  const { blob, ...rest } = photo;
  await put('photos', { ...rest, ...(await packBlob(blob)), attempts: 0 }); changed();
}
export async function enqueueProposal(item: QueuedProposal) {
  const photos = await Promise.all((item.photos || []).map(async ({ blob, ...rest }) => ({ ...rest, ...(await packBlob(blob)) })));
  await put('proposals', { ...item, photos, attempts: 0 }); changed();
}
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
      try {
        const created = await api('/defect-cases', { method: 'POST', body: p.body, key: 'offline-' + p.id, retry: false });
        // Ảnh chụp lúc offline: gắn vào mục lỗi theo loại lỗi (duy nhất trong một đề xuất).
        for (const photo of p.photos || []) {
          const item = created.items.find((i: any) => i.defect_type_id === photo.defectTypeId);
          if (item) await put('photos', { id: photo.id, caseId: created.id, itemId: item.id, kind: 'truoc', data: (photo as any).data, type: (photo as any).type, attempts: 0 });
        }
        await remove('proposals', p.id);
      }
      catch (e: any) { if (e?.code === 'NETWORK' || e?.code === 'SERVER_STARTING') break; await put('proposals', { ...p, attempts: (p.attempts || 0) + 1, error: e?.message }); }
    }
    for (const p of await all<QueuedPhoto>('photos')) {
      const form = new FormData();
      form.append('file', unpack(p), 'anh.jpg'); form.append('kind', p.kind); form.append('photo_id', p.id);
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

/** GET có bản lưu dự phòng (danh mục, đợt kiểm) để mở form tạo đề xuất khi mất mạng. Không dùng cho dữ liệu nhạy cảm. */
export async function cachedGet(path: string, signal?: AbortSignal) {
  const keyName = 'traceq.cache.' + path;
  try {
    const data = await api(path, { signal, retry: false });
    try { localStorage.setItem(keyName, JSON.stringify(data)); } catch { /* đầy bộ nhớ */ }
    return data;
  } catch (e: any) {
    if (e?.name === 'AbortError') throw e;
    const saved = (() => { try { return localStorage.getItem(keyName); } catch { return null; } })();
    if (saved && (e?.code === 'NETWORK' || e?.code === 'SERVER_STARTING')) return { ...JSON.parse(saved), _offline: true };
    throw e;
  }
}
