// Tổng quan (Quản lý): bộ lọc kỳ/sản phẩm/loại lỗi; KPI; Pareto; chi phí theo tuần + dự báo; xu hướng; phương án; đề xuất cần xử lý.
import { useState } from 'react';
import { download, get, query } from '../lib/api';
import { navigate } from '../lib/router';
import type { Row } from '../lib/api';
import { formatMoney, formatNumber, formatPercent, vnDateInput } from '../lib/format';
import { Alert, Button, Card, Chips, ErrorBox, Loading, PageHeader, Select, TextInput, useLoad, useToast } from '../ui/components';
import { MethodShare, ParetoChart, WeeklyCostChart } from '../ui/charts';
import ProposalList from './Proposals';

type Preset = '7' | '30' | 'thang' | 'tuy_chon';

function range(preset: Preset, from: string, to: string) {
  const today = new Date();
  if (preset === 'tuy_chon') return { date_from: from, date_to: to };
  if (preset === 'thang') return { date_from: vnDateInput(today).slice(0, 8) + '01', date_to: vnDateInput(today) };
  return { date_from: vnDateInput(new Date(Date.now() - (Number(preset) - 1) * 86400000)), date_to: vnDateInput(today) };
}

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return <div className={`kpi ${tone ? 'kpi-' + tone : ''}`}><span className="kpi-label">{label}</span><strong className="kpi-value">{value}</strong>{hint && <span className="kpi-hint">{hint}</span>}</div>;
}

export default function Dashboard() {
  const toast = useToast();
  const [preset, setPreset] = useState<Preset>('30');
  const [custom, setCustom] = useState({ from: vnDateInput(new Date(Date.now() - 29 * 86400000)), to: vnDateInput() });
  const [product, setProduct] = useState('');
  const [type, setType] = useState('');
  const products = useLoad((s) => get('/product-types?state=all&page_size=100', s), []);
  const types = useLoad((s) => get('/defect-types?state=all&page_size=100', s), []);
  const params = { ...range(preset, custom.from, custom.to), product_type_id: product, defect_type_id: type };
  const { data, loading, error, reload } = useLoad((s) => get('/dashboard' + query(params), s), [JSON.stringify(params)]);
  const k = data?.kpi;
  const f = data?.forecast;
  return <div className="page">
    <PageHeader title="Tổng quan" subtitle={data ? `Kỳ ${data.period.from.split('-').reverse().join('/')} – ${data.period.to.split('-').reverse().join('/')}` : undefined}
      actions={<><Button onClick={reload}>Làm mới</Button><Button onClick={() => navigate('/quet')}>Quét QR</Button><Button variant="primary" onClick={() => navigate('/tao')}>Tạo đề xuất</Button></>} />
    <div className="filters">
      <Chips label="Kỳ" value={preset} onChange={setPreset} options={[{ value: '7', label: '7 ngày' }, { value: '30', label: '30 ngày' }, { value: 'thang', label: 'Tháng này' }, { value: 'tuy_chon', label: 'Tùy chọn' }]} />
      {preset === 'tuy_chon' && <><TextInput label="Từ ngày" type="date" value={custom.from} onChange={(e) => setCustom({ ...custom, from: e.target.value })} />
        <TextInput label="Đến ngày" type="date" value={custom.to} onChange={(e) => setCustom({ ...custom, to: e.target.value })} /></>}
      <Select label="Sản phẩm" value={product} onChange={(e) => setProduct(e.target.value)}><option value="">Tất cả</option>{(products.data?.items || []).map((p: Row) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
      <Select label="Loại lỗi" value={type} onChange={(e) => setType(e.target.value)}><option value="">Tất cả</option>{(types.data?.items || []).map((t: Row) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select>
    </div>
    {loading && !data ? <Loading /> : error ? <ErrorBox error={error} onRetry={reload} /> : data && <>
      <div className="kpi-grid">
        <Kpi label="Quá hạn" value={String(k.overdue)} tone={k.overdue ? 'bad' : undefined} hint="đề xuất đang mở" />
        <Kpi label="Chờ giám sát" value={String(k.waiting_supervisor)} hint="chờ xác nhận lỗi" />
        <Kpi label="Lỗi ưu tiên chờ Quản lý" value={String(k.waiting_approver)} />
        <Kpi label="Tỷ lệ sản phẩm lỗi" value={k.defect_rate == null ? 'Chưa tính được' : formatPercent(k.defect_rate, 2)} hint={`${k.defective_count} lỗi / ${k.inspected_count ?? '?'} đã kiểm`} />
        <Kpi label="Số lỗi / sản phẩm lỗi" value={k.defects_per_product == null ? '—' : formatNumber(k.defects_per_product, 2)} />
        <Kpi label="Chi phí kỳ này" value={formatMoney(k.period_cost)} hint="chi phí thực tế đã nhập" />
        <Kpi label="Chi phí / sản phẩm đã kiểm" value={k.cost_per_inspected == null ? '—' : formatMoney(k.cost_per_inspected)} />
        <Kpi label="Dự báo tuần tới" value={f.available ? formatMoney(f.value) : 'Chưa đủ dữ liệu'} hint={f.available ? `95%: ${formatMoney(f.low)} – ${formatMoney(f.high)}` : `cần ≥ ${f.min_n} tuần có chi phí`} />
      </div>
      {k.warnings?.length > 0 && <Alert tone="warn" title="Lưu ý về số liệu">{k.warnings.join(' ')}</Alert>}
      <div className="grid-2">
        <Card title="Chi phí theo tuần (12 tuần) và dự báo">
          <WeeklyCostChart weeks={data.weekly} forecast={f} />
          <p className="muted">{f.available ? f.method + '. Đây là số đo thống kê, không phải cam kết.' : f.reason}</p>
        </Card>
        <Card title="Pareto chi phí theo loại lỗi">{data.pareto.length ? <ParetoChart rows={data.pareto} /> : <p className="muted">Chưa có chi phí thực tế trong kỳ.</p>}</Card>
        <Card title="Loại lỗi xu hướng tăng (4 tuần gần nhất so với 4 tuần trước)">
          {data.trending.length ? <ul className="list">{data.trending.map((t: Row) => <li key={t.defect_type_id} className="list-row"><strong>{t.name}</strong>
            <span>{t.previous} → <strong>{t.recent}</strong> sản phẩm lỗi{t.change_pct != null ? ` (+${t.change_pct}%)` : ' (mới xuất hiện)'}</span></li>)}</ul>
            : <p className="muted">Không có loại lỗi tăng đáng kể (ngưỡng: ≥ 3 sản phẩm và tăng ≥ 50%).</p>}
        </Card>
        <Card title="Tỷ lệ phương án trong kỳ"><MethodShare rows={data.methods} /></Card>
      </div>
      <Card title="Đề xuất cần xử lý" actions={<Button onClick={() => download('/dashboard/todo.xlsx' + query({ product_type_id: product, defect_type_id: type }), 'de-xuat-can-xu-ly.xlsx').catch((e) => toast(e.message, 'error'))}>Xuất Excel</Button>}>
        <div className="embedded-list"><ProposalList title="" view="all" defaultFilter="dang_mo" extraFilters={[{ value: 'cho_phuong_an', label: 'Chờ chọn phương án' }, { value: 'dang_xu_ly', label: 'Đang xử lý' }, { value: 'cho_dong', label: 'Chờ kiểm tra đóng' }]} /></div>
      </Card>
    </>}
  </div>;
}
