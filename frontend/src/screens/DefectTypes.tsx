// Danh mục loại lỗi: mỗi loại lỗi là một "thư mục", bên trong là các mức (cài ở hạng mục 4).
import { useState } from 'react';
import { get, patch, post, query } from '../lib/api';
import type { Row } from '../lib/api';
import { Badge, Button, Chips, ConfirmDialog, Empty, ErrorBox, Loading, Modal, PageHeader, TextInput, useLoad, useToast } from '../ui/components';
import { DeleteDialog, HistoryDialog, STATE_OPTIONS } from './Catalog';
import LevelSettings from './LevelSettings';
import { LEVEL_LABELS } from '../lib/labels';

function TypeForm({ item, onClose, onSaved }: { item?: Row; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ code: item?.code || '', name: item?.name || '', reason: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async () => {
    setBusy(true); setError('');
    try {
      if (item) await patch(`/defect-types/${item.id}`, { code: v.code, name: v.name, row_version: item.row_version, reason: v.reason || 'Sửa loại lỗi' });
      else await post('/defect-types', { code: v.code, name: v.name });
      onSaved(); onClose();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };
  return <Modal title={item ? 'Sửa loại lỗi' : 'Thêm loại lỗi'} onClose={onClose} footer={<><Button onClick={onClose}>Hủy bỏ</Button><Button variant="primary" busy={busy} onClick={submit} disabled={!v.code || !v.name}>Lưu</Button></>}>
    <TextInput label="Mã loại lỗi" required value={v.code} onChange={(e) => setV({ ...v, code: e.target.value })} />
    <TextInput label="Tên loại lỗi" required value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} hint="Đổi tên không làm thay đổi đề xuất cũ: đề xuất cũ giữ tên lúc ghi nhận." />
    {item && <TextInput label="Lý do thay đổi" value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} />}
    {error && <p className="error-text" role="alert">{error}</p>}
  </Modal>;
}

export default function DefectTypes() {
  const toast = useToast();
  const [state, setState] = useState<'active' | 'inactive' | 'all'>('active');
  const [modal, setModal] = useState<{ kind: string; item?: Row } | null>(null);
  const { data, loading, error, reload } = useLoad((s) => get('/defect-types' + query({ state, page_size: 100 }), s), [state]);
  return <div className="page">
    <PageHeader title="Danh mục lỗi" subtitle="Loại lỗi là thư mục; bên trong là các mức do quản lý cài." actions={<Button variant="primary" onClick={() => setModal({ kind: 'form' })}>Thêm loại lỗi</Button>} />
    <div className="toolbar"><Chips label="Trạng thái" value={state} onChange={setState} options={STATE_OPTIONS} /></div>
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <div className="folder-list">
      {data.items.map((t: Row) => <section key={t.id} className="card folder">
        <header className="card-head"><div><h2>{t.name}</h2><p className="muted">{t.code}</p></div>
          <div>{t.priority_flag && <Badge tone="priority">Ưu tiên</Badge>}{t.effective_active ? <Badge tone="ok">Đang dùng</Badge> : <Badge>Ngừng sử dụng</Badge>}{t.is_used && <Badge>Đã có dữ liệu</Badge>}</div></header>
        <ul className="level-summary">{(t.levels || []).map((l: Row) => <li key={l.level} className={l.enabled ? '' : 'off'}>
          <strong>{LEVEL_LABELS[l.level]}</strong> {l.enabled ? <span>{l.criteria || <Badge tone="warn">Chưa có tiêu chí</Badge>} · hạn {l.deadline_hours} giờ</span> : <Badge>Tắt</Badge>}</li>)}</ul>
        {!(t.levels || []).some((l: Row) => l.enabled) && <p className="error-text">Chưa bật mức nào: người tạo chưa chọn được loại lỗi này.</p>}
        <div className="row-actions">
          <Button variant="primary" onClick={() => setModal({ kind: 'levels', item: t })}>Cài đặt mức</Button>
          <Button onClick={() => setModal({ kind: 'form', item: t })}>Sửa tên</Button>
          {t.is_active ? <Button variant="danger" onClick={() => setModal({ kind: 'delete', item: t })}>{t.is_used ? 'Ngừng sử dụng' : 'Xóa'}</Button>
            : <Button onClick={() => setModal({ kind: 'restore', item: t })}>Khôi phục</Button>}
          <Button variant="ghost" onClick={() => setModal({ kind: 'history', item: t })}>Lịch sử</Button>
        </div>
      </section>)}
      {!data.items.length && <Empty title="Chưa có loại lỗi">Thêm loại lỗi đầu tiên, sau đó cài các mức Nhẹ/Trung bình/Nặng.</Empty>}
    </div>}
    {modal?.kind === 'form' && <TypeForm item={modal.item} onClose={() => setModal(null)} onSaved={() => { toast('Đã lưu loại lỗi'); reload(); }} />}
    {modal?.kind === 'delete' && <DeleteDialog kind="defect-types" item={modal.item!} label={modal.item!.name} onClose={() => setModal(null)} onDone={(op) => { toast(op === 'delete' ? 'Đã xóa' : 'Đã ngừng sử dụng'); reload(); }} />}
    {modal?.kind === 'restore' && <ConfirmDialog title={`Khôi phục “${modal.item!.name}”?`} requireReason confirmLabel="Khôi phục" onClose={() => setModal(null)} onConfirm={async (reason) => { await post(`/defect-types/${modal.item!.id}/restore`, { row_version: modal.item!.row_version, reason }); toast('Đã khôi phục'); reload(); }} />}
    {modal?.kind === 'levels' && <LevelSettings typeId={modal.item!.id} onClose={() => setModal(null)} onSaved={() => { toast('Đã lưu cài đặt'); reload(); }} />}
    {modal?.kind === 'history' && <HistoryDialog kind="defect-types" item={modal.item!} title={modal.item!.name} onClose={() => setModal(null)} />}
  </div>;
}
