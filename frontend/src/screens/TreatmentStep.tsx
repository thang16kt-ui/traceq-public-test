// Chọn phương án: Sửa/Tái chế/Hủy/Khác; chi phí ước tính tự tính (nguồn + số mẫu); hạn xử lý; "Chốt phương án".
// Một cấp duyệt: phương án chốt có hiệu lực ngay. "Chờ cấp trên" chỉ còn cho đề xuất cũ (Quản lý Phê duyệt / Từ chối).
import { useEffect, useState } from 'react';
import { get, post } from '../lib/api';
import type { Row } from '../lib/api';
import { formatMoney, formatTime } from '../lib/format';
import { METHOD_LABELS, METHODS } from '../lib/labels';
import { Alert, Badge, Button, Card, Loading, Segmented, TextArea, useToast } from '../ui/components';
import { DETAIL_SECTIONS } from './Detail';

export function EstimateView({ e }: { e: Row }) {
  return <div className="estimate">
    <div className="estimate-main"><span className="muted">Chi phí ước tính</span><strong>{e.est_cost ? formatMoney(e.est_cost) : 'Chưa ước tính được'}</strong></div>
    <p className="muted">Nguồn: {e.est_source_label}{e.est_sample_n ? ` · từ ${e.est_sample_n} lần sửa thực tế` : ' · 0 mẫu thực tế'}</p>
    {e.breakdown?.length > 0 && <ul className="breakdown">{e.breakdown.map((b: Row, n: number) => <li key={n}>{b.name}: {b.quantity} vị trí × {b.unit_cost ? formatMoney(b.unit_cost) : 'chưa có giá'}{b.source === 'thuc_te' ? ` (thực tế, ${b.sample_n} mẫu)` : b.source === 'gia_thi_truong' ? ' (giá thị trường)' : ''}</li>)}</ul>}
    {e.missing?.length > 0 && <p className="error-text">Thiếu giá: {e.missing.join(', ')}</p>}
  </div>;
}

function ChooseTreatment({ p, reload }: { p: Row; reload: () => void }) {
  const toast = useToast();
  const [method, setMethod] = useState<string>('');
  const [note, setNote] = useState('');
  const [estimate, setEstimate] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!method) return;
    const c = new AbortController();
    setEstimate(null);
    get(`/defect-cases/${p.id}/estimate?method=${method}`, c.signal).then(setEstimate).catch(() => {});
    return () => c.abort();
  }, [method, p.id]);
  const rejected = p.treatment?.status === 'bi_tu_choi' ? p.treatment : null;
  const submit = async () => {
    setBusy(true); setError('');
    try { await post(`/defect-cases/${p.id}/treatment`, { row_version: p.row_version, method, note }); toast('Đã chốt phương án, chuyển sang xử lý'); reload(); }
    catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return <Card title="Chọn phương án" className="step-card">
    {rejected && <Alert tone="warn" title={`Phương án ${rejected.method_label} đã bị trả lại`}>Lý do: {rejected.rejected_reason}</Alert>}
    <Segmented label="Phương án" required value={method} onChange={setMethod} options={METHODS.map((m) => ({ value: m, label: METHOD_LABELS[m] + ((p.suggested_methods || []).includes(m) ? ' · gợi ý' : '') }))} />
    {method && (estimate ? <EstimateView e={estimate} /> : <Loading text="Đang tính chi phí…" />)}
    <p><strong>Hạn xử lý (theo mức độ):</strong> {p.deadline_at ? formatTime(p.deadline_at) : '—'}</p>
    {estimate && <p className="muted">Một cấp duyệt: chốt xong chuyển thẳng sang xử lý.{p.priority ? '' : ` Chi phí trên ${formatMoney(estimate.threshold)} hoặc phương án Hủy thì hệ thống không tự duyệt.`}</p>}
    <TextArea label={method === 'khac' ? 'Ghi chú (bắt buộc với phương án Khác)' : 'Ghi chú'} required={method === 'khac'} value={note} onChange={(e) => setNote(e.target.value)} />
    {error && <p className="error-text" role="alert">{error}</p>}
    <Button variant="primary" busy={busy} disabled={!method || !estimate} onClick={submit}>Chốt phương án</Button>
  </Card>;
}

function ApprovalInfo({ p }: { p: Row }) {
  const t = p.treatment;
  if (!t) return null;
  return <Card title="Đề xuất cũ đang chờ cấp trên" className="step-card">
    <Alert tone="info" title="Đã bỏ bước Cấp trên">Đề xuất này vào hàng chờ trước khi chuyển sang một cấp duyệt. Quản lý Phê duyệt để chuyển sang xử lý, hoặc Từ chối để chọn lại phương án.{t.approval_reasons?.length ? ` Lý do cũ: ${t.approval_reasons.join('; ')}.` : ''}</Alert>
    <dl className="kv"><dt>Phương án</dt><dd>{t.method_label}</dd><dt>Người chốt</dt><dd>{t.decided_by} · {formatTime(t.decided_at)}</dd>{t.note && <><dt>Ghi chú</dt><dd>{t.note}</dd></>}</dl>
    <EstimateView e={t} />
    <p className="muted">Phê duyệt → chuyển sang xử lý. Từ chối (bắt buộc lý do) → quay lại bước chọn phương án.</p>
  </Card>;
}

DETAIL_SECTIONS.push((p, reload) => p.status === 'cho_phuong_an' && p.allowed_actions.includes('chot_phuong_an') ? <ChooseTreatment p={p} reload={reload} /> : null);
DETAIL_SECTIONS.push((p) => p.status === 'cho_cap_tren' ? <ApprovalInfo p={p} /> : null);
DETAIL_SECTIONS.push((p) => p.treatment && !['cho_cap_tren', 'cho_phuong_an'].includes(p.status) ? <Card title="Phương án đã chốt"><dl className="kv">
  <dt>Phương án</dt><dd>{p.treatment.method_label} <Badge tone={p.treatment.status === 'hieu_luc' ? 'ok' : 'neutral'}>{p.treatment.approved_by ? `${p.treatment.approved_by} phê duyệt` : 'Có hiệu lực khi chốt'}</Badge></dd>
  <dt>Chi phí ước tính</dt><dd>{formatMoney(p.treatment.est_cost)} · {p.treatment.est_source_label}{p.treatment.est_sample_n ? ` (${p.treatment.est_sample_n} mẫu)` : ''}</dd></dl></Card> : null);
