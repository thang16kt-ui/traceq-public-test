// Gọi API: cookie phiên + X-CSRF-Token, Idempotency-Key cho mọi thao tác ghi.
// Khi máy chủ đang khởi động (Render ngủ đông) hoặc mất mạng: tự thử lại với CÙNG khóa,
// nên gửi lại không tạo bản ghi trùng.
export type Row = Record<string, any>;

export function uuid(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

let csrfToken = '';
export function setCSRF(value: string) { csrfToken = value || ''; }

export class ApiError extends Error {
  status: number; code: string; fields: Row; requestId: string;
  constructor(status: number, data: Row) {
    super(data.message || `Yêu cầu thất bại (${status})`);
    this.status = status; this.code = data.code || ''; this.fields = data.field_errors || {}; this.requestId = data.request_id || '';
  }
}

export type ServerState = 'ok' | 'waking' | 'offline';
type Listener = (state: ServerState) => void;
const listeners = new Set<Listener>();
let serverState: ServerState = 'ok';
export function onServerState(fn: Listener) { listeners.add(fn); fn(serverState); return () => { listeners.delete(fn); }; }
function setServerState(state: ServerState) { if (state !== serverState) { serverState = state; listeners.forEach((fn) => fn(state)); } }

let unauthorizedHandler: (() => void) | null = null;
export function onUnauthorized(fn: () => void) { unauthorizedHandler = fn; }

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const RETRY_DELAYS = [1000, 2000, 4000, 6000, 8000, 10000, 10000, 10000]; // ~50 giây: đủ cho Render khởi động

export interface ApiOptions { method?: string; body?: any; key?: string; signal?: AbortSignal; retry?: boolean }

export async function api(path: string, options: ApiOptions = {}): Promise<any> {
  const method = (options.method || 'GET').toUpperCase();
  const write = !['GET', 'HEAD'].includes(method);
  const key = write ? options.key || uuid() : undefined;
  const canRetry = options.retry !== false;
  for (let attempt = 0; ; attempt++) {
    const headers = new Headers();
    let body: BodyInit | undefined;
    if (options.body instanceof FormData) body = options.body;
    else if (options.body !== undefined) { body = JSON.stringify(options.body); headers.set('Content-Type', 'application/json'); }
    if (write) { headers.set('X-CSRF-Token', csrfToken); headers.set('Idempotency-Key', key!); }
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, { method, body, headers, credentials: 'include', signal: options.signal });
    } catch (error) {
      if (options.signal?.aborted) throw error;
      setServerState(navigator.onLine ? 'waking' : 'offline');
      if (!canRetry || attempt >= RETRY_DELAYS.length) throw new ApiError(0, { code: 'NETWORK', message: navigator.onLine ? 'Chưa kết nối được máy chủ. Dữ liệu đang nhập vẫn được giữ, hãy thử lại.' : 'Thiết bị đang mất mạng. Dữ liệu đang nhập vẫn được giữ.' });
      await sleep(RETRY_DELAYS[attempt]);
      continue;
    }
    const type = response.headers.get('content-type') || '';
    const waking = [502, 503, 504].includes(response.status) || (!type.includes('application/json') && !response.ok);
    if (waking) {
      setServerState('waking');
      if (!canRetry || attempt >= RETRY_DELAYS.length) throw new ApiError(503, { code: 'SERVER_STARTING', message: 'Máy chủ đang khởi động hoặc quá tải. Vui lòng thử lại sau ít phút.' });
      await sleep(RETRY_DELAYS[attempt]);
      continue;
    }
    setServerState('ok');
    if (!type.includes('application/json')) return response;
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 401 && unauthorizedHandler && !path.startsWith('/auth/')) unauthorizedHandler();
      throw new ApiError(response.status, data);
    }
    if (data && data.csrf_token) setCSRF(data.csrf_token);
    return data;
  }
}

export const get = (path: string, signal?: AbortSignal) => api(path, { signal });
export const post = (path: string, body?: any, key?: string) => api(path, { method: 'POST', body, key });
export const patch = (path: string, body?: any, key?: string) => api(path, { method: 'PATCH', body, key });
export const put = (path: string, body?: any, key?: string) => api(path, { method: 'PUT', body, key });
export const del = (path: string, body?: any, key?: string) => api(path, { method: 'DELETE', body, key });

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Có lỗi xảy ra. Vui lòng thử lại.';
}

export function query(params: Row): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return entries.length ? '?' + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString() : '';
}

export async function download(path: string, fallbackName: string) {
  const response = await fetch(`/api/v1${path}`, { credentials: 'include' });
  if (!response.ok) {
    let message = 'Không tải được tệp.';
    try { message = (await response.json()).message || message; } catch { /* không phải JSON */ }
    throw new Error(message);
  }
  const disposition = response.headers.get('content-disposition') || '';
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = match ? match[1] : fallbackName; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function deviceLabel(): string {
  const ua = navigator.userAgent;
  const os = /iPhone|iPad/.test(ua) ? 'iPhone/iPad' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'Mac' : 'Thiết bị';
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : /Firefox\//.test(ua) ? 'Firefox' : 'Trình duyệt';
  return `${os} · ${browser}`;
}
