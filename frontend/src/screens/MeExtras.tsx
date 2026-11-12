import { useEffect, useState } from 'react';
import { disablePush, enablePush, pushStatus } from '../lib/push';
import { Button, useToast } from '../ui/components';
// Phần mở rộng màn "Tôi" – được hoàn thiện ở hạng mục 10 (Web Push) và 13 (PWA/offline).
export function SyncPanel() {
  return <p className="muted">Chế độ làm việc offline chưa bật trong phiên bản này. Dữ liệu được gửi thẳng lên máy chủ.</p>;
}
export function InstallButton() {
  return <p className="muted">Cài ứng dụng lên màn hình chính sẽ có ở phiên bản sau.</p>;
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
