// Danh sách đề xuất: sắp theo cờ ưu tiên → mức Nặng → quá hạn → mới nhất (server sắp).
import { useState } from 'react';
import { Plus } from 'lucide-react';
import { get, query } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime, relativeDeadline } from '../lib/format';
import { LEVEL_LABELS } from '../lib/labels';
import { navigate } from '../lib/router';
import { Badge, Button, Chips, Empty, ErrorBox, Loading, PageHeader, Pager, StatusBadge, useLoad } from '../ui/components';

export function ProposalCard({ p }: { p: Row }) {
  return <a className={`proposal-card ${p.priority ? 'is-priority' : ''}`} href={`#/de-xuat/${p.id}`}>
    <div className="pc-top">
      <strong className="pc-code">{p.code}</strong>
      {p.priority && <Badge tone="priority">Ưu tiên</Badge>}
      {p.max_level === 'nang' && <Badge tone="error">Nặng</Badge>}
      {p.overdue && <Badge tone="error">Quá hạn</Badge>}
      <span className="pc-status"><StatusBadge status={p.status} /></span>
    </div>
    <div className="pc-product">{p.product.name} · <span className="muted">Serial {p.serial_number} · Lô {p.batch.lot_code}</span></div>
    <ul className="pc-items">{p.items.map((i: Row) => <li key={i.id}>{i.name} × {i.occurrence_count} · {LEVEL_LABELS[i.level]}</li>)}</ul>
    <div className="pc-meta muted">Tạo {formatTime(p.created_at)} bởi {p.creator.display_name}{p.deadline_at && p.status !== 'da_dong' && p.status !== 'da_huy' ? ` · Hạn: ${relativeDeadline(p.deadline_at)}` : ''}</div>
  </a>;
}

type Filter = 'dang_mo' | 'tat_ca' | 'cho_minh_chung' | 'cho_xac_nhan' | 'qua_han' | 'uu_tien' | 'nhap' | 'cho_phuong_an' | 'dang_xu_ly' | 'cho_dong' | 'cho_cap_tren' | 'da_dong';

export default function ProposalList({ title, subtitle, view, canCreate, extraFilters = [], defaultFilter = 'tat_ca' }: { title: string; subtitle?: string; view: string; canCreate?: boolean; extraFilters?: { value: Filter; label: string }[]; defaultFilter?: Filter }) {
  const [filter, setFilter] = useState<Filter>(defaultFilter);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useLoad((s) => get('/defect-cases' + query({ view, filter, search, page, page_size: 20 }), s), [view, filter, search, page]);
  const counts = data?.counts || {};
  const options: { value: Filter; label: string; count?: number }[] = [
    ...(defaultFilter === 'dang_mo' ? [{ value: 'dang_mo' as Filter, label: 'Đang mở' }] : []), { value: 'tat_ca', label: 'Tất cả' }, { value: 'cho_minh_chung', label: 'Chờ minh chứng', count: counts.cho_minh_chung },
    { value: 'cho_xac_nhan', label: 'Chờ xác nhận', count: counts.cho_xac_nhan }, { value: 'qua_han', label: 'Quá hạn', count: counts.qua_han },
    { value: 'uu_tien', label: 'Ưu tiên', count: counts.uu_tien }, ...extraFilters,
  ];
  return <div className="page">
    {title && <PageHeader title={title} subtitle={subtitle} actions={<>
      <Button onClick={reload}>Làm mới</Button>
      {canCreate && <Button variant="primary" onClick={() => navigate('/tao')}><Plus size={18} aria-hidden /> Tạo đề xuất</Button>}
    </>} />}
    <Chips label="Lọc đề xuất" value={filter} onChange={(v) => { setFilter(v); setPage(1); }} options={options} />
    <input className="search" type="search" placeholder="Tìm mã DX hoặc serial…" aria-label="Tìm đề xuất" value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} style={{ margin: '8px 0 14px', maxWidth: 360 }} />
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <>
      <div className="card-list">{data.items.map((p: Row) => <ProposalCard key={p.id} p={p} />)}</div>
      {!data.items.length && <Empty title="Không có đề xuất">{canCreate ? 'Bấm “Tạo đề xuất” hoặc quét QR sản phẩm để bắt đầu.' : 'Chưa có việc trong mục này.'}</Empty>}
      <Pager page={page} pageSize={20} total={data.total} onPage={setPage} />
    </>}
    {canCreate && <button type="button" className="fab" onClick={() => navigate('/tao')} aria-label="Tạo đề xuất"><Plus size={28} /></button>}
  </div>;
}
