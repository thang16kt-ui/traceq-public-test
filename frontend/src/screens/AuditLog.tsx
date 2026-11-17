// Nhật ký: mọi hành động nhạy cảm (đăng nhập, đổi cài đặt, chuyển trạng thái, xuất báo cáo, khóa tài khoản…). Chỉ đọc.
import { useState } from 'react';
import { get, query } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { Empty, ErrorBox, Loading, Modal, PageHeader, Pager, Select, useLoad } from '../ui/components';

export const AUDIT_LABELS: Record<string, string> = {
  login: 'Đăng nhập', logout: 'Đăng xuất', auto_lock: 'Tự khóa do sai mật khẩu', lock_user: 'Khóa tài khoản', unlock_user: 'Mở khóa tài khoản',
  reset_password: 'Đặt lại mật khẩu', change_password: 'Đổi mật khẩu', create_user: 'Tạo người dùng', update_user: 'Sửa người dùng',
  revoke_session: 'Đăng xuất thiết bị', revoke_other_sessions: 'Đăng xuất thiết bị khác', revoke_all_sessions: 'Đăng xuất mọi thiết bị',
  update_setting: 'Đổi cài đặt', update_levels: 'Đổi cài đặt mức lỗi', create: 'Tạo mới', update: 'Sửa', delete: 'Xóa', deactivate: 'Ngừng sử dụng',
  restore: 'Khôi phục', transition: 'Chuyển trạng thái', upload: 'Tải ảnh minh chứng', export_report: 'Xuất báo cáo', export_proposal_pdf: 'Xuất PDF đề xuất',
  seed_demo_user: 'Tạo tài khoản mẫu', bootstrap_user: 'Tạo tài khoản (CLI)', enqueue: 'Xếp hàng xuất dữ liệu', auto_approval: 'Tự động duyệt',
};
const ENTITY_LABELS: Record<string, string> = { users: 'Người dùng', defect_cases: 'Đề xuất', app_settings: 'Cài đặt', defect_types: 'Loại lỗi', product_types: 'Sản phẩm', batches: 'Lô', attachments: 'Minh chứng', report_exports: 'Báo cáo', inspection_sessions: 'Đợt kiểm tra' };

export default function AuditLog() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const [entity, setEntity] = useState('');
  const [open, setOpen] = useState<Row | null>(null);
  const { data, loading, error, reload } = useLoad((s) => get('/audit-logs' + query({ page, page_size: 50, action, entity_type: entity }), s), [page, action, entity]);
  return <div className="page">
    <PageHeader title="Nhật ký" subtitle="Ghi lại mọi thao tác nhạy cảm; không sửa, không xóa được." />
    <div className="toolbar">
      <div style={{ minWidth: 220 }}><Select label="Hành động" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
        <option value="">Tất cả</option>{(data?.actions || []).map((a: string) => <option key={a} value={a}>{AUDIT_LABELS[a] || a}</option>)}</Select></div>
      <div style={{ minWidth: 220 }}><Select label="Đối tượng" value={entity} onChange={(e) => { setEntity(e.target.value); setPage(1); }}>
        <option value="">Tất cả</option>{Object.entries(ENTITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></div>
    </div>
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <>
      <div className="table-wrap"><table className="table"><thead><tr><th>Thời gian</th><th>Người thực hiện</th><th>Hành động</th><th>Đối tượng</th><th>Lý do</th><th><span className="sr-only">Chi tiết</span></th></tr></thead>
        <tbody>{data.items.map((l: Row) => <tr key={l.id}>
          <td>{formatTime(l.created_at)}</td><td>{l.actor_name}</td>
          <td>{AUDIT_LABELS[l.action] || l.action}{l.action === 'transition' && l.changed_fields?.action && <div className="muted">{l.changed_fields.from} → {l.changed_fields.to}{l.changed_fields.actor_kind === 'tu_dong' ? ' (tự động)' : ''}</div>}</td>
          <td>{ENTITY_LABELS[l.entity_type] || l.entity_type}</td><td>{l.reason || '—'}</td>
          <td><button type="button" className="btn btn-ghost" onClick={() => setOpen(l)}>Xem</button></td></tr>)}</tbody></table></div>
      {!data.items.length && <Empty title="Không có bản ghi" />}
      <Pager page={page} pageSize={50} total={data.total} onPage={setPage} />
    </>}
    {open && <Modal title="Chi tiết nhật ký" onClose={() => setOpen(null)} wide><pre className="code-block">{JSON.stringify(open, null, 2)}</pre></Modal>}
  </div>;
}
