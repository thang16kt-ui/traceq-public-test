// Tờ tổng quan (A4 xem trước) – KHÔNG có chỗ ký. "Gửi đề xuất" → gửi giám sát + QR. Sau khi gửi: QR lớn, Tải QR, Xong.
import { useState } from 'react';
import { download, get, post } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { LEVEL_LABELS } from '../lib/labels';
import { navigate } from '../lib/router';
import { useSession } from '../lib/session';
import { Alert, Button, ErrorBox, Loading, useLoad, useToast } from '../ui/components';

export function SheetPaper({ p }: { p: Row }) {
  return <article className="a4" aria-label="Tờ tổng quan đề xuất">
    <header className="a4-head"><div><strong>TraceQ</strong><div className="muted">Tờ tổng quan đề xuất</div></div><div className="a4-code">{p.code}</div></header>
    <h1 className="a4-title">TỜ TỔNG QUAN ĐỀ XUẤT SẢN PHẨM LỖI</h1>
    <dl className="kv a4-kv">
      <dt>Mã đề xuất</dt><dd>{p.code}</dd>
      <dt>Ngày tạo</dt><dd>{formatTime(p.created_at)}</dd>
      <dt>Người tạo</dt><dd>{p.creator.display_name}</dd>
      <dt>Sản phẩm</dt><dd>{p.product.name} ({p.product.sku})</dd>
      <dt>Serial</dt><dd>{p.serial_number}</dd>
      <dt>Lô / ca / công đoạn</dt><dd>{p.batch.lot_code} · {p.inspection_session.shift} · {p.inspection_session.stage} · {p.inspection_session.line}</dd>
      <dt>Giám sát</dt><dd>{p.supervisor?.display_name || 'Chưa gán (quản lý sẽ xử lý)'}</dd>
    </dl>
    <table className="table a4-table"><thead><tr><th>STT</th><th>Loại lỗi</th><th className="num">SL</th><th>Mức độ</th></tr></thead>
      <tbody>{p.items.map((i: Row, n: number) => <tr key={i.id}><td>{n + 1}</td><td>{i.name}{i.priority && <strong> (ƯU TIÊN)</strong>}{i.note && <div className="muted">{i.note}</div>}</td><td className="num">{i.occurrence_count}</td><td>{LEVEL_LABELS[i.level]}</td></tr>)}</tbody></table>
    {p.note && <p><strong>Ghi chú:</strong> {p.note}</p>}
    <footer className="a4-foot muted">SL = số lượng lỗi (số vị trí lỗi trên sản phẩm). In lúc {formatTime(new Date())}.</footer>
  </article>;
}

export default function Sheet({ id }: { id: string }) {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get(`/defect-cases/${id}`, s), [id]);
  const [busy, setBusy] = useState(false);
  const [sendError, setSendError] = useState('');
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const send = async () => {
    setBusy(true); setSendError('');
    try { await post(`/defect-cases/${id}/transitions`, { action: 'gui_de_xuat', row_version: data.row_version }); toast(`Đã gửi ${data.code} tới giám sát`); navigate(`/de-xuat/${id}/da-gui`, true); }
    catch (e: any) { setSendError(e.message); } finally { setBusy(false); }
  };
  return <div className="page">
    <div className="actions-bar no-print">
      <Button onClick={() => navigate(`/de-xuat/${id}`)}>Quay lại</Button>
      {data.status === 'nhap' && <Button onClick={() => navigate(`/tao/${id}`)}>Sửa</Button>}
      <Button onClick={() => window.print()}>In</Button>
      {data.allowed_actions.includes('gui_de_xuat') && <Button variant="primary" busy={busy} onClick={send}>Gửi đề xuất</Button>}
    </div>
    {data.priority && <div className="no-print"><Alert tone="priority" title="Đề xuất có lỗi ưu tiên">Khi gửi, giám sát và quản lý được báo ngay.</Alert></div>}
    {sendError && <p className="error-text no-print" role="alert">{sendError}</p>}
    <SheetPaper p={data} />
  </div>;
}

export function AfterSubmit({ id }: { id: string }) {
  const { user } = useSession();
  const toast = useToast();
  const { data, loading, error } = useLoad((s) => get(`/defect-cases/${id}`, s), [id]);
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return <div className="page narrow center">
    <Alert tone="ok" title={`Đã gửi ${data.code}`}>Đề xuất đã gửi tới {data.supervisor?.display_name || 'quản lý'}. Dán QR lên sản phẩm để chụp minh chứng và theo dõi.</Alert>
    <img className="qr-big" src={`/api/v1/units/${data.unit_id}/label?format=png`} alt={`Tem QR ${data.code}, serial ${data.serial_number}`} />
    <p className="qr-caption"><strong>{data.code}</strong> · Serial {data.serial_number}</p>
    <div className="actions-bar">
      <Button onClick={() => download(`/units/${data.unit_id}/label?format=png`, `QR-${data.code}.png`).catch((e) => toast(e.message, 'error'))}>Tải QR</Button>
      <Button onClick={() => download(`/units/${data.unit_id}/label?format=pdf`, `QR-${data.code}.pdf`).catch((e) => toast(e.message, 'error'))}>Tải tem PDF để in</Button>
      {data.status === 'cho_minh_chung' && data.creator.id === user.id && <Button onClick={() => navigate(`/de-xuat/${id}/minh-chung`)}>Chụp minh chứng ngay</Button>}
      <Button variant="primary" onClick={() => navigate('/viec-cua-toi')}>Xong</Button>
    </div>
  </div>;
}
