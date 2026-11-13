// Chi tiết đề xuất: thông tin sản phẩm, mục lỗi + ảnh trước/sau, chi phí, LỊCH SỬ ĐẦY ĐỦ (chỉ đọc), các nút theo trạng thái.
import { useState } from 'react';
import type { ReactNode } from 'react';
import { download, get, post } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime, relativeDeadline } from '../lib/format';
import { LEVEL_LABELS, STATUS_LABELS } from '../lib/labels';
import { navigate } from '../lib/router';
import { useSession } from '../lib/session';
import { Alert, Badge, Button, Card, ConfirmDialog, ErrorBox, Loading, PageHeader, StatusBadge, useLoad, useToast } from '../ui/components';
import { Photo } from './Evidence';

const ACTION_LABELS: Row = {
  gui_de_xuat: 'Gửi đề xuất', xac_nhan_loi: 'Xác nhận lỗi', tu_choi: 'Từ chối', phe_duyet: 'Phê duyệt', cap_tren_tu_choi: 'Từ chối',
  dong_de_xuat: 'Đóng đề xuất', yeu_cau_lam_lai: 'Yêu cầu làm lại', huy_nhap: 'Hủy nháp', huy_de_xuat: 'Hủy đề xuất',
};
const NEEDS_REASON = ['tu_choi', 'cap_tren_tu_choi', 'yeu_cau_lam_lai', 'huy_nhap', 'huy_de_xuat'];
const DANGER = ['tu_choi', 'cap_tren_tu_choi', 'yeu_cau_lam_lai', 'huy_nhap', 'huy_de_xuat'];

export function Timeline({ entries }: { entries: Row[] }) {
  return <ol className="timeline">{entries.map((h, n) => <li key={n} className={`tl-${h.actor_kind}`}>
    <div className="tl-head"><strong>{h.label}</strong>{h.kind === 'trang_thai' && h.to_label && <span className="muted"> → {h.to_label}</span>}
      {h.actor_kind === 'tu_dong' && <Badge tone="info">Hệ thống tự động</Badge>}</div>
    <div className="muted">{h.actor} · {formatTime(h.at)}</div>
    {h.reason && <div className="tl-reason">Lý do: {h.reason}</div>}
    {h.meta?.confidence !== undefined && <div className="muted">Độ tin cậy: {Math.round(h.meta.confidence * 100)}%</div>}
  </li>)}</ol>;
}

/** Vùng mở rộng do các bước sau gắn vào (duyệt, phương án, chi phí…). */
export const DETAIL_SECTIONS: ((p: Row, reload: () => void) => ReactNode)[] = [];

export default function Detail({ id }: { id: string }) {
  const { user } = useSession();
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get(`/defect-cases/${id}`, s), [id]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const p = data;
  const act = async (action: string, reason?: string) => {
    setBusy(true);
    try { await post(`/defect-cases/${id}/transitions`, { action, row_version: p.row_version, reason: reason || null }); toast(`Đã ${ACTION_LABELS[action].toLowerCase()}`); reload(); window.dispatchEvent(new Event('traceq:notifications')); }
    catch (e: any) { toast(e.message, 'error'); reload(); } finally { setBusy(false); }
  };
  const simple = p.allowed_actions.filter((a: string) => ACTION_LABELS[a] && !['gui_de_xuat'].includes(a));
  const confirmedBy = p.history.filter((h: Row) => h.action === 'xac_nhan_loi').slice(-1)[0];
  return <div className="page">
    <PageHeader title={p.code} subtitle={<>{p.product.name} · Serial {p.serial_number}</>} onBack={() => history.back()} actions={<>
      <Button onClick={() => navigate(`/de-xuat/${id}/tong-quan`)}>Tờ tổng quan</Button>
      <Button onClick={() => download(`/defect-cases/${id}/pdf`, `${p.code}.pdf`).catch((e) => toast(e.message, 'error'))}>Xuất PDF</Button>
    </>} />
    <div className="status-row"><StatusBadge status={p.status} />{p.priority && <Badge tone="priority">Ưu tiên</Badge>}{p.overdue && <Badge tone="error">Quá hạn</Badge>}
      {p.deadline_at && !['da_dong', 'da_huy'].includes(p.status) && <span className="muted">Hạn xử lý: {formatTime(p.deadline_at)} ({relativeDeadline(p.deadline_at)})</span>}</div>
    {confirmedBy && <Alert tone="ok">Đề xuất đã được xác nhận bởi {confirmedBy.actor}{confirmedBy.actor_kind === 'tu_dong' ? '' : ''} lúc {formatTime(confirmedBy.at)}.</Alert>}
    {p.status === 'cho_minh_chung' && p.creator.id === user.id && <Alert tone="info" title="Việc tiếp theo: chụp minh chứng">
      <Button variant="primary" onClick={() => navigate(`/de-xuat/${id}/minh-chung`)}>Chụp minh chứng</Button></Alert>}
    {p.status === 'nhap' && p.creator.id === user.id && <div className="actions-bar"><Button onClick={() => navigate(`/tao/${id}`)}>Sửa nháp</Button><Button variant="primary" onClick={() => navigate(`/de-xuat/${id}/tong-quan`)}>Xem tờ tổng quan</Button></div>}
    {DETAIL_SECTIONS.map((section, n) => <div key={n}>{section(p, reload)}</div>)}
    {simple.length > 0 && <div className="actions-bar sticky-actions">{simple.map((a: string) => <Button key={a} variant={DANGER.includes(a) ? 'danger' : 'primary'} busy={busy}
      onClick={() => NEEDS_REASON.includes(a) ? setConfirm(a) : act(a)}>{ACTION_LABELS[a]}</Button>)}</div>}
    <div className="grid-2">
      <Card title="Sản phẩm">
        <dl className="kv"><dt>Sản phẩm</dt><dd>{p.product.name} ({p.product.sku})</dd><dt>Serial</dt><dd>{p.serial_number}</dd>
          <dt>Lô</dt><dd>{p.batch.lot_code}</dd><dt>Ca / công đoạn</dt><dd>{p.inspection_session.shift} · {p.inspection_session.stage} · {p.inspection_session.line}</dd>
          <dt>Người tạo</dt><dd>{p.creator.display_name}</dd><dt>Giám sát</dt><dd>{p.supervisor?.display_name || '—'}</dd>
          <dt>Ngày tạo</dt><dd>{formatTime(p.created_at)}</dd><dt>Lịch sử sản phẩm</dt><dd>{p.previous_proposals} đề xuất khác</dd></dl>
      </Card>
      <Card title="Lịch sử đầy đủ"><Timeline entries={p.history} /></Card>
    </div>
    <Card title="Mục lỗi và minh chứng">
      {p.items.map((i: Row, n: number) => <section key={i.id} className="item-view">
        <h3>{n + 1}. {i.name} × {i.occurrence_count} · {LEVEL_LABELS[i.level]} {i.priority && <Badge tone="priority">Ưu tiên</Badge>}</h3>
        {i.criteria && <p className="muted">Tiêu chí: {i.criteria}</p>}{i.note && <p>Ghi chú: {i.note}</p>}
        <div className="before-after">
          <div><h4>Trước xử lý</h4>{i.photos?.length ? <div className="photo-grid">{i.photos.map((ph: Row, k: number) => <Photo key={ph.id} photo={ph} label={`Ảnh minh chứng ${k + 1} của ${i.name}`} />)}</div> : <p className="muted">{i.no_photo_reason ? `Không có ảnh – lý do: ${i.no_photo_reason}` : 'Chưa có ảnh'}</p>}</div>
          {(i.after_photos?.length > 0 || ['cho_dong', 'da_dong'].includes(p.status)) && <div><h4>Sau xử lý</h4>{i.after_photos?.length ? <div className="photo-grid">{i.after_photos.map((ph: Row, k: number) => <Photo key={ph.id} photo={ph} label={`Ảnh sau xử lý ${k + 1} của ${i.name}`} />)}</div> : <p className="muted">Không có ảnh sau xử lý</p>}</div>}
        </div>
      </section>)}
    </Card>

    {confirm && <ConfirmDialog title={ACTION_LABELS[confirm]} danger requireReason confirmLabel={ACTION_LABELS[confirm]}
      message={confirm === 'tu_choi' ? 'Đề xuất sẽ quay lại bước chụp minh chứng.' : confirm === 'cap_tren_tu_choi' ? 'Đề xuất quay lại bước chọn phương án.' : confirm === 'yeu_cau_lam_lai' ? 'Đề xuất quay lại bước Đang xử lý.' : `Đề xuất sẽ chuyển sang "${STATUS_LABELS.da_huy}". Lịch sử được giữ nguyên.`}
      onClose={() => setConfirm(null)} onConfirm={(reason) => act(confirm, reason)} />}
  </div>;
}
