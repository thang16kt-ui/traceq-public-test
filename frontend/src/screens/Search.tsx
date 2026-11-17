// Tra cứu: serial, mã DX, lô, loại lỗi, khoảng thời gian; nút Quét QR; kết quả + "Lịch sử sản phẩm này".
import { useState } from 'react';
import { QrCode } from 'lucide-react';
import { get, query } from '../lib/api';
import type { Row } from '../lib/api';
import { STATUS_LABELS } from '../lib/labels';
import { Button, Card, Empty, ErrorBox, Loading, PageHeader, Pager, Select, TextInput, useLoad } from '../ui/components';
import { ProposalCard } from './Proposals';
import { QrScanner } from './Scan';

const EMPTY = { serial: '', code: '', lot: '', defect_type_id: '', status: '', date_from: '', date_to: '' };

export default function Search() {
  const [form, setForm] = useState<Row>(EMPTY);
  const [params, setParams] = useState<Row | null>(null);
  const [page, setPage] = useState(1);
  const [scanning, setScanning] = useState(false);
  const types = useLoad((s) => get('/defect-types?state=all&page_size=100', s), []);
  const result = useLoad((s) => params ? get('/search' + query({ ...params, page }), s) : Promise.resolve(null), [params, page]);
  const set = (k: string, v: string) => setForm({ ...form, [k]: v });
  const submit = (e?: React.FormEvent) => { e?.preventDefault(); setPage(1); setParams({ ...form }); };
  return <div className="page">
    <PageHeader title="Tra cứu" subtitle="Tìm đề xuất theo serial, mã DX, lô, loại lỗi, thời gian" />
    <Card>
      <form onSubmit={submit}>
        <div className="grid-3">
          <TextInput label="Serial" value={form.serial} onChange={(e) => set('serial', e.target.value)} />
          <TextInput label="Mã đề xuất (DX-…)" value={form.code} onChange={(e) => set('code', e.target.value)} />
          <TextInput label="Lô" value={form.lot} onChange={(e) => set('lot', e.target.value)} />
          <Select label="Loại lỗi" value={form.defect_type_id} onChange={(e) => set('defect_type_id', e.target.value)}>
            <option value="">Tất cả</option>{(types.data?.items || []).map((t: Row) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
          <Select label="Trạng thái" value={form.status} onChange={(e) => set('status', e.target.value)}>
            <option value="">Tất cả</option>{Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
          <div className="grid-2"><TextInput label="Từ ngày" type="date" value={form.date_from} onChange={(e) => set('date_from', e.target.value)} />
            <TextInput label="Đến ngày" type="date" value={form.date_to} onChange={(e) => set('date_to', e.target.value)} /></div>
        </div>
        <div className="actions-bar">
          <Button type="submit" variant="primary">Tìm</Button>
          <Button onClick={() => setScanning(true)}><QrCode size={18} aria-hidden /> Quét QR</Button>
          <Button variant="ghost" onClick={() => { setForm(EMPTY); setParams(null); }}>Xóa bộ lọc</Button>
        </div>
      </form>
    </Card>
    {scanning && <QrScanner onClose={() => setScanning(false)} onResult={(text) => {
      setScanning(false);
      const m = /\/q\/([^/?#]+)/.exec(text);
      if (m) { location.hash = '/quet/' + encodeURIComponent(decodeURIComponent(m[1])); return; }
      const next = { ...EMPTY, serial: text.trim() }; setForm(next); setParams(next); setPage(1);
    }} />}
    {params && (result.loading && !result.data ? <Loading /> : result.error ? <ErrorBox error={result.error} onRetry={result.reload} /> : result.data && <>
      <p className="muted">{result.data.total} kết quả</p>
      <div className="card-list">{result.data.items.map((p: Row) => <div key={p.id}><ProposalCard p={p} />
        <p className="history-note">Lịch sử sản phẩm này: {p.product_history_count ? `${p.product_history_count} đề xuất lỗi khác` : 'chưa có đề xuất lỗi nào khác'}</p></div>)}</div>
      {!result.data.items.length && <Empty title="Không tìm thấy đề xuất phù hợp" />}
      <Pager page={page} pageSize={25} total={result.data.total} onPage={setPage} />
    </>)}
  </div>;
}
