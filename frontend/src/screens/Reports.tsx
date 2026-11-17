// Báo cáo in/PDF (khách hàng, kiểm toán): chọn kỳ + nội dung; PDF A4 và Excel; lịch sử xuất; gửi định kỳ qua email.
import { useState } from 'react';
import { download, get, post, put } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime, vnDateInput } from '../lib/format';
import { Alert, Badge, Button, Card, Checkbox, ErrorBox, Loading, PageHeader, Pager, Select, TextInput, useLoad, useToast } from '../ui/components';

const SECTIONS: [string, string][] = [['kpi', 'Chỉ số chính (KPI)'], ['pareto', 'Pareto chi phí theo loại lỗi'], ['tu_dong', 'Tự động duyệt (số đo trong kỳ)'], ['de_xuat', 'Bảng đề xuất'], ['ma_bam', 'Mã băm ảnh minh chứng (SHA-256)'], ['anh', 'Đính kèm bộ ảnh theo đề xuất (tệp lớn)']];
const DAYS = ['Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ nhật'];

function Schedule({ smtp }: { smtp: boolean }) {
  const toast = useToast();
  const { data, loading, reload } = useLoad((s) => get('/settings', s), []);
  const [draft, setDraft] = useState<Row | null>(null);
  if (loading || !data) return <Loading />;
  const value: Row = draft || data.items.find((i: Row) => i.key === 'report_email').value;
  const set = (k: string, v: any) => setDraft({ ...value, [k]: v });
  const save = async () => {
    try { await put('/settings/report_email', { value: { ...value, recipients: String(value.recipients_text ?? value.recipients.join(', ')).split(/[,;\s]+/).filter(Boolean) }, reason: 'Cập nhật gửi báo cáo định kỳ' }); toast('Đã lưu lịch gửi'); setDraft(null); reload(); }
    catch (e: any) { toast(e.message, 'error'); }
  };
  return <Card title="Gửi báo cáo định kỳ qua email">
    {!smtp && <Alert tone="warn" title="Máy chủ chưa cấu hình gửi email (SMTP)">Báo cáo định kỳ vẫn được tạo và lưu ở đây; Quản lý nhận thông báo trong app để tải về.</Alert>}
    <Checkbox label="Bật gửi định kỳ" checked={!!value.enabled} onChange={(e) => set('enabled', e.target.checked)} />
    <TextInput label="Người nhận (cách nhau bằng dấu phẩy)" value={value.recipients_text ?? value.recipients.join(', ')} onChange={(e) => set('recipients_text', e.target.value)} />
    <div className="grid-3">
      <Select label="Tần suất" value={value.frequency} onChange={(e) => set('frequency', e.target.value)}><option value="weekly">Hằng tuần (tuần trước)</option><option value="monthly">Hằng tháng (ngày 1, tháng trước)</option></Select>
      {value.frequency === 'weekly' && <Select label="Ngày gửi" value={value.weekday} onChange={(e) => set('weekday', Number(e.target.value))}>{DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</Select>}
      <TextInput label="Giờ gửi (giờ VN)" type="time" value={value.time} onChange={(e) => set('time', e.target.value)} />
    </div>
    <Button variant="primary" onClick={save} disabled={!draft}>Lưu lịch gửi</Button>
  </Card>;
}

export default function Reports() {
  const toast = useToast();
  const today = vnDateInput();
  const [form, setForm] = useState<Row>({ date_from: today.slice(0, 8) + '01', date_to: today, product_type_id: '', sections: ['kpi', 'pareto', 'tu_dong', 'de_xuat', 'ma_bam'] });
  const [busy, setBusy] = useState('');
  const [page, setPage] = useState(1);
  const products = useLoad((s) => get('/product-types?state=all&page_size=100', s), []);
  const history = useLoad((s) => get(`/reports?page=${page}`, s), [page]);
  const make = async (format: 'pdf' | 'xlsx') => {
    setBusy(format);
    try {
      const r = await post('/reports', { date_from: form.date_from, date_to: form.date_to, product_type_id: form.product_type_id || null, format, sections: form.sections });
      toast(`Đã tạo ${r.code}`); history.reload();
      await download(`/reports/${r.id}/download`, `${r.code}.${format}`);
    } catch (e: any) { toast(e.message, 'error'); } finally { setBusy(''); }
  };
  const toggle = (k: string) => setForm({ ...form, sections: form.sections.includes(k) ? form.sections.filter((x: string) => x !== k) : [...form.sections, k] });
  return <div className="page">
    <PageHeader title="Báo cáo" subtitle="Báo cáo in/PDF cho khách hàng và kiểm toán. Mọi lần xuất được ghi nhật ký." />
    <div className="grid-2">
      <Card title="Xuất báo cáo">
        <div className="grid-2"><TextInput label="Từ ngày" type="date" value={form.date_from} onChange={(e) => setForm({ ...form, date_from: e.target.value })} />
          <TextInput label="Đến ngày" type="date" value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} /></div>
        <Select label="Sản phẩm" value={form.product_type_id} onChange={(e) => setForm({ ...form, product_type_id: e.target.value })}><option value="">Toàn nhà máy</option>{(products.data?.items || []).map((p: Row) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        <fieldset><legend>Nội dung</legend>{SECTIONS.map(([k, label]) => <Checkbox key={k} label={label} checked={form.sections.includes(k)} onChange={() => toggle(k)} />)}</fieldset>
        <p className="muted">PDF A4 có mã BC-xxxx, người xuất, giờ xuất và chỗ ký “Người lập” / “Quản lý xác nhận”.</p>
        <div className="actions-bar"><Button variant="primary" busy={busy === 'pdf'} onClick={() => make('pdf')}>Xuất PDF</Button><Button busy={busy === 'xlsx'} onClick={() => make('xlsx')}>Xuất Excel</Button></div>
      </Card>
      <Schedule smtp={!!history.data?.smtp_configured} />
    </div>
    <Card title="Lịch sử xuất">
      {history.loading && !history.data ? <Loading /> : history.error ? <ErrorBox error={history.error} onRetry={history.reload} /> : <>
        <div className="table-wrap"><table className="table"><thead><tr><th>Mã</th><th>Kỳ</th><th>Người xuất</th><th>Lúc</th><th>Gửi email</th><th>SHA-256</th><th><span className="sr-only">Tải</span></th></tr></thead>
          <tbody>{history.data.items.map((r: Row) => <tr key={r.id}><td><strong>{r.code}</strong> <Badge>{r.format.toUpperCase()}</Badge>{r.kind === 'dinh_ky' && <Badge tone="info">Định kỳ</Badge>}</td>
            <td>{r.params.date_from.split('-').reverse().join('/')} – {r.params.date_to.split('-').reverse().join('/')}</td><td>{r.created_by}</td><td>{formatTime(r.created_at)}</td>
            <td>{r.delivery?.email === 'da_gui' ? <Badge tone="ok">Đã gửi</Badge> : r.delivery?.email ? <Badge tone="warn">{r.delivery.email === 'loi' ? 'Lỗi gửi' : 'Chưa gửi'}</Badge> : '—'}</td>
            <td><code title={r.sha256}>{r.sha256.slice(0, 12)}…</code></td>
            <td><Button onClick={() => download(`/reports/${r.id}/download`, `${r.code}.${r.format}`).catch((e) => toast(e.message, 'error'))}>Tải</Button></td></tr>)}</tbody></table></div>
        <Pager page={page} pageSize={20} total={history.data.total} onPage={setPage} />
      </>}
    </Card>
  </div>;
}
