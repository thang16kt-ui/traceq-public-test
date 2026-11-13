import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { ApiError, deviceLabel, post } from '../lib/api';
import type { Row } from '../lib/api';
import { Alert, Button, Checkbox, TextInput } from '../ui/components';

export default function Login({ onLogin, environment }: { onLogin: (data: Row) => void; environment: string }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      onLogin(await post('/auth/login', { username: username.trim(), password, remember, device_label: deviceLabel() }));
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'Không đăng nhập được');
    } finally { setBusy(false); }
  };
  return <main className="login">
    <form className="login-card" onSubmit={submit} noValidate>
      <div className="brand-block"><span className="logo" aria-hidden>TQ</span><div><h1>TraceQ</h1><p>Ghi nhận và xử lý sản phẩm lỗi</p></div></div>
      {environment === 'demo' && <Alert tone="warn" title="BẢN TEST – dữ liệu mẫu">
        Tài khoản thử: demo.nguoitao, demo.giamsat, demo.captren, demo.quanly, demo.admin. Mật khẩu do người quản trị bản test cung cấp. Không nhập dữ liệu thật.
      </Alert>}
      <TextInput label="Tên đăng nhập hoặc mã nhân viên" autoComplete="username" autoCapitalize="none" required value={username} onChange={(e) => setUsername(e.target.value)} />
      <TextInput label="Mật khẩu" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      <Checkbox label="Ghi nhớ trên thiết bị này (30 ngày)" hint="Chỉ bật trên điện thoại/máy tính của riêng bạn." checked={remember} onChange={(e) => setRemember(e.target.checked)} />
      {error && <p className="error-text" role="alert">{error}</p>}
      <Button type="submit" variant="primary" busy={busy} disabled={!username || !password}>Đăng nhập</Button>
      <p className="muted">Quên mật khẩu? Liên hệ quản lý để được đặt lại.</p>
      <div className="security-note"><ShieldCheck size={18} aria-hidden />
        <p>Thiết bị cá nhân: đặt khóa màn hình cho điện thoại, không cho người khác dùng phiên của bạn. Khi mất máy, báo quản lý để khóa tài khoản và thu hồi phiên từ xa. Dữ liệu chưa gửi trên máy sẽ bị xóa khi đăng xuất.</p>
      </div>
    </form>
  </main>;
}
