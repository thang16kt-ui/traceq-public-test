// Quản lý người dùng: Admin tạo/sửa vai trò; Quản lý đặt lại mật khẩu, khóa, đánh dấu vắng mặt.
import { useState } from 'react';
import { get, patch, post, query } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime, vnDateInput } from '../lib/format';
import { ROLE_LABELS } from '../lib/labels';
import { hasRole, useSession } from '../lib/session';
import { Badge, Button, Chips, ConfirmDialog, Empty, ErrorBox, Loading, Modal, PageHeader, Pager, TextInput, useLoad, useToast } from '../ui/components';

const ROLE_KEYS = Object.keys(ROLE_LABELS);

function RolePicker({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return <fieldset className="segmented"><legend>Vai trò (chọn một hoặc nhiều)</legend>
    <div className="segmented-row">{ROLE_KEYS.map((r) => <label key={r} className={`seg ${value.includes(r) ? 'active' : ''}`}>
      <input type="checkbox" checked={value.includes(r)} onChange={(e) => onChange(e.target.checked ? [...value, r] : value.filter((x) => x !== r))} />
      <span>{ROLE_LABELS[r]}</span></label>)}</div></fieldset>;
}

function UserForm({ user, onClose, onSaved }: { user?: Row; onClose: () => void; onSaved: () => void }) {
  const [values, setValues] = useState({ username: user?.username || '', code: user?.code || '', display_name: user?.display_name || '', roles: user?.roles || ['nguoi_tao'], password: '', reason: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fields, setFields] = useState<Row>({});
  const set = (k: string, v: any) => setValues((s) => ({ ...s, [k]: v }));
  const submit = async () => {
    setBusy(true); setError(''); setFields({});
    try {
      if (user) await patch(`/users/${user.id}`, { row_version: user.row_version, display_name: values.display_name, code: values.code || null, roles: values.roles, reason: values.reason || 'Cập nhật thông tin người dùng' });
      else await post('/users', { username: values.username, code: values.code || null, display_name: values.display_name, roles: values.roles, password: values.password });
      onSaved(); onClose();
    } catch (e: any) { setError(e.message); setFields(e.fields || {}); } finally { setBusy(false); }
  };
  return <Modal title={user ? 'Sửa người dùng' : 'Thêm người dùng'} onClose={onClose} footer={<><Button onClick={onClose}>Hủy bỏ</Button><Button variant="primary" busy={busy} onClick={submit} disabled={!values.roles.length}>Lưu</Button></>}>
    {!user && <TextInput label="Tên đăng nhập" required value={values.username} onChange={(e) => set('username', e.target.value)} hint="Chữ không dấu, số, dấu chấm/gạch." error={fields.username} />}
    <TextInput label="Mã nhân viên" value={values.code} onChange={(e) => set('code', e.target.value)} hint="Dùng để đăng nhập thay tên đăng nhập." error={fields.code} />
    <TextInput label="Họ tên" required value={values.display_name} onChange={(e) => set('display_name', e.target.value)} />
    <RolePicker value={values.roles} onChange={(v) => set('roles', v)} />
    {!user && <TextInput label="Mật khẩu ban đầu" type="password" autoComplete="new-password" required value={values.password} onChange={(e) => set('password', e.target.value)} hint="Người dùng phải đổi mật khẩu ở lần đăng nhập đầu." error={fields.password} />}
    {user && <TextInput label="Lý do thay đổi" value={values.reason} onChange={(e) => set('reason', e.target.value)} />}
    {error && <p className="error-text" role="alert">{error}</p>}
  </Modal>;
}

function ResetPassword({ user, onClose, onSaved }: { user: Row; onClose: () => void; onSaved: () => void }) {
  const [password, setPassword] = useState('');
  const [reason, setReason] = useState('Người dùng quên mật khẩu');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async () => {
    setBusy(true); setError('');
    try { await post(`/users/${user.id}/reset-password`, { new_password: password, reason }); onSaved(); onClose(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return <Modal title={`Đặt lại mật khẩu: ${user.display_name}`} onClose={onClose} footer={<><Button onClick={onClose}>Hủy bỏ</Button><Button variant="primary" busy={busy} onClick={submit}>Đặt lại mật khẩu</Button></>}>
    <p>Mọi thiết bị của người này sẽ bị đăng xuất. Họ phải đổi mật khẩu ở lần đăng nhập tới. Hãy đưa mật khẩu tạm trực tiếp, không gửi qua nhóm chat.</p>
    <TextInput label="Mật khẩu tạm" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} hint="Ít nhất 10 ký tự." />
    <TextInput label="Lý do" required value={reason} onChange={(e) => setReason(e.target.value)} />
    {error && <p className="error-text" role="alert">{error}</p>}
  </Modal>;
}

function Away({ user, onClose, onSaved }: { user: Row; onClose: () => void; onSaved: () => void }) {
  const [until, setUntil] = useState(user.away_until ? vnDateInput(new Date(user.away_until)) : vnDateInput(new Date(Date.now() + 86400000)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async (clear: boolean) => {
    setBusy(true); setError('');
    try {
      await patch(`/users/${user.id}`, clear ? { row_version: user.row_version, clear_away: true, reason: 'Đã quay lại làm việc' } : { row_version: user.row_version, away_until: `${until}T23:59:59+07:00`, reason: 'Vắng mặt, chuyển duyệt cho giám sát thay thế' });
      onSaved(); onClose();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return <Modal title={`Vắng mặt: ${user.display_name}`} onClose={onClose} footer={<>{user.away_until && <Button onClick={() => save(true)} busy={busy}>Đã quay lại</Button>}<Button variant="primary" busy={busy} onClick={() => save(false)}>Lưu</Button></>}>
    <p>Trong thời gian vắng, đề xuất của sản phẩm do người này giám sát sẽ chuyển cho giám sát thay thế (cài ở Sản phẩm).</p>
    <TextInput label="Vắng đến hết ngày" type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
    {error && <p className="error-text" role="alert">{error}</p>}
  </Modal>;
}

function Sessions({ user, onClose }: { user: Row; onClose: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get(`/users/${user.id}/sessions`, s), [user.id]);
  const [confirm, setConfirm] = useState(false);
  return <Modal title={`Thiết bị của ${user.display_name}`} onClose={onClose} footer={<Button variant="danger" onClick={() => setConfirm(true)}>Đăng xuất mọi thiết bị</Button>}>
    {loading ? <Loading /> : error ? <ErrorBox error={error} /> : (data.items.length ? <ul className="list">{data.items.map((s: Row) => <li key={s.id} className="list-row"><div><strong>{s.device_label}</strong><p className="muted">Gần nhất {formatTime(s.last_seen_at)}</p></div></li>)}</ul> : <Empty title="Không có thiết bị nào đang đăng nhập" />)}
    {confirm && <ConfirmDialog title="Đăng xuất mọi thiết bị" danger requireReason confirmLabel="Đăng xuất" onClose={() => setConfirm(false)}
      onConfirm={async (reason) => { await post(`/users/${user.id}/sessions/revoke-all`, { reason }); toast('Đã đăng xuất mọi thiết bị'); reload(); }} />}
  </Modal>;
}

export default function Users() {
  const { user: me } = useSession();
  const toast = useToast();
  const isAdmin = hasRole(me, 'admin');
  const [state, setState] = useState<'active' | 'inactive' | 'all'>('active');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ kind: string; user?: Row } | null>(null);
  const { data, loading, error, reload } = useLoad((s) => get('/users' + query({ state, search, page, page_size: 50 }), s), [state, search, page]);
  const done = (text: string) => () => { toast(text); reload(); };
  return <div className="page">
    <PageHeader title="Người dùng" subtitle="Vai trò, khóa tài khoản và đặt lại mật khẩu" actions={isAdmin && <Button variant="primary" onClick={() => setModal({ kind: 'create' })}>Thêm người dùng</Button>} />
    <div className="toolbar">
      <Chips label="Trạng thái" value={state} onChange={(v) => { setState(v); setPage(1); }} options={[{ value: 'active', label: 'Đang hoạt động' }, { value: 'inactive', label: 'Đã vô hiệu hóa' }, { value: 'all', label: 'Tất cả' }]} />
      <input className="search" type="search" placeholder="Tìm tên, mã nhân viên…" aria-label="Tìm người dùng" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} />
    </div>
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Họ tên</th><th>Mã NV</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
        <tbody>{data.items.map((u: Row) => <tr key={u.id}>
          <td><strong>{u.display_name}</strong><div className="muted">{u.username}</div></td>
          <td>{u.code || '—'}</td>
          <td>{u.roles.map((r: string) => <Badge key={r}>{ROLE_LABELS[r]}</Badge>)}</td>
          <td>{!u.is_active ? <Badge>Đã vô hiệu hóa</Badge> : u.locked_at ? <Badge tone="error">Đã khóa</Badge> : u.temporarily_locked ? <Badge tone="warn">Tạm khóa (sai mật khẩu)</Badge> : <Badge tone="ok">Hoạt động</Badge>}
            {u.away_until && <Badge tone="warn">Vắng đến {formatTime(u.away_until)}</Badge>}{u.must_change_password && <Badge>Chờ đổi mật khẩu</Badge>}</td>
          <td>{formatTime(u.last_login_at)}<div className="muted">{u.active_sessions} thiết bị</div></td>
          <td><div className="row-actions">
            {isAdmin && <Button onClick={() => setModal({ kind: 'edit', user: u })}>Sửa</Button>}
            {(isAdmin || !u.roles.includes('admin')) && <>
              <Button onClick={() => setModal({ kind: 'reset', user: u })}>Đặt lại mật khẩu</Button>
              {u.roles.includes('giam_sat') && <Button onClick={() => setModal({ kind: 'away', user: u })}>Vắng mặt</Button>}
              <Button onClick={() => setModal({ kind: 'sessions', user: u })}>Thiết bị</Button>
              {u.id !== me.id && (u.locked_at || u.temporarily_locked ? <Button onClick={() => setModal({ kind: 'unlock', user: u })}>Mở khóa</Button> : <Button variant="danger" onClick={() => setModal({ kind: 'lock', user: u })}>Khóa</Button>)}
              {isAdmin && u.id !== me.id && <Button onClick={() => setModal({ kind: 'active', user: u })}>{u.is_active ? 'Vô hiệu hóa' : 'Kích hoạt lại'}</Button>}
            </>}
          </div></td>
        </tr>)}</tbody></table></div>
      {!data.items.length && <Empty title="Không có người dùng phù hợp" />}
      <Pager page={page} pageSize={50} total={data.total} onPage={setPage} />
    </>}
    {modal?.kind === 'create' && <UserForm onClose={() => setModal(null)} onSaved={done('Đã tạo người dùng')} />}
    {modal?.kind === 'edit' && <UserForm user={modal.user} onClose={() => setModal(null)} onSaved={done('Đã lưu')} />}
    {modal?.kind === 'reset' && <ResetPassword user={modal.user!} onClose={() => setModal(null)} onSaved={done('Đã đặt lại mật khẩu')} />}
    {modal?.kind === 'away' && <Away user={modal.user!} onClose={() => setModal(null)} onSaved={done('Đã lưu')} />}
    {modal?.kind === 'sessions' && <Sessions user={modal.user!} onClose={() => setModal(null)} />}
    {modal?.kind === 'lock' && <ConfirmDialog title={`Khóa tài khoản ${modal.user!.display_name}`} danger requireReason confirmLabel="Khóa tài khoản" message="Người này bị đăng xuất khỏi mọi thiết bị và không đăng nhập được cho tới khi mở khóa." onClose={() => setModal(null)} onConfirm={async (reason) => { await post(`/users/${modal.user!.id}/lock`, { reason }); done('Đã khóa tài khoản')(); }} />}
    {modal?.kind === 'unlock' && <ConfirmDialog title={`Mở khóa ${modal.user!.display_name}`} requireReason confirmLabel="Mở khóa" onClose={() => setModal(null)} onConfirm={async (reason) => { await post(`/users/${modal.user!.id}/unlock`, { reason }); done('Đã mở khóa')(); }} />}
    {modal?.kind === 'active' && <ConfirmDialog title={modal.user!.is_active ? 'Vô hiệu hóa tài khoản' : 'Kích hoạt lại tài khoản'} danger={modal.user!.is_active} requireReason confirmLabel={modal.user!.is_active ? 'Vô hiệu hóa' : 'Kích hoạt lại'} onClose={() => setModal(null)} onConfirm={async (reason) => { await patch(`/users/${modal.user!.id}`, { row_version: modal.user!.row_version, is_active: !modal.user!.is_active, reason }); done('Đã lưu')(); }} />}
  </div>;
}
