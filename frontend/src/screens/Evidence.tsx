// Chụp minh chứng: ảnh gắn TỪNG mục lỗi; mục không có ảnh bắt buộc nhập lý do; chỉ "Gửi minh chứng" khi đủ.
import { useState } from 'react';
import { Camera } from 'lucide-react';
import { api, get, post, uuid } from '../lib/api';
import type { Row } from '../lib/api';
import { compressImage } from '../lib/image';
import { LEVEL_LABELS } from '../lib/labels';
import { navigate } from '../lib/router';
import { Alert, Badge, Button, Card, ErrorBox, Loading, PageHeader, TextArea, useLoad, useToast } from '../ui/components';
import { enqueuePhoto } from '../lib/offline';

export function Photo({ photo, label }: { photo: Row; label: string }) {
  return <figure className="photo"><a href={`/api/v1/attachments/${photo.id}`} target="_blank" rel="noreferrer">
    <img src={`/api/v1/attachments/${photo.id}`} alt={label} loading="lazy" /></a>
    <figcaption className="muted" title={`SHA-256: ${photo.sha256}`}>SHA-256 {photo.sha256.slice(0, 12)}…</figcaption></figure>;
}

export async function uploadPhoto(caseId: string, itemId: string, file: File, kind: 'truoc' | 'sau') {
  const blob = await compressImage(file);
  const photoId = uuid();
  const form = () => { const f = new FormData(); f.append('file', blob, 'anh.jpg'); f.append('kind', kind); f.append('photo_id', photoId); f.append('taken_at', new Date().toISOString()); return f; };
  try {
    return await api(`/defect-cases/${caseId}/items/${itemId}/photos`, { method: 'POST', body: form(), key: photoId });
  } catch (e: any) {
    if (e?.code === 'NETWORK' || e?.code === 'SERVER_STARTING') { await enqueuePhoto({ id: photoId, caseId, itemId, kind, blob }); return null; }
    throw e;
  }
}

export default function Evidence({ id }: { id: string }) {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get(`/defect-cases/${id}`, s), [id]);
  const [reasons, setReasons] = useState<Row>({});
  const [uploading, setUploading] = useState<Row>({});
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState('');
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const items: Row[] = data.items;
  const ready = items.every((i) => i.photos.length > 0 || (reasons[i.id] || i.no_photo_reason || '').trim().length >= 3);
  const onFiles = async (item: Row, files: FileList | null) => {
    if (!files?.length) return;
    setUploading((u) => ({ ...u, [item.id]: true }));
    try {
      let queued = 0;
      for (const file of Array.from(files)) { const r = await uploadPhoto(id, item.id, file, 'truoc'); if (!r) queued++; }
      toast(queued ? `Mất mạng: ${queued} ảnh đã lưu trên máy, sẽ tự gửi khi có mạng` : 'Đã tải ảnh', queued ? 'info' : 'ok');
      reload();
    } catch (e: any) { toast(e.message, 'error'); } finally { setUploading((u) => ({ ...u, [item.id]: false })); }
  };
  const submit = async () => {
    setBusy(true); setSubmitError('');
    const no_photo_reasons = Object.fromEntries(items.filter((i) => !i.photos.length).map((i) => [i.id, (reasons[i.id] ?? i.no_photo_reason ?? '').trim()]));
    try { await post(`/defect-cases/${id}/evidence/submit`, { row_version: data.row_version, no_photo_reasons }); toast('Đã gửi minh chứng'); navigate(`/de-xuat/${id}`, true); }
    catch (e: any) { setSubmitError(e.message); reload(); } finally { setBusy(false); }
  };
  const accepting = ['nhap', 'cho_minh_chung'].includes(data.status);
  return <div className="page narrow">
    <PageHeader title={`Chụp minh chứng ${data.code}`} subtitle={`${data.product.name} · Serial ${data.serial_number}`} onBack={() => navigate(`/de-xuat/${id}`)} />
    {!accepting && <Alert tone="info">Đề xuất không còn ở bước chụp minh chứng.</Alert>}
    {data.history.filter((h: Row) => h.action === 'tu_choi').slice(-1).map((h: Row) => <Alert key={h.at} tone="warn" title={`Giám sát đã từ chối: ${h.reason}`}>Chụp lại hoặc bổ sung ảnh rồi gửi lại.</Alert>)}
    {items.map((item, n) => <Card key={item.id} title={<>{n + 1}. {item.name} × {item.occurrence_count} · {LEVEL_LABELS[item.level]} {item.priority && <Badge tone="priority">Ưu tiên</Badge>}</>}>
      <div className="photo-grid">{item.photos.map((p: Row, k: number) => <Photo key={p.id} photo={p} label={`Ảnh ${k + 1} của ${item.name}`} />)}</div>
      {item.photos.length ? <Badge tone="ok">Đã có {item.photos.length} ảnh</Badge> : <Badge tone="warn">Chưa có ảnh</Badge>}
      {accepting && <label className="btn btn-primary file-btn">
        <Camera size={18} aria-hidden /> {uploading[item.id] ? 'Đang tải…' : 'Chụp / chọn ảnh'}
        <input type="file" accept="image/*" capture="environment" multiple onChange={(e) => { onFiles(item, e.target.files); e.target.value = ''; }} disabled={uploading[item.id]} />
      </label>}
      {!item.photos.length && accepting && <TextArea label="Không có ảnh – lý do" required value={reasons[item.id] ?? item.no_photo_reason ?? ''} onChange={(e) => setReasons({ ...reasons, [item.id]: e.target.value })} hint="Bắt buộc khi mục này không có ảnh." />}
    </Card>)}
    {submitError && <p className="error-text" role="alert">{submitError}</p>}
    {data.status === 'cho_minh_chung' && <div className="actions-bar sticky-actions">
      <Button variant="primary" busy={busy} disabled={!ready} onClick={submit}>Gửi minh chứng</Button>
      {!ready && <span className="muted">Mỗi mục cần ít nhất 1 ảnh hoặc lý do.</span>}
    </div>}
  </div>;
}
