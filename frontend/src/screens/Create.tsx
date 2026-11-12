// Tạo đề xuất: quét QR/nhập serial → tự điền sản phẩm/lô/ca/công đoạn → mục lỗi (mức BẮT BUỘC chọn) → Lưu nháp / Xem tờ tổng quan.
import { useEffect, useMemo, useState } from 'react';
import { Plus, QrCode, Trash2 } from 'lucide-react';
import { ApiError, get, patch, post, uuid } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { LEVEL_LABELS, LEVELS } from '../lib/labels';
import { navigate } from '../lib/router';
import { safeStorage, useSession } from '../lib/session';
import { Alert, Badge, Button, Card, ErrorBox, Loading, PageHeader, Segmented, Select, Stepper, TextArea, TextInput, useLoad, useToast } from '../ui/components';
import { QrScanner } from './Scan';
import { cachedGet, enqueueProposal } from '../lib/offline';
import { compressImage } from '../lib/image';
import { uploadPhoto } from './Evidence';
import { Camera } from 'lucide-react';

interface Item { key: string; defect_type_id: string; occurrence_count: number; level: string; note: string; photos?: File[] }
const newItem = (): Item => ({ key: uuid(), defect_type_id: '', occurrence_count: 1, level: '', note: '', photos: [] });

export function QuickSession({ onCreated, batchId }: { onCreated: (s: Row) => void; batchId?: string }) {
  const settings = useLoad((s) => cachedGet('/settings', s), []);
  const batches = useLoad((s) => cachedGet('/batches?state=active&page_size=100', s), []);
  const [v, setV] = useState<Row>({ batch_id: batchId || '', line: '', shift: '', stage: '', inspected_count: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const list = (k: string) => settings.data?.items.find((i: Row) => i.key === k)?.value || [];
  useEffect(() => {
    if (settings.data) setV((x) => ({ ...x, line: x.line || list('lines')[0] || '', shift: x.shift || list('shifts')[0] || '', stage: x.stage || list('stages')[0] || '' }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.data]);
  const create = async () => {
    setBusy(true); setError('');
    try { onCreated(await post('/inspection-sessions', { batch_id: v.batch_id, line: v.line, shift: v.shift, stage: v.stage, inspected_count: v.inspected_count === '' ? null : Number(v.inspected_count) })); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return <div className="quick-session">
    <Select label="Lô" required value={v.batch_id} onChange={(e) => setV({ ...v, batch_id: e.target.value })}>
      <option value="">— Chọn lô —</option>{(batches.data?.items || []).map((b: Row) => <option key={b.id} value={b.id}>{b.lot_code} · {b.product_type?.name}</option>)}
    </Select>
    <div className="grid-3">
      <Select label="Dây chuyền" value={v.line} onChange={(e) => setV({ ...v, line: e.target.value })}>{list('lines').map((x: string) => <option key={x}>{x}</option>)}</Select>
      <Select label="Ca" value={v.shift} onChange={(e) => setV({ ...v, shift: e.target.value })}>{list('shifts').map((x: string) => <option key={x}>{x}</option>)}</Select>
      <Select label="Công đoạn" value={v.stage} onChange={(e) => setV({ ...v, stage: e.target.value })}>{list('stages').map((x: string) => <option key={x}>{x}</option>)}</Select>
    </div>
    <TextInput label="Số sản phẩm đã kiểm (có thể nhập sau)" inputMode="numeric" value={v.inspected_count} onChange={(e) => setV({ ...v, inspected_count: e.target.value.replace(/[^\d]/g, '') })} />
    {error && <p className="error-text" role="alert">{error}</p>}
    <Button variant="primary" busy={busy} disabled={!v.batch_id} onClick={create}>Tạo đợt kiểm tra</Button>
  </div>;
}

function ItemEditor({ item, types, onChange, onRemove, index, canRemove, errors }: { item: Item; types: Row[]; onChange: (i: Item) => void; onRemove: () => void; index: number; canRemove: boolean; errors: Row }) {
  const type = types.find((t) => t.id === item.defect_type_id);
  const levels = type ? type.levels.filter((l: Row) => l.enabled) : [];
  const level = levels.find((l: Row) => l.level === item.level);
  return <section className={`item-card ${type?.priority_flag ? 'is-priority' : ''}`} aria-label={`Mục lỗi ${index + 1}`}>
    <header className="card-head"><h3>Mục lỗi {index + 1}</h3>{canRemove && <Button variant="ghost" onClick={onRemove} aria-label={`Xóa mục lỗi ${index + 1}`}><Trash2 size={18} /> Xóa mục</Button>}</header>
    <Select label="Loại lỗi" required value={item.defect_type_id} error={errors.type} onChange={(e) => onChange({ ...item, defect_type_id: e.target.value, level: '' })}>
      <option value="">— Chọn loại lỗi —</option>
      {types.map((t) => <option key={t.id} value={t.id}>{t.name}{t.priority_flag ? ' (ƯU TIÊN)' : ''}</option>)}
    </Select>
    {type?.priority_flag && <Alert tone="priority" title="Lỗi ưu tiên">Loại lỗi đặc biệt: giám sát và quản lý được báo ngay, luôn cần người duyệt và lên cấp trên.</Alert>}
    <Stepper label="Số lượng lỗi (số vị trí lỗi trên sản phẩm)" value={item.occurrence_count} onChange={(n) => onChange({ ...item, occurrence_count: n })} />
    {type && <Segmented label="Mức độ" required value={item.level} error={errors.level} onChange={(v) => onChange({ ...item, level: v })}
      options={LEVELS.map((l) => ({ value: l, label: LEVEL_LABELS[l], disabled: !levels.some((x: Row) => x.level === l) }))} />}
    {type && <p className="criteria"><strong>Tiêu chí của loại lỗi đã chọn:</strong> {level ? level.criteria : 'chọn mức độ để xem tiêu chí.'}</p>}
    <TextArea label="Ghi chú" value={item.note} onChange={(e) => onChange({ ...item, note: e.target.value })} placeholder="Vị trí lỗi, mô tả thêm…" />
    <label className="btn file-btn"><Camera size={18} aria-hidden /> Chụp ảnh minh chứng (tùy chọn){item.photos?.length ? ` · ${item.photos.length} ảnh` : ''}
      <input type="file" accept="image/*" capture="environment" multiple onChange={(e) => { const files = Array.from(e.target.files || []); e.target.value = ''; onChange({ ...item, photos: [...(item.photos || []), ...files] }); }} /></label>
    {!!item.photos?.length && <p className="muted">Ảnh được gửi cùng đề xuất (lưu trên máy nếu đang mất mạng). Có thể chụp thêm ở bước Chụp minh chứng.</p>}
  </section>;
}

export default function Create({ editId, token }: { editId?: string; token?: string }) {
  const { user } = useSession();
  const toast = useToast();
  const draftKey = `traceq.draft.${user.id}.${editId || 'new'}`;
  const types = useLoad((s) => cachedGet('/defect-types?state=active&page_size=100', s), []);
  const openSessions = useLoad((s) => cachedGet('/inspection-sessions?status=open&page_size=50', s), []);
  const existing = useLoad((s) => editId ? get(`/defect-cases/${editId}`, s) : Promise.resolve(null), [editId]);
  const [serial, setSerial] = useState('');
  const [scan, setScan] = useState<Row | null>(null);
  const [sessionId, setSessionId] = useState(safeStorage.get('traceq.lastSession.' + user.id) || '');
  const [items, setItems] = useState<Item[]>([newItem()]);
  const [note, setNote] = useState('');
  const [scanning, setScanning] = useState(false);
  const [showQuick, setShowQuick] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [errors, setErrors] = useState<Row>({});
  const [restored, setRestored] = useState(false);
  const [clientId] = useState(() => uuid());

  // Khôi phục dữ liệu form chưa lưu (máy chủ ngủ đông, mất mạng, tải lại trang).
  useEffect(() => {
    if (editId) return;
    const raw = safeStorage.get(draftKey);
    if (raw) { try { const d = JSON.parse(raw); setSerial(d.serial || ''); setItems(d.items?.length ? d.items : [newItem()]); setNote(d.note || ''); if (d.sessionId) setSessionId(d.sessionId); setRestored(true); } catch { /* bỏ qua */ } }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (!editId) safeStorage.set(draftKey, JSON.stringify({ serial, items: items.map(({ photos: _p, ...rest }) => rest), note, sessionId })); }, [serial, items, note, sessionId, editId, draftKey]);
  useEffect(() => {
    const d = existing.data;
    if (!d) return;
    setSerial(d.serial_number); setNote(d.note || ''); setSessionId(d.inspection_session.id);
    setItems(d.items.map((i: Row) => ({ key: i.id, defect_type_id: i.defect_type_id, occurrence_count: i.occurrence_count, level: i.level, note: i.note || '' })));
  }, [existing.data]);
  useEffect(() => { if (token) lookup(token); /* mở từ QR */ // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const sessions: Row[] = openSessions.data?.items || [];
  const session = sessions.find((s) => s.id === sessionId) || (existing.data && existing.data.inspection_session.id === sessionId ? { ...existing.data.inspection_session, batch: { ...existing.data.batch, product_type: existing.data.product } } : null);
  const typeList: Row[] = useMemo(() => {
    const all = (types.data?.items || []).filter((t: Row) => t.levels?.some((l: Row) => l.enabled));
    const recent: string[] = JSON.parse(safeStorage.get('traceq.recentTypes.' + user.id) || '[]');
    return [...all].sort((a, b) => (recent.indexOf(a.id) === -1 ? 99 : recent.indexOf(a.id)) - (recent.indexOf(b.id) === -1 ? 99 : recent.indexOf(b.id)));
  }, [types.data, user.id]);

  async function lookup(text: string) {
    const value = text.trim();
    if (!value) return;
    const tokenMatch = /\/q\/([^/?#]+)/.exec(value);
    const key = tokenMatch ? decodeURIComponent(tokenMatch[1]) : value;
    setError(''); setScan(null);
    try {
      const data = await get('/qr/' + encodeURIComponent(key));
      setScan(data); setSerial(data.unit.serial_number);
      if (data.open_session) setSessionId(data.open_session.id);
      else setSessionId('');
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) { setSerial(key); setScan({ unknown: true }); }
      else setError(e instanceof Error ? e.message : 'Không tra cứu được');
    }
  }

  const openProposal = scan?.cases?.find((c: Row) => !['da_dong', 'da_huy'].includes(c.status));
  const validate = () => {
    const errs: Row = {};
    items.forEach((i) => { if (!i.defect_type_id) errs[i.key + '.type'] = 'Chọn loại lỗi'; else if (!i.level) errs[i.key + '.level'] = 'Bắt buộc chọn mức độ'; });
    if (!serial.trim()) errs.serial = 'Nhập serial hoặc quét QR';
    if (!sessionId) errs.session = 'Chọn đợt kiểm tra';
    setErrors(errs);
    return !Object.keys(errs).length;
  };
  const save = async (next: 'stay' | 'sheet') => {
    if (!validate()) { setError('Vui lòng điền đủ các mục bắt buộc'); return; }
    setBusy(true); setError('');
    const defects = items.map((i) => ({ defect_type_id: i.defect_type_id, occurrence_count: i.occurrence_count, level: i.level, note: i.note }));
    const body = { id: clientId, inspection_session_id: sessionId, serial_number: serial.trim(), note, defects };
    try {
      let result;
      try {
        result = editId ? await patch(`/defect-cases/${editId}`, { row_version: existing.data.row_version, note, defects }) : await post('/defect-cases', body);
      } catch (e: any) {
        if (editId || !(e?.code === 'NETWORK' || e?.code === 'SERVER_STARTING')) throw e;
        // Mất mạng / máy chủ ngủ: lưu bền trên máy (cùng UUID) và tự gửi khi có mạng – không tạo trùng.
        const photos = await Promise.all(items.flatMap((i) => (i.photos || []).map(async (f) => ({ id: uuid(), defectTypeId: i.defect_type_id, blob: await compressImage(f) }))));
        await enqueueProposal({ id: clientId, body, photos, createdAt: new Date().toISOString() });
        safeStorage.remove(draftKey);
        toast('Đang mất mạng: đề xuất đã lưu trên máy và sẽ tự gửi khi có mạng', 'info');
        navigate('/toi', true);
        return;
      }
      for (const item of items) {
        const target = result.items.find((x: Row) => x.defect_type_id === item.defect_type_id);
        for (const file of item.photos || []) { if (target) await uploadPhoto(result.id, target.id, file, 'truoc').catch(() => toast('Một ảnh chưa gửi được, hãy chụp lại ở bước minh chứng', 'error')); }
      }
      safeStorage.remove(draftKey);
      safeStorage.set('traceq.lastSession.' + user.id, sessionId);
      const recent: string[] = JSON.parse(safeStorage.get('traceq.recentTypes.' + user.id) || '[]');
      safeStorage.set('traceq.recentTypes.' + user.id, JSON.stringify([...new Set([...defects.map((d) => d.defect_type_id), ...recent])].slice(0, 10)));
      toast(`Đã lưu nháp ${result.code}`);
      navigate(next === 'sheet' ? `/de-xuat/${result.id}/tong-quan` : `/de-xuat/${result.id}`, true);
    } catch (e: any) {
      setError(e.message);
      if (e.code === 'OPEN_PROPOSAL_EXISTS' && e.fields?.case_id) setScan((s) => ({ ...(s || {}), cases: [{ id: e.fields.case_id, code: e.fields.code, status: 'cho_minh_chung' }] }));
    } finally { setBusy(false); }
  };

  if (types.loading || openSessions.loading || existing.loading) return <Loading />;
  if (types.error) return <ErrorBox error={types.error} onRetry={types.reload} />;
  return <div className="page narrow">
    <PageHeader title={editId ? `Sửa ${existing.data?.code}` : 'Tạo đề xuất'} subtitle="1 đề xuất = 1 sản phẩm (serial)" onBack={() => history.back()} />
    {restored && <Alert tone="info">Đã khôi phục dữ liệu bạn đang nhập dở.</Alert>}
    <Card title="Sản phẩm">
      {!editId && <>
        <div className="row-inline">
          <div className="grow"><TextInput label="Serial sản phẩm" required value={serial} error={errors.serial} onChange={(e) => { setSerial(e.target.value); setScan(null); }} onBlur={() => serial && !scan && lookup(serial)} autoCapitalize="characters" /></div>
          <Button onClick={() => setScanning(true)}><QrCode size={18} aria-hidden /> Quét QR</Button>
        </div>
        {scanning && <QrScanner onResult={(text) => { setScanning(false); lookup(text); }} onClose={() => setScanning(false)} />}
      </>}
      {scan?.unit && <dl className="kv"><dt>Sản phẩm</dt><dd>{scan.product.name}</dd><dt>Lô</dt><dd>{scan.batch.lot_code}</dd><dt>Lịch sử</dt><dd>{scan.history_count} đề xuất trước đó</dd></dl>}
      {scan?.unknown && <p className="muted">Serial mới, chưa có trong hệ thống. Chọn đợt kiểm tra để gắn sản phẩm/lô.</p>}
      {openProposal && <Alert tone="warn" title={`Sản phẩm đang có đề xuất ${openProposal.code} chưa đóng`}>
        Mỗi sản phẩm chỉ có một đề xuất đang mở. <a href={`#/de-xuat/${openProposal.id}`}>Mở đề xuất {openProposal.code}</a> để thêm mục lỗi.</Alert>}
      {editId ? <dl className="kv"><dt>Serial</dt><dd>{existing.data?.serial_number}</dd></dl> : <>
        <Select label="Đợt kiểm tra" required value={sessionId} error={errors.session} onChange={(e) => setSessionId(e.target.value)}>
          <option value="">— Chọn đợt đang kiểm —</option>
          {sessions.filter((s) => !scan?.batch || s.batch_id === scan.batch.id).map((s) => <option key={s.id} value={s.id}>{s.batch.product_type.name} · Lô {s.batch.lot_code} · {s.shift} · {s.stage} · {formatTime(s.started_at)}</option>)}
        </Select>
        {!sessions.filter((s) => !scan?.batch || s.batch_id === scan.batch.id).length && <Alert tone="warn" title="Chưa có đợt kiểm tra đang mở">Tạo nhanh đợt kiểm tra cho ca này để tiếp tục.</Alert>}
        <Button onClick={() => setShowQuick((x) => !x)}>{showQuick ? 'Ẩn tạo nhanh' : 'Tạo nhanh đợt kiểm tra'}</Button>
        {showQuick && <QuickSession batchId={scan?.batch?.id} onCreated={(s) => { setShowQuick(false); openSessions.reload(); setSessionId(s.id); toast('Đã tạo đợt kiểm tra'); }} />}
      </>}
      {session && <dl className="kv session-info">
        <dt>Sản phẩm</dt><dd>{session.batch?.product_type?.name}</dd><dt>Lô</dt><dd>{session.batch?.lot_code}</dd>
        <dt>Ca / công đoạn</dt><dd>{session.shift} · {session.stage} · {session.line}</dd>
        <dt>Tình trạng đợt kiểm</dt><dd><Badge tone={session.status === 'open' ? 'ok' : 'neutral'}>{session.status === 'open' ? 'đang kiểm' : 'đã đóng'}</Badge></dd>
      </dl>}
    </Card>
    <Card title="Mục lỗi">
      {items.map((item, index) => <ItemEditor key={item.key} item={item} index={index} types={typeList} canRemove={items.length > 1}
        errors={{ type: errors[item.key + '.type'], level: errors[item.key + '.level'] }}
        onChange={(next) => setItems(items.map((x) => x.key === item.key ? next : x))} onRemove={() => setItems(items.filter((x) => x.key !== item.key))} />)}
      <Button onClick={() => setItems([...items, newItem()])}><Plus size={18} aria-hidden /> Thêm loại lỗi</Button>
      {!typeList.length && <Alert tone="warn">Chưa có loại lỗi nào được bật mức. Liên hệ quản lý.</Alert>}
    </Card>
    <TextArea label="Ghi chú chung" value={note} onChange={(e) => setNote(e.target.value)} />
    <p className="muted">Giám sát được gắn tự động theo sản phẩm.</p>
    {error && <p className="error-text" role="alert">{error}</p>}
    <div className="actions-bar sticky-actions">
      <Button busy={busy} onClick={() => save('stay')}>Lưu nháp</Button>
      <Button variant="primary" busy={busy} onClick={() => save('sheet')}>Xem tờ tổng quan</Button>
    </div>
  </div>;
}
