// Hoàn tất xử lý: chi phí thực tế (vật tư, số giờ, khác), tổng so với ước tính, nguyên nhân gốc, ảnh sau xử lý.
// Kiểm tra và đóng: ảnh trước/sau, ước tính vs thực tế, nguyên nhân gốc; "Đóng đề xuất" / "Yêu cầu làm lại".
import { useState } from 'react';
import { Camera } from 'lucide-react';
import { get, post } from '../lib/api';
import type { Row } from '../lib/api';
import { formatMoney } from '../lib/format';
import { ROOT_CAUSES } from '../lib/labels';
import { Alert, Badge, Button, Card, TextArea, TextInput, useLoad, useToast } from '../ui/components';
import { DETAIL_SECTIONS } from './Detail';
import { Photo, uploadPhoto } from './Evidence';

const num = (v: string) => (v === '' ? 0 : Number(v));

function Comparison({ estimate, actual }: { estimate: any; actual: any }) {
  if (actual == null) return null;
  const diff = estimate != null ? Number(actual) - Number(estimate) : null;
  return <div className="compare">
    <div><span className="muted">Ước tính</span><strong>{formatMoney(estimate)}</strong></div>
    <div><span className="muted">Thực tế</span><strong>{formatMoney(actual)}</strong></div>
    {diff != null && <div><span className="muted">Chênh lệch</span><strong>{diff > 0 ? '+' : ''}{formatMoney(diff)}{Number(estimate) ? ` (${diff > 0 ? '+' : ''}${Math.round(diff / Number(estimate) * 100)}%)` : ''}</strong>
      <Badge tone={diff > 0 ? 'warn' : 'ok'}>{diff > 0 ? 'Cao hơn ước tính' : 'Không vượt ước tính'}</Badge></div>}
  </div>;
}

function CompleteForm({ p, reload }: { p: Row; reload: () => void }) {
  const toast = useToast();
  const settings = useLoad((s) => get('/settings', s), []);
  const defaultRate = settings.data?.items.find((i: Row) => i.key === 'hourly_rate')?.value || '';
  const [v, setV] = useState<Row>({ material: '', hours: '', hourly_rate: '', other: '', note: '' });
  const [causes, setCauses] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState('');
  const [error, setError] = useState('');
  const rate = v.hourly_rate === '' ? Number(defaultRate) : num(v.hourly_rate);
  const total = num(v.material) + num(v.hours) * rate + num(v.other);
  const previous = p.cost_actual ? Number(p.cost_actual.total) : 0;
  const set = (k: string, x: string) => setV({ ...v, [k]: x.replace(/[^\d.]/g, '') });
  const submit = async () => {
    setBusy(true); setError('');
    try {
      await post(`/defect-cases/${p.id}/complete`, { row_version: p.row_version, material: String(num(v.material)), hours: String(num(v.hours)),
        hourly_rate: v.hourly_rate === '' ? null : String(num(v.hourly_rate)), other: String(num(v.other)), root_causes: causes, note: v.note });
      toast('Đã hoàn tất xử lý, chờ kiểm tra đóng'); reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  const lastRework = p.history.filter((h: Row) => h.action === 'yeu_cau_lam_lai').slice(-1)[0];
  return <Card title="Hoàn tất xử lý" className="step-card">
    {lastRework && <Alert tone="warn" title={`Yêu cầu làm lại: ${lastRework.reason}`}>Chi phí nhập lần này được cộng thêm vào chi phí đã nhập trước ({formatMoney(previous)}).</Alert>}
    <h3 className="sub">Ảnh sau xử lý</h3>
    {p.items.map((i: Row) => <div key={i.id} className="after-row"><strong>{i.name}</strong>
      <div className="photo-grid">{(i.after_photos || []).map((ph: Row, k: number) => <Photo key={ph.id} photo={ph} label={`Ảnh sau xử lý ${k + 1} của ${i.name}`} />)}</div>
      <label className="btn file-btn"><Camera size={18} aria-hidden /> {uploading === i.id ? 'Đang tải…' : 'Chụp ảnh sau xử lý'}
        <input type="file" accept="image/*" capture="environment" disabled={!!uploading} onChange={async (e) => {
          const file = e.target.files?.[0]; e.target.value = ''; if (!file) return;
          setUploading(i.id); try { const r = await uploadPhoto(p.id, i.id, file, 'sau'); toast(r ? 'Đã tải ảnh' : 'Mất mạng: ảnh sẽ tự gửi khi có mạng', r ? 'ok' : 'info'); reload(); } catch (err: any) { toast(err.message, 'error'); } finally { setUploading(''); }
        }} /></label></div>)}
    <h3 className="sub">Chi phí thực tế</h3>
    <div className="grid-2">
      <TextInput label="Vật tư (VND)" inputMode="numeric" value={v.material} onChange={(e) => set('material', e.target.value)} />
      <TextInput label="Số giờ công" inputMode="decimal" value={v.hours} onChange={(e) => set('hours', e.target.value)} />
      <TextInput label="Đơn giá giờ công (VND/giờ)" inputMode="numeric" value={v.hourly_rate} placeholder={String(defaultRate)} hint={`Để trống = mặc định ${formatMoney(defaultRate)}`} onChange={(e) => set('hourly_rate', e.target.value)} />
      <TextInput label="Chi phí khác (VND)" inputMode="numeric" value={v.other} onChange={(e) => set('other', e.target.value)} />
    </div>
    <Comparison estimate={p.treatment?.est_cost} actual={previous + total} />
    <fieldset className="segmented"><legend>Nguyên nhân gốc (chọn một hoặc nhiều) <span className="required">*</span></legend>
      <div className="chips">{ROOT_CAUSES.map((c) => <button key={c} type="button" className={`chip ${causes.includes(c) ? 'active' : ''}`} aria-pressed={causes.includes(c)}
        onClick={() => setCauses(causes.includes(c) ? causes.filter((x) => x !== c) : [...causes, c])}>{c}</button>)}</div></fieldset>
    <TextArea label="Ghi chú xử lý" value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} />
    {!p.items.some((i: Row) => i.after_photos?.length) && <p className="muted">Chưa có ảnh sau xử lý – nên chụp để người đóng đối chiếu.</p>}
    {error && <p className="error-text" role="alert">{error}</p>}
    <Button variant="primary" busy={busy} disabled={!causes.length} onClick={submit}>Hoàn tất xử lý</Button>
  </Card>;
}

function CloseReview({ p }: { p: Row }) {
  const c = p.cost_actual;
  return <Card title="Kiểm tra và đóng" className="step-card">
    <Comparison estimate={p.treatment?.est_cost} actual={c?.total} />
    {c && <dl className="kv"><dt>Nguyên nhân gốc</dt><dd>{c.root_causes.map((x: string) => <Badge key={x}>{x}</Badge>)}</dd>
      <dt>Chi tiết</dt><dd>Vật tư {formatMoney(c.material)} · {c.hours} giờ · khác {formatMoney(c.other)}{c.entries.length > 1 ? ` · ${c.entries.length} lần xử lý` : ''}</dd>
      {c.note && <><dt>Ghi chú</dt><dd>{c.note}</dd></>}</dl>}
    <p className="muted">Đối chiếu ảnh trước/sau ở mục bên dưới. "Đóng đề xuất" đưa chi phí thực tế vào dữ liệu dự báo; "Yêu cầu làm lại" bắt buộc lý do.</p>
  </Card>;
}

DETAIL_SECTIONS.push((p, reload) => p.status === 'dang_xu_ly' && p.allowed_actions.includes('hoan_tat_xu_ly') ? <CompleteForm p={p} reload={reload} /> : null);
DETAIL_SECTIONS.push((p) => p.status === 'cho_dong' ? <CloseReview p={p} /> : null);
DETAIL_SECTIONS.push((p) => p.status === 'da_dong' && p.cost_actual ? <Card title="Chi phí"><Comparison estimate={p.treatment?.est_cost} actual={p.cost_actual.total} /></Card> : null);
