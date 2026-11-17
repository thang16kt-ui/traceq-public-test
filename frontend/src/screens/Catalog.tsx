// Danh mục: loại lỗi, sản phẩm, lô, ca/công đoạn. Mục chưa dùng thì xóa hẳn; đã dùng thì "Ngừng sử dụng" + "Khôi phục".
import { useState } from 'react';
import type { ReactNode } from 'react';
import { del, get, patch, post, put, query } from '../lib/api';
import type { Row } from '../lib/api';
import { formatMoney, formatTime } from '../lib/format';
import { navigate } from '../lib/router';
import { QuickSession } from './Create';
import { Badge, Button, Card, Chips, ConfirmDialog, Empty, ErrorBox, Loading, Modal, PageHeader, Pager, Select, TextInput, useLoad, useToast } from '../ui/components';

type State = 'active' | 'inactive' | 'all';
export const STATE_OPTIONS: { value: State; label: string }[] = [{ value: 'active', label: 'Đang dùng' }, { value: 'inactive', label: 'Ngừng sử dụng' }, { value: 'all', label: 'Tất cả' }];

/** Xóa (hẳn nếu chưa dùng / ngừng dùng nếu đã dùng) – luôn có hộp xác nhận. */
export function DeleteDialog({ kind, item, label, onClose, onDone }: { kind: string; item: Row; label: string; onClose: () => void; onDone: (op: string) => void }) {
  return <ConfirmDialog title={item.is_used ? `Ngừng sử dụng “${label}”?` : `Xóa “${label}”?`} danger requireReason
    confirmLabel={item.is_used ? 'Ngừng sử dụng' : 'Xóa hẳn'}
    message={item.is_used
      ? <p>Mục này đã được dùng trong dữ liệu. Hệ thống sẽ <strong>ngừng sử dụng</strong> (không xóa) để giữ lịch sử; bản ghi cũ vẫn hiện đúng tên. Bạn có thể khôi phục sau.</p>
      : <p>Mục này chưa được dùng ở đâu nên sẽ bị <strong>xóa hẳn</strong>. Thao tác không hoàn tác được.</p>}
    onClose={onClose}
    onConfirm={async (reason) => { const r = await del(`/${kind}/${item.id}`, { row_version: item.row_version, reason }); onDone(r.operation); }} />;
}

export function HistoryDialog({ kind, item, title, onClose }: { kind: string; item: Row; title: string; onClose: () => void }) {
  const { data, loading, error } = useLoad((s) => get(`/${kind}/${item.id}/history`, s), [item.id]);
  const ACTIONS: Row = { create: 'Tạo mới', update: 'Sửa', deactivate: 'Ngừng sử dụng', restore: 'Khôi phục', delete: 'Xóa', update_levels: 'Sửa cài đặt mức' };
  return <Modal title={`Lịch sử: ${title}`} onClose={onClose} wide>
    {loading ? <Loading /> : error ? <ErrorBox error={error} /> : data.items.length ? <ul className="list">{data.items.map((l: Row) => <li key={l.id} className="list-row"><div>
      <strong>{ACTIONS[l.action] || l.action}</strong> · {l.actor_name} · {formatTime(l.created_at)}{l.reason && <p className="muted">Lý do: {l.reason}</p>}</div></li>)}</ul> : <Empty title="Chưa có lịch sử" />}
  </Modal>;
}

function StatusCell({ item }: { item: Row }) {
  return item.effective_active ? <Badge tone="ok">Đang dùng</Badge> : <Badge>Ngừng sử dụng</Badge>;
}

// ---------- Sản phẩm ----------
function ProductForm({ item, onClose, onSaved }: { item?: Row; onClose: () => void; onSaved: () => void }) {
  const supervisors = useLoad((s) => get('/users/options?role=giam_sat', s), []);
  const [v, setV] = useState<Row>({ sku: item?.sku || '', name: item?.name || '', unit_of_measure: item?.unit_of_measure || 'cái', supervisor_id: item?.supervisor_id || '', backup_supervisor_id: item?.backup_supervisor_id || '', unit_cost: item?.unit_cost ?? '', salvage_value: item?.salvage_value ?? '', reason: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (k: string, x: any) => setV((s) => ({ ...s, [k]: x }));
  const submit = async () => {
    setBusy(true); setError('');
    const body: Row = { sku: v.sku, name: v.name, unit_of_measure: v.unit_of_measure, supervisor_id: v.supervisor_id || null, backup_supervisor_id: v.backup_supervisor_id || null, unit_cost: v.unit_cost === '' ? null : String(v.unit_cost), salvage_value: v.salvage_value === '' ? null : String(v.salvage_value) };
    try {
      if (item) await patch(`/product-types/${item.id}`, { ...body, row_version: item.row_version, reason: v.reason || 'Cập nhật sản phẩm' });
      else await post('/product-types', body);
      onSaved(); onClose();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const options = supervisors.data?.items || [];
  return <Modal title={item ? 'Sửa sản phẩm' : 'Thêm sản phẩm'} onClose={onClose} footer={<><Button onClick={onClose}>Hủy bỏ</Button><Button variant="primary" busy={busy} onClick={submit} disabled={!v.sku || !v.name}>Lưu</Button></>}>
    <div className="grid-2">
      <TextInput label="Mã sản phẩm (SKU)" required value={v.sku} onChange={(e) => set('sku', e.target.value)} />
      <TextInput label="Đơn vị tính" value={v.unit_of_measure} onChange={(e) => set('unit_of_measure', e.target.value)} />
    </div>
    <TextInput label="Tên sản phẩm" required value={v.name} onChange={(e) => set('name', e.target.value)} />
    <div className="grid-2">
      <Select label="Giám sát phụ trách" value={v.supervisor_id} onChange={(e) => set('supervisor_id', e.target.value)} hint="Đề xuất của sản phẩm này gửi tới người này.">
        <option value="">— Chưa gán —</option>{options.map((u: Row) => <option key={u.id} value={u.id}>{u.display_name}{u.code ? ` (${u.code})` : ''}</option>)}
      </Select>
      <Select label="Giám sát thay thế" value={v.backup_supervisor_id} onChange={(e) => set('backup_supervisor_id', e.target.value)} hint="Nhận việc khi giám sát chính vắng hoặc quá hạn.">
        <option value="">— Không có —</option>{options.map((u: Row) => <option key={u.id} value={u.id}>{u.display_name}{u.code ? ` (${u.code})` : ''}</option>)}
      </Select>
      <TextInput label="Giá vốn (VND/sản phẩm)" inputMode="decimal" value={v.unit_cost} onChange={(e) => set('unit_cost', e.target.value.replace(/[^\d]/g, ''))} hint="Dùng ước tính chi phí khi Hủy." />
      <TextInput label="Giá trị thu hồi khi tái chế (VND)" inputMode="decimal" value={v.salvage_value} onChange={(e) => set('salvage_value', e.target.value.replace(/[^\d]/g, ''))} hint="Tái chế = giá vốn − giá trị thu hồi." />
    </div>
    {item && <TextInput label="Lý do thay đổi" value={v.reason} onChange={(e) => set('reason', e.target.value)} />}
    {error && <p className="error-text" role="alert">{error}</p>}
  </Modal>;
}

function Products() {
  const toast = useToast();
  const [state, setState] = useState<State>('active');
  const [page, setPage] = useState(1);
  const [modal, setModal] = useState<{ kind: string; item?: Row } | null>(null);
  const { data, loading, error, reload } = useLoad((s) => get('/product-types' + query({ state, page, page_size: 50 }), s), [state, page]);
  return <>
    <div className="toolbar"><Chips label="Trạng thái" value={state} onChange={(x) => { setState(x); setPage(1); }} options={STATE_OPTIONS} /><Button variant="primary" onClick={() => setModal({ kind: 'form' })}>Thêm sản phẩm</Button></div>
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <>
      <div className="table-wrap"><table className="table"><thead><tr><th>Sản phẩm</th><th>Giám sát</th><th className="num">Giá vốn</th><th>Trạng thái</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
        <tbody>{data.items.map((p: Row) => <tr key={p.id}>
          <td><strong>{p.name}</strong><div className="muted">{p.sku} · {p.unit_of_measure}</div></td>
          <td>{p.supervisor ? p.supervisor.display_name : <Badge tone="warn">Chưa gán giám sát</Badge>}{p.backup_supervisor && <div className="muted">Thay thế: {p.backup_supervisor.display_name}</div>}</td>
          <td className="num">{formatMoney(p.unit_cost)}</td>
          <td><StatusCell item={p} /></td>
          <td><div className="row-actions">
            <Button onClick={() => setModal({ kind: 'form', item: p })}>Sửa</Button>
            {p.is_active ? <Button variant="danger" onClick={() => setModal({ kind: 'delete', item: p })}>{p.is_used ? 'Ngừng sử dụng' : 'Xóa'}</Button>
              : <Button onClick={() => setModal({ kind: 'restore', item: p })}>Khôi phục</Button>}
            <Button variant="ghost" onClick={() => setModal({ kind: 'history', item: p })}>Lịch sử</Button>
          </div></td></tr>)}</tbody></table></div>
      {!data.items.length && <Empty title="Chưa có sản phẩm" />}
      <Pager page={page} pageSize={50} total={data.total} onPage={setPage} />
    </>}
    {modal?.kind === 'form' && <ProductForm item={modal.item} onClose={() => setModal(null)} onSaved={() => { toast('Đã lưu sản phẩm'); reload(); }} />}
    {modal?.kind === 'delete' && <DeleteDialog kind="product-types" item={modal.item!} label={modal.item!.name} onClose={() => setModal(null)} onDone={(op) => { toast(op === 'delete' ? 'Đã xóa' : 'Đã ngừng sử dụng'); reload(); }} />}
    {modal?.kind === 'restore' && <ConfirmDialog title={`Khôi phục “${modal.item!.name}”?`} requireReason confirmLabel="Khôi phục" onClose={() => setModal(null)} onConfirm={async (reason) => { await post(`/product-types/${modal.item!.id}/restore`, { row_version: modal.item!.row_version, reason }); toast('Đã khôi phục'); reload(); }} />}
    {modal?.kind === 'history' && <HistoryDialog kind="product-types" item={modal.item!} title={modal.item!.name} onClose={() => setModal(null)} />}
  </>;
}

// ---------- Lô ----------
function Batches() {
  const toast = useToast();
  const [state, setState] = useState<State>('active');
  const [modal, setModal] = useState<{ kind: string; item?: Row } | null>(null);
  const [form, setForm] = useState<Row>({ product_type_id: '', lot_code: '', reason: '' });
  const [error, setError] = useState('');
  const products = useLoad((s) => get('/product-types?state=active&page_size=100', s), []);
  const { data, loading, error: loadError, reload } = useLoad((s) => get('/batches' + query({ state, page_size: 100 }), s), [state]);
  const save = async () => {
    setError('');
    try {
      if (modal?.item) await patch(`/batches/${modal.item.id}`, { product_type_id: form.product_type_id, lot_code: form.lot_code, row_version: modal.item.row_version, reason: form.reason || 'Sửa lô' });
      else await post('/batches', { product_type_id: form.product_type_id, lot_code: form.lot_code });
      toast('Đã lưu lô'); setModal(null); reload();
    } catch (e: any) { setError(e.message); }
  };
  const open = (item?: Row) => { setError(''); setForm({ product_type_id: item?.product_type_id || products.data?.items?.[0]?.id || '', lot_code: item?.lot_code || '', reason: '' }); setModal({ kind: 'form', item }); };
  return <>
    <div className="toolbar"><Chips label="Trạng thái" value={state} onChange={setState} options={STATE_OPTIONS} /><Button variant="primary" onClick={() => open()}>Thêm lô</Button></div>
    {loading && !data ? <Loading /> : loadError ? <ErrorBox error={loadError} onRetry={reload} /> : <div className="table-wrap"><table className="table">
      <thead><tr><th>Lô</th><th>Sản phẩm</th><th>Trạng thái</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
      <tbody>{data.items.map((b: Row) => <tr key={b.id}><td><strong>{b.lot_code}</strong></td><td>{b.product_type?.name}</td><td><StatusCell item={b} /></td>
        <td><div className="row-actions"><Button onClick={() => open(b)}>Sửa</Button>
          {b.is_active ? <Button variant="danger" onClick={() => setModal({ kind: 'delete', item: b })}>{b.is_used ? 'Ngừng sử dụng' : 'Xóa'}</Button> : <Button onClick={() => setModal({ kind: 'restore', item: b })}>Khôi phục</Button>}
          <Button variant="ghost" onClick={() => setModal({ kind: 'history', item: b })}>Lịch sử</Button></div></td></tr>)}</tbody></table>
      {!data.items.length && <Empty title="Chưa có lô" />}</div>}
    {modal?.kind === 'form' && <Modal title={modal.item ? 'Sửa lô' : 'Thêm lô'} onClose={() => setModal(null)} footer={<><Button onClick={() => setModal(null)}>Hủy bỏ</Button><Button variant="primary" onClick={save} disabled={!form.product_type_id || !form.lot_code}>Lưu</Button></>}>
      <Select label="Sản phẩm" required value={form.product_type_id} onChange={(e) => setForm({ ...form, product_type_id: e.target.value })}>{(products.data?.items || []).map((p: Row) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
      <TextInput label="Mã lô" required value={form.lot_code} onChange={(e) => setForm({ ...form, lot_code: e.target.value })} />
      {modal.item && <TextInput label="Lý do thay đổi" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />}
      {error && <p className="error-text" role="alert">{error}</p>}
    </Modal>}
    {modal?.kind === 'delete' && <DeleteDialog kind="batches" item={modal.item!} label={modal.item!.lot_code} onClose={() => setModal(null)} onDone={(op) => { toast(op === 'delete' ? 'Đã xóa' : 'Đã ngừng sử dụng'); reload(); }} />}
    {modal?.kind === 'restore' && <ConfirmDialog title={`Khôi phục lô ${modal.item!.lot_code}?`} requireReason confirmLabel="Khôi phục" onClose={() => setModal(null)} onConfirm={async (reason) => { await post(`/batches/${modal.item!.id}/restore`, { row_version: modal.item!.row_version, reason }); toast('Đã khôi phục'); reload(); }} />}
    {modal?.kind === 'history' && <HistoryDialog kind="batches" item={modal.item!} title={modal.item!.lot_code} onClose={() => setModal(null)} />}
  </>;
}

// ---------- Danh sách ca / công đoạn / dây chuyền ----------
function NameList({ settingKey, title, values, onSaved }: { settingKey: string; title: string; values: string[]; onSaved: () => void }) {
  const toast = useToast();
  const [text, setText] = useState(values.join('\n'));
  const [error, setError] = useState('');
  const save = async () => {
    setError('');
    try { await put(`/settings/${settingKey}`, { value: text.split('\n').map((x) => x.trim()).filter(Boolean), reason: `Cập nhật ${title.toLowerCase()}` }); toast('Đã lưu'); onSaved(); }
    catch (e: any) { setError(e.message); }
  };
  return <Card title={title}>
    <label className="field"><span className="field-label">Mỗi dòng một mục</span><textarea rows={5} value={text} onChange={(e) => setText(e.target.value)} /></label>
    {error && <p className="error-text" role="alert">{error}</p>}
    <Button variant="primary" onClick={save}>Lưu {title.toLowerCase()}</Button>
  </Card>;
}

function Lists() {
  const { data, loading, error, reload } = useLoad((s) => get('/settings', s), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const value = (k: string) => data.items.find((i: Row) => i.key === k)?.value || [];
  return <div className="grid-3">
    <NameList settingKey="lines" title="Dây chuyền" values={value('lines')} onSaved={reload} />
    <NameList settingKey="shifts" title="Ca" values={value('shifts')} onSaved={reload} />
    <NameList settingKey="stages" title="Công đoạn" values={value('stages')} onSaved={reload} />
  </div>;
}

export function ProductsScreen({ tab: initial }: { tab?: string }) {
  const [tab, setTab] = useState(initial || 'san-pham');
  const tabs: Record<string, ReactNode> = { 'san-pham': <Products />, 'lo': <Batches />, 'ca': <Lists />, 'dot-kiem': <SessionsTab /> };
  return <div className="page">
    <PageHeader title="Sản phẩm/lô/ca" subtitle="Sản phẩm, giám sát phụ trách, lô, ca, công đoạn và đợt kiểm tra" />
    <Chips label="Mục" value={tab} onChange={setTab} options={[{ value: 'san-pham', label: 'Sản phẩm' }, { value: 'lo', label: 'Lô' }, { value: 'ca', label: 'Ca/công đoạn' }, { value: 'dot-kiem', label: 'Đợt kiểm tra' }]} />
    <div style={{ marginTop: 12 }}>{tabs[tab]}</div>
  </div>;
}

function SessionsTab() {
  const toast = useToast();
  const [status, setStatus] = useState<'open' | 'closed'>('open');
  const [modal, setModal] = useState<Row | 'new' | null>(null);
  const [count, setCount] = useState('');
  const { data, loading, error, reload } = useLoad((s) => get('/inspection-sessions' + query({ status, page_size: 100 }), s), [status]);
  return <>
    <div className="toolbar"><Chips label="Trạng thái đợt" value={status} onChange={setStatus} options={[{ value: 'open', label: 'Đang kiểm' }, { value: 'closed', label: 'Đã đóng' }]} />
      <Button variant="primary" onClick={() => setModal('new')}>Tạo đợt kiểm tra</Button></div>
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <div className="table-wrap"><table className="table">
      <thead><tr><th>Bắt đầu</th><th>Sản phẩm / lô</th><th>Ca · công đoạn</th><th className="num">Đã kiểm</th><th className="num">SP lỗi</th><th>Tình trạng</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
      <tbody>{data.items.map((s: Row) => <tr key={s.id}><td>{formatTime(s.started_at)}</td><td>{s.batch.product_type.name}<div className="muted">Lô {s.batch.lot_code}</div></td>
        <td>{s.shift} · {s.stage}<div className="muted">{s.line}</div></td><td className="num">{s.inspected_count ?? '—'}</td><td className="num">{s.defective_count}</td>
        <td><Badge tone={s.status === 'open' ? 'ok' : 'neutral'}>{s.status === 'open' ? 'đang kiểm' : 'đã đóng'}</Badge></td>
        <td>{s.status === 'open' && <Button onClick={() => { setCount(s.inspected_count ?? ''); setModal(s); }}>Nhập số đã kiểm / đóng đợt</Button>}</td></tr>)}</tbody></table>
      {!data.items.length && <Empty title="Không có đợt kiểm tra" />}</div>}
    {modal === 'new' && <Modal title="Tạo đợt kiểm tra" onClose={() => setModal(null)}><QuickSession onCreated={() => { setModal(null); toast('Đã tạo đợt'); reload(); }} /></Modal>}
    {modal && modal !== 'new' && <Modal title="Đợt kiểm tra" onClose={() => setModal(null)} footer={<>
      <Button onClick={async () => { try { await patch(`/inspection-sessions/${(modal as Row).id}`, { row_version: (modal as Row).row_version, inspected_count: count === '' ? null : Number(count), reason: 'Cập nhật số đã kiểm' }); toast('Đã lưu'); setModal(null); reload(); } catch (e: any) { toast(e.message, 'error'); } }}>Lưu số đã kiểm</Button>
      <Button variant="primary" onClick={async () => { try { await patch(`/inspection-sessions/${(modal as Row).id}`, { row_version: (modal as Row).row_version, inspected_count: count === '' ? null : Number(count), status: 'closed', reason: 'Đóng đợt kiểm tra cuối ca' }); toast('Đã đóng đợt'); setModal(null); reload(); } catch (e: any) { toast(e.message, 'error'); } }}>Đóng đợt</Button></>}>
      <TextInput label="Số sản phẩm đã kiểm trong đợt" inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value.replace(/[^\d]/g, ''))} hint="Dùng làm mẫu số tính tỷ lệ sản phẩm lỗi. Phải ≥ số sản phẩm lỗi đã xác nhận." />
    </Modal>}
  </>;
}

// ---------- Thiết lập (Quản lý) ----------
const GENERAL: { key: string; type: 'money' | 'int' | 'time' }[] = [
  { key: 'approval_threshold', type: 'money' }, { key: 'hourly_rate', type: 'money' }, { key: 'cost_min_samples', type: 'int' },
  { key: 'cost_window_days', type: 'int' }, { key: 'end_of_day_time', type: 'time' }, { key: 'cost_reminder_days', type: 'int' },
  { key: 'escalation_hours', type: 'int' }, { key: 'repeat_defect_count', type: 'int' },
];

function GeneralSettings() {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get('/settings', s), []);
  const [draft, setDraft] = useState<Row>({});
  const [errors, setErrors] = useState<Row>({});
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const items: Row = Object.fromEntries(data.items.map((i: Row) => [i.key, i]));
  const save = async (key: string, type: string) => {
    const raw = draft[key];
    if (raw === undefined) return;
    try {
      await put(`/settings/${key}`, { value: type === 'int' ? parseInt(raw, 10) : type === 'money' ? String(raw).replace(/[^\d]/g, '') : raw, reason: 'Cập nhật thiết lập' });
      toast('Đã lưu'); setErrors({ ...errors, [key]: '' }); setDraft({ ...draft, [key]: undefined }); reload();
    } catch (e: any) { setErrors({ ...errors, [key]: e.message }); }
  };
  return <Card title="Ngưỡng và nhắc việc">
    <div className="grid-2">{GENERAL.map(({ key, type }) => <div key={key}>
      <TextInput label={items[key].label} type={type === 'time' ? 'time' : 'text'} inputMode={type === 'time' ? undefined : 'numeric'}
        value={draft[key] ?? String(items[key].value)} error={errors[key]}
        hint={type === 'money' ? `Hiện tại: ${formatMoney(items[key].value)}` : `Mặc định: ${items[key].default}`}
        onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} onBlur={() => save(key, type)} />
    </div>)}</div>
    <p className="muted">Giá trị được lưu khi rời ô nhập. Mọi thay đổi được ghi vào Nhật ký.</p>
  </Card>;
}

export function SetupHub() {
  const links = [
    ['/danh-muc', 'Danh mục lỗi', 'Loại lỗi, mức Nhẹ/Trung bình/Nặng, tiêu chí, giá, hạn xử lý, cờ ưu tiên'],
    ['/san-pham', 'Sản phẩm/lô/ca', 'Sản phẩm, giám sát phụ trách, giá vốn, lô, ca, công đoạn, đợt kiểm tra'],
    ['/tu-dong-duyet', 'Tự động duyệt', 'Chế độ Tắt / Chỉ gợi ý / Tự động cho từng bước'],
    ['/nguoi-dung', 'Người dùng', 'Vai trò, khóa tài khoản, đặt lại mật khẩu, vắng mặt'],
    ['/nhat-ky', 'Nhật ký', 'Mọi thao tác nhạy cảm'],
  ];
  return <div className="page">
    <PageHeader title="Thiết lập" subtitle="Quản lý cài đặt một lần trước khi vận hành" />
    <div className="grid-2">{links.map(([path, title, desc]) => <button key={path} type="button" className="card link-card" onClick={() => navigate(path)}><strong>{title}</strong><span className="muted">{desc}</span></button>)}</div>
    <GeneralSettings />
  </div>;
}
