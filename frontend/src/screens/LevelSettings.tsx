// Cài đặt loại lỗi: tối đa 3 mức Nhẹ/Trung bình/Nặng do Quản lý cài; cờ ưu tiên ở cấp loại lỗi.
import { useState } from 'react';
import { get, put } from '../lib/api';
import type { Row } from '../lib/api';
import { formatDate, formatMoney, vnDateInput } from '../lib/format';
import { COST_MODE_LABELS, LEVEL_LABELS, METHOD_LABELS, METHODS } from '../lib/labels';
import { Alert, Badge, Button, Checkbox, Empty, ErrorBox, Loading, Modal, Segmented, TextArea, TextInput, useLoad } from '../ui/components';

function PriceHistory({ level, onClose }: { level: Row; onClose: () => void }) {
  const { data, loading, error } = useLoad((s) => get(`/defect-levels/${level.id}/price-history`, s), [level.id]);
  return <Modal title={`Lịch sử giá · ${LEVEL_LABELS[level.level]}`} onClose={onClose}>
    {loading ? <Loading /> : error ? <ErrorBox error={error} /> : data.items.length ? <div className="table-wrap"><table className="table">
      <thead><tr><th>Hiệu lực từ</th><th className="num">Giá</th><th>Người đổi</th><th>Lý do</th></tr></thead>
      <tbody>{data.items.map((h: Row) => <tr key={h.id}><td>{formatDate(h.effective_from)}</td><td className="num">{formatMoney(h.price)}</td><td>{h.changed_by_name}</td><td>{h.reason || '—'}</td></tr>)}</tbody>
    </table></div> : <Empty title="Chưa có lịch sử giá" />}
  </Modal>;
}

export default function LevelSettings({ typeId, onClose, onSaved }: { typeId: string; onClose: () => void; onSaved: () => void }) {
  const { data, loading, error } = useLoad((s) => get(`/defect-types/${typeId}/config`, s), [typeId]);
  const [draft, setDraft] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [history, setHistory] = useState<Row | null>(null);
  const [reason, setReason] = useState('');
  if (loading) return <Modal title="Cài đặt loại lỗi" onClose={onClose}><Loading /></Modal>;
  if (error) return <Modal title="Cài đặt loại lỗi" onClose={onClose}><ErrorBox error={error} /></Modal>;
  const value: Row = draft || { priority_flag: data.priority_flag, cost_mode: data.cost_mode, levels: data.levels.map((l: Row) => ({ ...l, market_price: l.market_price ?? '', price_effective_from: l.price_effective_from || '' })) };
  const set = (patch: Row) => setDraft({ ...value, ...patch });
  const setLevel = (i: number, patch: Row) => set({ levels: value.levels.map((l: Row, j: number) => j === i ? { ...l, ...patch } : l) });
  const save = async () => {
    setBusy(true); setSaveError('');
    try {
      await put(`/defect-types/${typeId}/config`, {
        row_version: data.row_version, priority_flag: value.priority_flag, cost_mode: value.cost_mode, reason: reason || 'Cập nhật cài đặt loại lỗi',
        levels: value.levels.map((l: Row) => ({ level: l.level, enabled: l.enabled, criteria: l.criteria || '', market_price: l.market_price === '' ? null : String(l.market_price),
          price_effective_from: l.market_price === '' ? null : (l.price_effective_from || vnDateInput()), deadline_hours: l.deadline_hours ? Number(l.deadline_hours) : null, suggested_actions: l.suggested_actions })),
      });
      onSaved(); onClose();
    } catch (e: any) { setSaveError(e.message); } finally { setBusy(false); }
  };
  return <Modal title={`Cài đặt loại lỗi: ${data.name}`} onClose={onClose} wide footer={<><Button onClick={onClose}>Hủy bỏ</Button><Button variant="primary" busy={busy} onClick={save}>Lưu cài đặt</Button></>}>
    <div className={`priority-toggle ${value.priority_flag ? 'on' : ''}`}>
      <Checkbox checked={value.priority_flag} onChange={(e) => set({ priority_flag: e.target.checked })}
        label={<strong>Lỗi đặc biệt: luôn cảnh báo ưu tiên</strong>}
        hint="Bật một lần ở đây thì MỌI mức bên trong (kể cả Nhẹ) đều gắn cờ: đẩy lên đầu danh sách, báo ngay Quản lý; Quản lý trực tiếp duyệt (không bao giờ tự duyệt)." />
    </div>
    <Segmented label="Cách tính chi phí ước tính" value={value.cost_mode} onChange={(v) => set({ cost_mode: v })}
      options={Object.entries(COST_MODE_LABELS).map(([k, label]) => ({ value: k, label }))} />
    <p className="hint">Tự động: dùng dữ liệu thực tế khi đủ số lần sửa tối thiểu (cài ở Thiết lập), ngược lại dùng giá thị trường.</p>
    <Alert tone="info">App không tự quyết mức và không suy mức từ số lượng. Người tạo phải chọn một trong các mức đang bật dưới đây.</Alert>
    <div className="folder-levels">{value.levels.map((l: Row, i: number) => <section key={l.level} className={`level-card ${l.enabled ? '' : 'off'}`}>
      <header className="card-head"><h3>{LEVEL_LABELS[l.level]}</h3>{value.priority_flag && <Badge tone="priority">Ưu tiên</Badge>}{!l.enabled && <Badge>Đang tắt</Badge>}</header>
      <Checkbox checked={l.enabled} onChange={(e) => setLevel(i, { enabled: e.target.checked })} label={`Dùng mức ${LEVEL_LABELS[l.level]}`} />
      {l.enabled && <>
        <TextArea label="Tiêu chí" required value={l.criteria} onChange={(e) => setLevel(i, { criteria: e.target.value })} hint="Hiện cho người tạo khi chọn mức này." />
        <div className="grid-2">
          <TextInput label="Giá thị trường (VND/vị trí lỗi)" inputMode="numeric" value={l.market_price} onChange={(e) => setLevel(i, { market_price: e.target.value.replace(/[^\d]/g, '') })} />
          <TextInput label="Ngày hiệu lực của giá" type="date" value={l.price_effective_from || vnDateInput()} onChange={(e) => setLevel(i, { price_effective_from: e.target.value })} />
          <TextInput label="Hạn xử lý (giờ)" inputMode="numeric" required value={l.deadline_hours || ''} onChange={(e) => setLevel(i, { deadline_hours: e.target.value.replace(/[^\d]/g, '') })} />
          <div className="field"><span className="field-label">Chi phí theo dữ liệu thực tế</span>
            <output className="readonly">{l.actual?.median_per_location ? `${formatMoney(l.actual.median_per_location)}/vị trí (từ ${l.actual.sample_n} lần sửa)` : `Chưa đủ dữ liệu (từ ${l.actual?.sample_n || 0} lần sửa)`}</output></div>
        </div>
        {l.id && l.current_price && <Button variant="ghost" onClick={() => setHistory(l)}>Xem lịch sử giá</Button>}
        <fieldset className="segmented"><legend>Phương án gợi ý</legend><div className="segmented-row">{METHODS.map((m) => <label key={m} className={`seg ${l.suggested_actions.includes(m) ? 'active' : ''}`}>
          <input type="checkbox" checked={l.suggested_actions.includes(m)} onChange={(e) => setLevel(i, { suggested_actions: e.target.checked ? [...l.suggested_actions, m] : l.suggested_actions.filter((x: string) => x !== m) })} />
          <span>{METHOD_LABELS[m]}</span></label>)}</div></fieldset>
      </>}
    </section>)}</div>
    <TextInput label="Lý do thay đổi" value={reason} onChange={(e) => setReason(e.target.value)} hint="Ghi vào lịch sử giá và nhật ký." />
    {saveError && <p className="error-text" role="alert">{saveError}</p>}
    {history && <PriceHistory level={history} onClose={() => setHistory(null)} />}
  </Modal>;
}
