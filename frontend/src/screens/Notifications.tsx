// Thông báo (mọi vai trò): lỗi ưu tiên, quá hạn, bị từ chối, nhắc cuối ngày, nhắc nhập chi phí, lỗi lặp lại.
import { useState } from 'react';
import { get, post, query } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { navigate } from '../lib/router';
import { Badge, Button, Chips, Empty, ErrorBox, Loading, PageHeader, Pager, useLoad, useToast } from '../ui/components';

const TYPE: Row = { uu_tien: ['priority', 'Ưu tiên'], qua_han: ['error', 'Quá hạn'], bi_tu_choi: ['warn', 'Bị từ chối'], can_duyet: ['info', 'Cần xử lý'],
  nhac_cuoi_ngay: ['neutral', 'Nhắc cuối ngày'], nhac_chi_phi: ['warn', 'Nhắc chi phí'], loi_lap_lai: ['warn', 'Lỗi lặp lại'] };

export default function Notifications() {
  const toast = useToast();
  const [unread, setUnread] = useState<'all' | 'unread'>('all');
  const [page, setPage] = useState(1);
  const { data, loading, error, reload } = useLoad((s) => get('/notifications' + query({ unread: unread === 'unread' ? 'true' : '', page }), s), [unread, page]);
  const refresh = () => { reload(); window.dispatchEvent(new Event('traceq:notifications')); };
  const open = async (n: Row) => {
    if (!n.read_at) await post(`/notifications/${n.id}/read`).catch(() => {});
    window.dispatchEvent(new Event('traceq:notifications'));
    if (n.link) navigate(n.link); else reload();
  };
  return <div className="page narrow">
    <PageHeader title="Thông báo" actions={<Button onClick={async () => { await post('/notifications/read-all'); toast('Đã đánh dấu tất cả là đã đọc'); refresh(); }}>Đánh dấu đã đọc tất cả</Button>} />
    <Chips label="Lọc thông báo" value={unread} onChange={(v) => { setUnread(v); setPage(1); }} options={[{ value: 'all', label: 'Tất cả' }, { value: 'unread', label: 'Chưa đọc' }]} />
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <>
      <ul className="notif-list">{data.items.map((n: Row) => <li key={n.id}><button type="button" className={`notif ${n.read_at ? '' : 'unread'} notif-${n.type}`} onClick={() => open(n)}>
        <div className="notif-top"><Badge tone={TYPE[n.type]?.[0]}>{TYPE[n.type]?.[1] || n.type}</Badge>{!n.read_at && <Badge tone="info">Mới</Badge>}<span className="muted">{formatTime(n.created_at)}</span></div>
        <strong>{n.title}</strong><span>{n.body}</span></button></li>)}</ul>
      {!data.items.length && <Empty title="Không có thông báo" />}
      <Pager page={page} pageSize={30} total={data.total} onPage={setPage} />
    </>}
  </div>;
}
