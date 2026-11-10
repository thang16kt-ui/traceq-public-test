export type Row = Record<string, any>;
let csrfToken = '';
export function setCSRF(value: string) {csrfToken = value || '';}
export class ApiError extends Error {status: number; code: string; requestId: string; constructor(status:number, data:Row){super(data.message || data.detail || `Yêu cầu thất bại (${status})`);this.status=status;this.code=data.code || '';this.requestId=data.request_id || '';}}
export async function api(path:string, init:RequestInit = {}, key?:string):Promise<any>{
  const headers = new Headers(init.headers);
  if(init.body && !(init.body instanceof FormData))headers.set('Content-Type','application/json');
  if(init.method && !['GET','HEAD','OPTIONS'].includes(init.method.toUpperCase())){
    const cookie = document.cookie.split('; ').find(s=>s.startsWith('csrf_token='));
    if(csrfToken || cookie)headers.set('X-CSRF-Token',csrfToken || decodeURIComponent(cookie!.slice(11)));
    if(key)headers.set('Idempotency-Key',key);
  }
  const response = await fetch(`/api/v1${path}`,{...init,headers,credentials:'include'});
  const contentType=response.headers.get('content-type') || '';
  if(!contentType.includes('application/json'))throw new ApiError(response.status || 503,{message:'Chưa kết nối được API. Hãy chạy máy chủ hoặc mở bản minh họa chỉ đọc.'});
  const data=await response.json();
  if(!response.ok)throw new ApiError(response.status,data);
  if(data.csrf_token)setCSRF(data.csrf_token);
  return data;
}
export function rows(data:any):Row[]{return Array.isArray(data)?data:data?.items || data?.data || [];}
export function formatNumber(value:any){return value == null?'—':Number(value).toLocaleString('vi-VN',{maximumFractionDigits:2});}
export function formatTime(value:any){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?String(value):d.toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});}
export function errorMessage(e:unknown){return e instanceof Error?e.message:'Có lỗi xảy ra. Vui lòng thử lại.';}
export async function download(path:string,name:string){const response=await fetch(`/api/v1${path}`,{credentials:'include'});if(!response.ok)throw new Error('Không thể tải tệp. Vui lòng kiểm tra quyền truy cập.');const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);}
