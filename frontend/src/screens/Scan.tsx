// Quét QR bằng camera (cần HTTPS) hoặc nhập mã tay. Quét chỉ để TRA CỨU: không thay đổi dữ liệu.
import { useEffect, useRef, useState } from 'react';
import { ApiError, get } from '../lib/api';
import type { Row } from '../lib/api';
import { navigate } from '../lib/router';
import { hasRole, useSession } from '../lib/session';
import { Alert, Button, Card, Empty, Loading, Modal, PageHeader, TextInput } from '../ui/components';
import { ProposalCard } from './Proposals';

export function QrScanner({ onResult, onClose }: { onResult: (text: string) => void; onClose: () => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let controls: { stop: () => void } | null = null;
    let done = false;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError('Trình duyệt chỉ cho dùng camera qua HTTPS. Hãy nhập mã in dưới QR.');
      return;
    }
    import('@zxing/browser').then(({ BrowserQRCodeReader }) => {
      const reader = new BrowserQRCodeReader();
      return reader.decodeFromConstraints({ video: { facingMode: 'environment' } }, video.current!, (result) => {
        if (result && !done) { done = true; controls?.stop(); onResult(result.getText()); }
      }).then((c) => { controls = c; if (done) c.stop(); });
    }).catch((e) => setError(e?.name === 'NotAllowedError' ? 'Bạn chưa cho phép dùng camera. Bật quyền camera trong cài đặt trình duyệt hoặc nhập mã tay.' : 'Không mở được camera. Hãy nhập mã tay.'));
    return () => { done = true; controls?.stop(); };
  }, [onResult]);
  return <Modal title="Quét QR" onClose={onClose}>
    {error ? <Alert tone="warn">{error}</Alert> : <div className="scanner"><video ref={video} muted playsInline aria-label="Khung camera quét QR" /><p className="muted">Đưa mã QR vào giữa khung.</p></div>}
  </Modal>;
}

export default function Scan({ token }: { token?: string }) {
  const { user, activeRole } = useSession();
  const [code, setCode] = useState('');
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<Row | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const lookup = async (text: string) => {
    const match = /\/q\/([^/?#]+)/.exec(text);
    const key = match ? decodeURIComponent(match[1]) : text.trim();
    if (!key) return;
    setLoading(true); setError(''); setResult(null);
    try { setResult(await get('/qr/' + encodeURIComponent(key))); }
    catch (e) { setResult(null); setError(e instanceof ApiError && e.status === 404 ? 'Chưa có sản phẩm này trong hệ thống.' : e instanceof Error ? e.message : 'Lỗi tra cứu'); setCode(key); }
    finally { setLoading(false); }
  };
  useEffect(() => { if (token) lookup(token); }, [token]);
  const open = result?.cases?.find((c: Row) => !['da_dong', 'da_huy'].includes(c.status));
  const creator = hasRole(user, 'nguoi_tao', 'quan_ly');
  return <div className="page narrow">
    <PageHeader title="Quét QR" subtitle="Quét QR trên sản phẩm để chụp minh chứng, duyệt hoặc xem lịch sử" />
    <Card>
      <Button variant="primary" className="block" onClick={() => setScanning(true)}>Mở camera quét QR</Button>
      <form className="row-inline" onSubmit={(e) => { e.preventDefault(); lookup(code); }}>
        <div className="grow"><TextInput label="Hoặc nhập serial / mã dưới QR" value={code} onChange={(e) => setCode(e.target.value)} /></div>
        <Button type="submit">Tra cứu</Button>
      </form>
    </Card>
    {scanning && <QrScanner onResult={(text) => { setScanning(false); lookup(text); }} onClose={() => setScanning(false)} />}
    {loading && <Loading />}
    {error && <Alert tone="warn" title={error}>{creator && code && <Button variant="primary" onClick={() => navigate('/tao?serial=' + encodeURIComponent(code))}>Tạo đề xuất cho serial {code}</Button>}</Alert>}
    {result && <Card title={`${result.product.name} · Serial ${result.unit.serial_number}`}>
      <p className="muted">Lô {result.batch.lot_code} · Lịch sử sản phẩm này: {result.history_count} đề xuất</p>
      {open && <div className="actions-bar">
        {open.status === 'cho_minh_chung' && open.creator?.id === user.id && <Button variant="primary" onClick={() => navigate(`/de-xuat/${open.id}/minh-chung`)}>Chụp minh chứng</Button>}
        <Button onClick={() => navigate(`/de-xuat/${open.id}`)}>Mở {open.code}</Button>
      </div>}
      {!open && creator && activeRole !== 'cap_tren' && <Button variant="primary" onClick={() => navigate('/tao?qr=' + encodeURIComponent(result.unit.qr_token))}>Tạo đề xuất mới cho sản phẩm này</Button>}
      <div className="card-list" style={{ marginTop: 12 }}>{result.cases.map((c: Row) => <ProposalCard key={c.id} p={c} />)}</div>
      {!result.cases.length && <Empty title="Bạn chưa có quyền xem đề xuất nào của sản phẩm này" />}
    </Card>}
  </div>;
}
