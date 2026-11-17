// Màn "Tôi": hồ sơ, đồng bộ offline, cài PWA, thông báo, mật khẩu, thiết bị, đăng xuất.
import { useState } from 'react';
import { get, patch, post } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { NOTIFY_LABELS, ROLE_LABELS } from '../lib/labels';
import { useSession } from '../lib/session';
import { Badge, Button, Card, Checkbox, ConfirmDialog, ErrorBox, Loading, PageHeader, TextInput, useLoad, useToast } from '../ui/components';
import { SyncPanel, InstallButton, PushToggle } from './MeExtras';

export function ChangePassword({ forced, onDone }: { forced?: boolean; onDone?: () => void }) {
  const toast = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [again, setAgain] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (next !== again) { setError('Mật khẩu nhập lại không khớp'); return; }
    setBusy(true); setError('');
    try {
      const result = await post('/me/password', { current_password: current, new_password: next });
      toast(result.revoked_other_sessions ? `Đã đổi mật khẩu, đăng xuất ${result.revoked_other_sessions} thiết bị khác` : 'Đã đổi mật khẩu');
      setCurrent(''); setNext(''); setAgain(''); onDone?.();
    } catch (err) { setError(err instanceof Error ? err.message : 'Không đổi được mật khẩu'); } finally { setBusy(false); }
  };
  return <form onSubmit={submit} className="stack">
    {forced && <p>Tài khoản của bạn vừa được tạo hoặc đặt lại. Hãy đổi sang mật khẩu riêng để tiếp tục.</p>}
    <TextInput label="Mật khẩu hiện tại" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
    <TextInput label="Mật khẩu mới" type="password" autoComplete="new-password" hint="Ít nhất 10 ký tự, không chứa tên đăng nhập." required value={next} onChange={(e) => setNext(e.target.value)} />
    <TextInput label="Nhập lại mật khẩu mới" type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} />
    {error && <p className="error-text" role="alert">{error}</p>}
    <Button type="submit" variant="primary" busy={busy} disabled={!current || !next}>Đổi mật khẩu</Button>
  </form>;
}

function Devices() {
  const toast = useToast();
  const { data, error, loading, reload } = useLoad((s) => get('/me/sessions', s), []);
  const [confirm, setConfirm] = useState<Row | 'others' | null>(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const items: Row[] = data?.items || [];
  return <>
    <ul className="list">
      {items.map((s) => <li key={s.id} className="list-row">
        <div><strong>{s.device_label}</strong>{s.current && <Badge tone="ok">Thiết bị này</Badge>}{s.remember && <Badge>Ghi nhớ 30 ngày</Badge>}
          <p className="muted">Dùng gần nhất {formatTime(s.last_seen_at)} · hết hạn {formatTime(s.expires_at)}</p></div>
        {!s.current && <Button variant="danger" onClick={() => setConfirm(s)}>Đăng xuất thiết bị</Button>}
      </li>)}
    </ul>
    {items.length > 1 && <Button onClick={() => setConfirm('others')}>Đăng xuất mọi thiết bị khác</Button>}
    {confirm && <ConfirmDialog title="Đăng xuất thiết bị" danger confirmLabel="Đăng xuất"
      message={confirm === 'others' ? 'Mọi thiết bị khác sẽ phải đăng nhập lại.' : `Thiết bị "${(confirm as Row).device_label}" sẽ phải đăng nhập lại.`}
      onClose={() => setConfirm(null)}
      onConfirm={async () => {
        if (confirm === 'others') await post('/me/sessions/revoke-others'); else await post(`/me/sessions/${(confirm as Row).id}/revoke`);
        toast('Đã đăng xuất thiết bị'); reload();
      }} />}
  </>;
}

function NotifyPrefs() {
  const { user, refreshUser } = useSession();
  const toast = useToast();
  const prefs: Row = user.notify_prefs || {};
  const toggle = async (key: string, value: boolean) => {
    try { await patch('/me/preferences', { notify_prefs: { ...prefs, [key]: value } }); await refreshUser(); }
    catch (e) { toast(e instanceof Error ? e.message : 'Không lưu được', 'error'); }
  };
  return <div className="stack">
    <Checkbox label={NOTIFY_LABELS.uu_tien} checked disabled hint="Không tắt được: lỗi ưu tiên luôn được báo ngay." />
    {Object.keys(NOTIFY_LABELS).filter((k) => k !== 'uu_tien').map((k) =>
      <Checkbox key={k} label={NOTIFY_LABELS[k]} checked={prefs[k] !== false} onChange={(e) => toggle(k, e.target.checked)} />)}
    <PushToggle />
  </div>;
}

export default function Me() {
  const { user, activeRole, setActiveRole, logout } = useSession();
  const [busy, setBusy] = useState(false);
  return <div className="page">
    <PageHeader title="Tôi" subtitle={user.display_name} />
    <div className="grid-2">
      <Card title="Hồ sơ">
        <dl className="kv">
          <dt>Họ tên</dt><dd>{user.display_name}</dd>
          <dt>Tên đăng nhập</dt><dd>{user.username}</dd>
          <dt>Mã nhân viên</dt><dd>{user.code || '—'}</dd>
          <dt>Vai trò</dt><dd>{user.roles.map((r: string) => <Badge key={r}>{ROLE_LABELS[r]}</Badge>)}</dd>
        </dl>
        {user.roles.length > 1 && <div className="field"><span className="field-label">Chế độ làm việc</span>
          <div className="chips">{user.roles.map((r: string) => <button key={r} type="button" className={`chip ${activeRole === r ? 'active' : ''}`} aria-pressed={activeRole === r} onClick={() => setActiveRole(r)}>{ROLE_LABELS[r]}</button>)}</div>
          <p className="hint">Đổi thanh điều hướng theo vai trò đang làm.</p></div>}
      </Card>
      <Card title="Đồng bộ dữ liệu offline"><SyncPanel /></Card>
      <Card title="Ứng dụng trên màn hình chính"><InstallButton /></Card>
      <Card title="Thông báo"><NotifyPrefs /></Card>
      <Card title="Đổi mật khẩu"><ChangePassword /></Card>
      <Card title="Vân tay / Face ID"><p className="muted">Chưa hỗ trợ trong phiên bản này. Hãy dùng mật khẩu và khóa màn hình của điện thoại.</p></Card>
      <Card title="Thiết bị đang đăng nhập"><Devices /></Card>
    </div>
    <Button variant="danger" className="block" busy={busy} onClick={async () => { setBusy(true); await logout(); }}>Đăng xuất</Button>
  </div>;
}
