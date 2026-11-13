// Hệ thống (Admin): sức khỏe máy chủ, scheduler, lưu trữ, sao lưu + diễn tập khôi phục, lỗi gần đây, gói xuất dữ liệu.
import { download, get, post } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { Alert, Badge, Button, Card, Empty, ErrorBox, Loading, PageHeader, useLoad, useToast } from '../ui/components';

const ok = (v: boolean | undefined, yes = 'Tốt', no = 'Có vấn đề') => <Badge tone={v ? 'ok' : 'error'}>{v ? yes : no}</Badge>;

function Exports() {
  const toast = useToast();
  const { data, loading, reload } = useLoad((s) => get('/export-runs?page_size=10', s), []);
  const run = async () => {
    const end = new Date(); const start = new Date(Date.now() - 86400000);
    try { await post('/export-runs', { period_start: start.toISOString(), period_end: end.toISOString(), scope: {}, format: 'xlsx', revision: 1 }); toast('Đã xếp hàng xuất gói dữ liệu 24 giờ qua'); reload(); }
    catch (e: any) { toast(e.message, 'error'); }
  };
  return <Card title="Gói xuất dữ liệu (tích hợp hệ thống khác)" actions={<Button onClick={run}>Xuất 24 giờ qua</Button>}>
    <p className="muted">Gói ZIP CSV/XLSX có checksum theo hợp đồng file (docs/file-contract.md). Giữ nguyên từ phiên bản trước.</p>
    {loading && !data ? <Loading /> : data?.items?.length ? <ul className="list">{data.items.map((r: Row) => <li key={r.id} className="list-row"><div>
      <strong>{formatTime(r.period_start)} – {formatTime(r.period_end)}</strong> <Badge tone={r.status === 'succeeded' ? 'ok' : r.status === 'failed' ? 'error' : 'info'}>{r.status === 'succeeded' ? 'Hoàn tất' : r.status === 'failed' ? 'Lỗi' : 'Đang xử lý'}</Badge></div>
      {r.status === 'succeeded' && <Button onClick={() => download(`/export-runs/${r.id}/download`, `export-${r.id}.zip`).catch((e) => toast(e.message, 'error'))}>Tải ZIP</Button>}</li>)}</ul> : <Empty title="Chưa có gói xuất" />}
  </Card>;
}

export default function System() {
  const { data, loading, error, reload } = useLoad((s) => get('/system/health', s), []);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const b = data.backup;
  return <div className="page">
    <PageHeader title="Hệ thống" subtitle={`Môi trường: ${data.environment}`} actions={<Button onClick={reload}>Làm mới</Button>} />
    {data.storage.ephemeral_warning && <Alert tone="error" title="Thư mục dữ liệu nằm trên đĩa tạm">Ảnh minh chứng và báo cáo sẽ MẤT khi máy chủ khởi động lại. Cấu hình DATA_DIR trên đĩa bền (Render disk/volume) trước khi dùng thật.</Alert>}
    <div className="kpi-grid">
      <div className="kpi"><span className="kpi-label">Cơ sở dữ liệu</span>{ok(data.database, 'Kết nối tốt', 'Mất kết nối')}<span className="kpi-hint">Schema {data.schema.applied || '?'} / cần {data.schema.expected}</span></div>
      <div className="kpi"><span className="kpi-label">Scheduler (cảnh báo, push, sao lưu)</span>{ok(data.scheduler.ok, 'Đang chạy', 'Không thấy nhịp')}<span className="kpi-hint">{data.scheduler.last_seen_seconds != null ? `nhịp cách đây ${data.scheduler.last_seen_seconds} giây` : 'chưa có nhịp'}</span></div>
      <div className="kpi"><span className="kpi-label">Lưu trữ file</span>{ok(data.storage.writable, 'Ghi được', 'Không ghi được')}<span className="kpi-hint">còn trống {data.storage.free_gb ?? '?'} GB</span></div>
      <div className="kpi"><span className="kpi-label">Lỗi 24 giờ</span><strong className="kpi-value">{data.errors_24h}</strong></div>
      <div className="kpi"><span className="kpi-label">Thông báo đẩy</span>{ok(data.push.configured, 'Đã cấu hình', 'Chưa cấu hình')}<span className="kpi-hint">{data.push.pending} chờ gửi</span></div>
      <div className="kpi"><span className="kpi-label">Email báo cáo</span>{ok(data.email.configured, 'Đã cấu hình', 'Chưa cấu hình')}<span className="kpi-hint">{data.email.host || 'thiếu SMTP_HOST'}</span></div>
      <div className="kpi"><span className="kpi-label">Sao lưu gần nhất</span>{b ? ok(b.ok, 'Đạt (đã thử khôi phục)', 'Lỗi') : <Badge tone="warn">Chưa có</Badge>}<span className="kpi-hint">{b ? formatTime(b.at) : 'chạy hằng đêm sau 02:00'}</span></div>
    </div>
    {b && <Card title="Sao lưu và diễn tập khôi phục">
      {b.error ? <Alert tone="error" title="Sao lưu lỗi">{b.error}</Alert> : <dl className="kv"><dt>Thư mục</dt><dd>{b.path}</dd><dt>Số dòng</dt><dd>{b.rows}</dd>
        <dt>Diễn tập khôi phục</dt><dd>{b.drill?.ok ? 'Đạt' : 'Không đạt'} · {b.drill?.tables} bảng khớp, {b.drill?.photos_checked} ảnh khớp mã băm</dd></dl>}
      <p className="muted">Nên chép thư mục sao lưu ra nơi khác máy chủ (ổ/kho khác). Hướng dẫn: docs/van-hanh.md.</p>
    </Card>}
    <Card title="Lỗi gần đây">
      {data.recent_errors.length ? <div className="table-wrap"><table className="table"><thead><tr><th>Lúc</th><th>Nguồn</th><th>Nội dung</th><th>Đường dẫn</th><th>Mã yêu cầu</th></tr></thead>
        <tbody>{data.recent_errors.map((e: Row) => <tr key={e.id}><td>{formatTime(e.at)}</td><td><Badge>{e.source === 'server' ? 'Máy chủ' : e.source === 'client' ? 'Giao diện' : 'Tiến trình nền'}</Badge></td>
          <td>{e.message}</td><td>{e.path || '—'}</td><td><code>{e.request_id?.slice(0, 8) || '—'}</code></td></tr>)}</tbody></table></div> : <Empty title="Không có lỗi" />}
    </Card>
    <Exports />
  </div>;
}
