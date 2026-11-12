import { useEffect, useState } from 'react';
import { disablePush, enablePush, pushStatus } from '../lib/push';
import { Badge, Button, useToast } from '../ui/components';
import { flushQueue, pendingCounts, pendingProposals } from '../lib/offline';
import type { QueuedProposal } from '../lib/offline';
import { formatTime } from '../lib/format';
// Phần mở rộng màn "Tôi": đồng bộ offline, cài PWA, thông báo đẩy.
export function SyncPanel() {
  const toast = useToast();
  const [counts, setCounts] = useState({ photos: 0, proposals: 0 });
  const [items, setItems] = useState<QueuedProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const refresh = () => { pendingCounts().then(setCounts); pendingProposals().then(setItems); };
  useEffect(() => {
    refresh();
    const on = () => { setOnline(navigator.onLine); refresh(); };
    window.addEventListener('traceq:queue', refresh); window.addEventListener('online', on); window.addEventListener('offline', on);
    return () => { window.removeEventListener('traceq:queue', refresh); window.removeEventListener('online', on); window.removeEventListener('offline', on); };
  }, []);
  const total = counts.photos + counts.proposals;
  return <div className="stack">
    <p><Badge tone={online ? 'ok' : 'error'}>{online ? 'Đang có mạng' : 'Mất mạng'}</Badge> {total ? <Badge tone="warn">{counts.proposals} đề xuất, {counts.photos} ảnh chờ gửi</Badge> : <Badge tone="ok">Đã đồng bộ hết</Badge>}</p>
    {items.map((p) => <p key={p.id} className="muted">Đề xuất serial {p.body.serial_number} lưu lúc {formatTime(p.createdAt)}{p.error ? ` – lỗi: ${p.error}` : ''}</p>)}
    <Button busy={busy} disabled={!total || !online} onClick={async () => { setBusy(true); const left = await flushQueue(); setBusy(false); refresh(); toast(left ? `Còn ${left} mục chưa gửi được` : 'Đã đồng bộ xong', left ? 'error' : 'ok'); }}>Đồng bộ ngay</Button>
    <p className="hint">Dữ liệu chờ gửi lưu trên máy này và bị xóa khi đăng xuất. Hãy đồng bộ trước khi đăng xuất.</p>
  </div>;
}

let deferredPrompt: any = null;
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferredPrompt = e; });

export function InstallButton() {
  const [installed, setInstalled] = useState(window.matchMedia('(display-mode: standalone)').matches);
  const [canPrompt, setCanPrompt] = useState(!!deferredPrompt);
  useEffect(() => {
    const ready = (e: Event) => { e.preventDefault(); deferredPrompt = e; setCanPrompt(true); };
    const done = () => setInstalled(true);
    window.addEventListener('beforeinstallprompt', ready); window.addEventListener('appinstalled', done);
    return () => { window.removeEventListener('beforeinstallprompt', ready); window.removeEventListener('appinstalled', done); };
  }, []);
  if (installed) return <p><Badge tone="ok">Đã cài trên màn hình chính</Badge></p>;
  const ios = /iPhone|iPad/.test(navigator.userAgent);
  return <div className="stack">
    {canPrompt && <Button variant="primary" onClick={async () => { deferredPrompt.prompt(); await deferredPrompt.userChoice; deferredPrompt = null; setCanPrompt(false); }}>Cài TraceQ lên màn hình chính</Button>}
    {!canPrompt && <p className="muted">{ios ? 'Trên iPhone/iPad: mở bằng Safari, bấm nút Chia sẻ rồi chọn “Thêm vào MH chính”.' : 'Mở menu trình duyệt (⋮) và chọn “Cài đặt ứng dụng” hoặc “Thêm vào màn hình chính”.'}</p>}
  </div>;
}
export function PushToggle() {
  const toast = useToast();
  const [state, setState] = useState<string>('loading');
  const [busy, setBusy] = useState(false);
  const refresh = () => pushStatus().then(setState).catch(() => setState('unsupported'));
  useEffect(() => { refresh(); }, []);
  const text: Record<string, string> = { unsupported: 'Thiết bị/trình duyệt này không hỗ trợ thông báo đẩy (cần HTTPS; trên iPhone cần cài ứng dụng lên màn hình chính).',
    disabled: 'Máy chủ chưa cấu hình thông báo đẩy. Thông báo vẫn có trong mục Thông báo.', denied: 'Bạn đã chặn thông báo cho trang này. Mở cài đặt trình duyệt để cho phép.',
    on: 'Thông báo đẩy đang BẬT trên thiết bị này.', off: 'Thông báo đẩy đang TẮT trên thiết bị này.', loading: 'Đang kiểm tra…' };
  return <div className="push-box"><p>{text[state]}</p>
    {state === 'off' && <Button variant="primary" busy={busy} onClick={async () => { setBusy(true); try { await enablePush(); toast('Đã bật thông báo đẩy'); } catch (e: any) { toast(e.message, 'error'); } finally { setBusy(false); refresh(); } }}>Bật thông báo đẩy</Button>}
    {state === 'on' && <Button busy={busy} onClick={async () => { setBusy(true); await disablePush(); setBusy(false); refresh(); }}>Tắt thông báo đẩy</Button>}
  </div>;
}
