// Tự động duyệt: Tắt / Chỉ gợi ý / Tự động cho từng bước; tiến độ điều kiện bật; Hiệu quả; kiểm tra mẫu; đảo ngược; kill switch.
import { useState } from 'react';
import { get, post, put } from '../lib/api';
import type { Row } from '../lib/api';
import { formatTime } from '../lib/format';
import { hasRole, useSession } from '../lib/session';
import { Alert, Badge, Button, Card, Checkbox, ConfirmDialog, Empty, ErrorBox, Loading, PageHeader, Segmented, TextInput, useLoad, useToast } from '../ui/components';

const MODES = [{ value: 'tat', label: 'Tắt' }, { value: 'goi_y', label: 'Chỉ gợi ý' }, { value: 'tu_dong', label: 'Tự động' }];
const ACTION: Row = { xac_nhan_loi: 'Xác nhận lỗi', chot_phuong_an: 'Chốt phương án', dong_de_xuat: 'Đóng đề xuất' };
const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 1000) / 10}%`);

function Progress({ value, target, label }: { value: number; target: number; label: string }) {
  const ratio = Math.min(1, target ? value / target : 0);
  return <div className="progress"><div className="progress-label">{label}</div><div className="progress-track" role="progressbar" aria-valuenow={Math.round(ratio * 100)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${ratio * 100}%` }} /></div></div>;
}

function Settings({ data, reload }: { data: Row; reload: () => void }) {
  const toast = useToast();
  const [cfg, setCfg] = useState<Row>(data.config);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await put('/auto-approval', { ...cfg, steps: Object.fromEntries(Object.entries(cfg.steps).map(([k, v]: any) => [k, { mode: v.mode }])), reason: 'Cập nhật cài đặt tự động duyệt' }); toast('Đã lưu'); reload(); }
    catch (e: any) { toast(e.message, 'error'); } finally { setBusy(false); }
  };
  const num = (k: string, label: string, hint: string, scale = 1) => <TextInput label={label} hint={hint} inputMode="decimal" value={String(Math.round(cfg[k] * scale * 1000) / 1000)}
    onChange={(e) => { const v = Number(e.target.value.replace(',', '.')); if (!Number.isNaN(v)) setCfg({ ...cfg, [k]: v / scale }); }} />;
  return <Card title="Cài đặt">
    {Object.entries(data.steps).map(([step, label]: any) => { const g = data.gates[step]; return <section key={step} className="auto-step">
      <h3>{label}</h3>
      <Segmented label="Chế độ" value={cfg.steps[step].mode} onChange={(v) => setCfg({ ...cfg, steps: { ...cfg.steps, [step]: { mode: v } } })}
        options={MODES.map((m) => ({ ...m, disabled: m.value === 'tu_dong' && cfg.steps[step].mode !== 'tu_dong' && (!g.ready || data.config.steps[step].mode !== 'goi_y') }))} />
      <Progress value={g.reviews} target={g.min_reviews} label={`Lượt duyệt ở chế độ gợi ý: ${g.reviews}/${g.min_reviews}`} />
      <p className="muted">Đồng thuận với người duyệt: <strong>{pct(g.agreement)}</strong> (mục tiêu {pct(g.target_agreement)}). {g.ready ? <Badge tone="ok">Đủ điều kiện bật Tự động</Badge> : <Badge>Chưa đủ điều kiện</Badge>}</p>
    </section>; })}
    <Alert tone="info" title="Lộ trình bắt buộc">Luật kiểm tra → Chỉ gợi ý (đo đồng thuận) → Tự động. Luôn do người duyệt: lỗi ưu tiên, mức Nặng, phương án Hủy, chi phí vượt ngưỡng cấp trên.</Alert>
    <div className="grid-3">
      {num('confidence_threshold', 'Ngưỡng tin cậy để tự duyệt (%)', 'Mặc định 90', 100)}
      {num('min_reviews', 'Số lượt duyệt tối thiểu', 'Mặc định 200')}
      {num('target_agreement', 'Đồng thuận mục tiêu (%)', 'Mặc định 95', 100)}
      {num('sample_rate', 'Tỷ lệ kiểm tra mẫu (%)', 'Mặc định 10', 100)}
      {num('reverse_hours', 'Cho đảo ngược trong (giờ)', 'Mặc định 24')}
      {num('pause_error_rate', 'Tự tạm dừng khi tỷ lệ sai vượt (%)', 'Theo từng loại lỗi', 100)}
      {num('pause_min_checks', 'Số mẫu tối thiểu để tạm dừng', 'Mặc định 10')}
      {num('new_type_min_samples', 'Loại lỗi mới: số mẫu tối thiểu', 'Mặc định 30')}
    </div>
    <Checkbox label="Loại lỗi/sản phẩm mới dưới N mẫu luôn do người duyệt" checked={cfg.new_type_rule} onChange={(e) => setCfg({ ...cfg, new_type_rule: e.target.checked })} />
    <Checkbox label="Tạm dừng toàn bộ tự động duyệt" checked={cfg.kill_switch} onChange={(e) => setCfg({ ...cfg, kill_switch: e.target.checked })} />
    <div className="actions-bar"><Button variant="primary" busy={busy} onClick={save}>Lưu cài đặt</Button>
      <Button onClick={async () => { await post('/auto-approval/retrain'); toast('Đã tính lại thống kê từ lịch sử quyết định'); reload(); }}>Huấn luyện lại</Button></div>
    <p className="muted">“Huấn luyện lại” tính lại thống kê đồng thuận từ toàn bộ lịch sử. Hệ thống dùng luật + thống kê đơn giản, không dùng mô hình phức tạp.</p>
  </Card>;
}

function Effectiveness({ canAct }: { canAct: boolean }) {
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get('/auto-approval/stats', s), []);
  const [reverse, setReverse] = useState<Row | null>(null);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  const check = async (id: string, result: 'dung' | 'sai') => {
    try { const r = await post(`/auto-approval/checks/${id}`, { result, note: result === 'sai' ? 'Quản lý đánh giá sai' : '' }); toast(result === 'sai' ? (r.returned_to_reviewer ? 'Đã trả về người duyệt' : 'Đã ghi Sai (đề xuất đã sang bước khác, xử lý thủ công)') : 'Đã ghi Đúng'); reload(); }
    catch (e: any) { toast(e.message, 'error'); }
  };
  const paused = Object.entries(data.paused_types || {});
  return <>
    {data.kill_switch && <Alert tone="error" title="Đang tạm dừng toàn bộ tự động duyệt">Mọi bước do người duyệt cho tới khi Quản lý bỏ chọn trong Cài đặt.</Alert>}
    {paused.map(([id, p]: any) => <Alert key={id} tone="warn" title={`Loại lỗi “${p.name}” đang bị tạm dừng tự động duyệt`}>{p.reason} · {formatTime(p.at)}
      {canAct && <Button onClick={async () => { await post(`/auto-approval/paused/${id}/resume`, { reason: 'Đã xem xét, cho chạy lại' }); reload(); }}>Cho chạy lại</Button>}</Alert>)}
    <Card title={`Hiệu quả (${data.days} ngày gần nhất)`}>
      <div className="table-wrap"><table className="table"><thead><tr><th>Bước</th><th>Chế độ</th><th className="num">Quyết định</th><th className="num">Tự duyệt</th><th className="num">Tỷ lệ tự duyệt</th><th className="num">TG duyệt TB (phút)</th><th className="num">Trước khi bật</th><th className="num">Bị đảo ngược</th><th className="num">Đồng thuận (gợi ý)</th><th className="num">Kiểm tra mẫu: sai/đã kiểm</th></tr></thead>
        <tbody>{Object.values(data.steps).map((s: any) => <tr key={s.label}><td>{s.label}</td><td>{MODES.find((m) => m.value === s.mode)?.label}</td><td className="num">{s.total}</td><td className="num">{s.auto}</td>
          <td className="num">{s.auto_rate == null ? '—' : s.auto_rate + '%'}</td><td className="num">{s.avg_minutes_now ?? '—'}</td><td className="num">{s.avg_minutes_before_auto ?? '—'}</td>
          <td className="num">{s.reversed}{s.reversed_rate != null ? ` (${s.reversed_rate}%)` : ''}</td><td className="num">{pct(s.gate.agreement)}</td><td className="num">{s.wrong}/{s.checked}</td></tr>)}</tbody></table></div>
      <p className="muted">Chỉ hiển thị số đo thực tế; không phải cam kết độ chính xác.</p>
    </Card>
    <Card title="Kiểm tra mẫu ngẫu nhiên">
      {data.pending_checks.length ? <ul className="list">{data.pending_checks.map((c: Row) => <li key={c.id} className="list-row"><div>
        <a href={`#/de-xuat/${c.case.id}`}><strong>{c.case.code}</strong></a> · {c.step_label}: {ACTION[c.decision.action]} · tin cậy {pct(c.decision.confidence)}
        <p className="muted">{c.decision.reason}</p></div>
        {canAct && <div className="row-actions"><Button onClick={() => check(c.id, 'dung')}>Đúng</Button><Button variant="danger" onClick={() => check(c.id, 'sai')}>Sai</Button></div>}</li>)}</ul>
        : <Empty title="Không có mẫu chờ kiểm tra" />}
    </Card>
    <Card title="Quyết định tự động còn đảo ngược được">
      {data.reversible.length ? <ul className="list">{data.reversible.map((d: Row) => <li key={d.id} className="list-row"><div>
        <a href={`#/de-xuat/${d.case.id}`}><strong>{d.case.code}</strong></a> · {d.step_label}: {ACTION[d.action]} lúc {formatTime(d.at)}<p className="muted">Hạn đảo ngược: {formatTime(d.reversible_until)}</p></div>
        {canAct && <Button variant="danger" onClick={() => setReverse(d)}>Đảo ngược</Button>}</li>)}</ul> : <Empty title="Không có quyết định tự động nào trong thời hạn đảo ngược" />}
    </Card>
    {reverse && <ConfirmDialog title={`Đảo ngược quyết định tự động ${reverse.case.code}`} danger requireReason confirmLabel="Đảo ngược" message="Đề xuất quay lại bước trước để người duyệt quyết định."
      onClose={() => setReverse(null)} onConfirm={async (reason) => { await post(`/auto-approval/decisions/${reverse.id}/reverse`, { reason }); toast('Đã đảo ngược'); reload(); }} />}
  </>;
}

export default function AutoApproval() {
  const { user } = useSession();
  const toast = useToast();
  const { data, loading, error, reload } = useLoad((s) => get('/auto-approval', s), []);
  const [kill, setKill] = useState(false);
  const canAct = hasRole(user, 'quan_ly');
  return <div className="page">
    <PageHeader title="Tự động duyệt" subtitle="Giảm thủ công ở phần duyệt, giữ người trong vòng kiểm soát"
      actions={canAct && <Button variant="danger" onClick={() => setKill(true)}>Tạm dừng toàn bộ tự động duyệt</Button>} />
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : <>
      {hasRole(user, 'quan_ly', 'admin') && <Settings key={JSON.stringify(data.config)} data={data} reload={reload} />}
      <Effectiveness canAct={canAct} />
    </>}
    {kill && <ConfirmDialog title="Tạm dừng toàn bộ tự động duyệt" danger requireReason confirmLabel="Tạm dừng ngay" message="Mọi bước sẽ do người duyệt cho tới khi bật lại."
      onClose={() => setKill(false)} onConfirm={async (reason) => { await post('/auto-approval/kill-switch', { reason }); toast('Đã tạm dừng toàn bộ'); reload(); }} />}
  </div>;
}
