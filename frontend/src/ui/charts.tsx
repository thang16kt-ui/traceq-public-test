// Biểu đồ SVG gọn, không thư viện: một trục, nét mảnh, đầu cột bo 4px, tooltip khi rê/chạm, luôn có bảng số liệu.
import { useState } from 'react';
import { formatMoney } from '../lib/format';

export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100'];
const short = (v: number) => v >= 1e9 ? (v / 1e9).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tỷ' : v >= 1e6 ? (v / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tr' : v >= 1e3 ? Math.round(v / 1e3) + 'k' : String(Math.round(v));

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((x) => x >= v) || v;
}

/** Chi phí theo tuần (cột) + cột dự báo nét đứt kèm khoảng sai số. */
export function WeeklyCostChart({ weeks, forecast }: { weeks: { week_start: string; cost: number }[]; forecast: any }) {
  const [hover, setHover] = useState<number | null>(null);
  const bars = [...weeks.map((w) => ({ label: w.week_start.slice(5).split('-').reverse().join('/'), value: w.cost, kind: 'actual' as const, full: w.week_start })),
    ...(forecast?.available ? [{ label: 'Tuần tới', value: forecast.value, kind: 'forecast' as const, full: 'Dự báo' }] : [])];
  const W = 640, H = 240, L = 48, B = 30, T = 12;
  const max = niceMax(Math.max(1, ...bars.map((b) => b.value), forecast?.available ? forecast.high : 0));
  const step = (W - L - 8) / bars.length;
  const bw = Math.max(6, Math.min(34, step - 6));
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return <figure className="chart">
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Chi phí thực tế theo tuần" onMouseLeave={() => setHover(null)}>
      {[0, 0.5, 1].map((f) => <g key={f}><line x1={L} x2={W - 4} y1={y(max * f)} y2={y(max * f)} className="grid" /><text x={L - 6} y={y(max * f) + 4} className="axis" textAnchor="end">{short(max * f)}</text></g>)}
      {bars.map((b, i) => {
        const x = L + i * step + (step - bw) / 2;
        const h = Math.max(b.value > 0 ? 2 : 0, H - B - y(b.value));
        const d = `M${x},${H - B} v${-Math.max(0, h - 4)} q0,-4 4,-4 h${bw - 8} q4,0 4,4 v${Math.max(0, h - 4)} z`;
        return <g key={i} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0} aria-label={`${b.full}: ${formatMoney(b.value)}`}>
          <rect x={L + i * step} y={T} width={step} height={H - T - B} fill="transparent" />
          {b.kind === 'actual' ? <path d={d} fill={SERIES[0]} opacity={hover === null || hover === i ? 1 : 0.55} />
            : <g><path d={d} fill="none" stroke={SERIES[0]} strokeWidth={2} strokeDasharray="5 4" />
              <line x1={x + bw / 2} x2={x + bw / 2} y1={y(forecast.low)} y2={y(forecast.high)} stroke="var(--ink-2)" strokeWidth={2} />
              <line x1={x + bw / 2 - 6} x2={x + bw / 2 + 6} y1={y(forecast.low)} y2={y(forecast.low)} stroke="var(--ink-2)" strokeWidth={2} />
              <line x1={x + bw / 2 - 6} x2={x + bw / 2 + 6} y1={y(forecast.high)} y2={y(forecast.high)} stroke="var(--ink-2)" strokeWidth={2} /></g>}
          {(i % 2 === 0 || b.kind === 'forecast') && <text x={x + bw / 2} y={H - 10} className="axis" textAnchor="middle">{b.label}</text>}
        </g>;
      })}
      <line x1={L} x2={W - 4} y1={H - B} y2={H - B} className="baseline" />
    </svg>
    {hover !== null && <div className="tooltip" role="status">{bars[hover].kind === 'forecast'
      ? <>Dự báo tuần tới: <strong>{formatMoney(forecast.value)}</strong><br />Khoảng 95%: {formatMoney(forecast.low)} – {formatMoney(forecast.high)}</>
      : <>Tuần từ {bars[hover].full.split('-').reverse().join('/')}: <strong>{formatMoney(bars[hover].value)}</strong></>}</div>}
    <figcaption className="legend"><span><i className="swatch" style={{ background: SERIES[0] }} />Chi phí thực tế</span>{forecast?.available && <span><i className="swatch dashed" />Dự báo (nét đứt, kèm khoảng sai số 95%)</span>}</figcaption>
    <details className="table-view"><summary>Xem bảng số liệu</summary><table className="table"><thead><tr><th>Tuần</th><th className="num">Chi phí</th></tr></thead>
      <tbody>{bars.map((b, i) => <tr key={i}><td>{b.full}</td><td className="num">{formatMoney(b.value)}{b.kind === 'forecast' ? ` (${formatMoney(forecast.low)} – ${formatMoney(forecast.high)})` : ''}</td></tr>)}</tbody></table></details>
  </figure>;
}

/** Pareto chi phí theo loại lỗi: cột ngang sắp giảm dần, cột % lũy kế là chữ (không dùng trục thứ hai). */
export function ParetoChart({ rows }: { rows: { name: string; cost: number; cumulative_pct: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.cost));
  return <figure className="chart pareto" aria-label="Pareto chi phí theo loại lỗi">
    <table className="pareto-table"><thead><tr><th>Loại lỗi</th><th>Chi phí</th><th className="num">Lũy kế</th></tr></thead>
      <tbody>{rows.map((r) => <tr key={r.name} className={r.cumulative_pct <= 80 ? 'vital' : ''}>
        <td>{r.name}</td>
        <td><div className="hbar"><span style={{ width: `${(r.cost / max) * 100}%`, background: SERIES[0] }} /></div><span className="hbar-value">{formatMoney(r.cost)}</span></td>
        <td className="num">{r.cumulative_pct.toLocaleString('vi-VN')}%</td></tr>)}</tbody></table>
    <figcaption className="muted">Dòng in đậm: nhóm loại lỗi chiếm ~80% chi phí.</figcaption>
  </figure>;
}

/** Tỷ lệ phương án: một thanh xếp chồng, có nhãn chữ và chú giải. */
export function MethodShare({ rows }: { rows: { method: string; label: string; count: number; pct: number }[] }) {
  const total = rows.reduce((a, r) => a + r.count, 0);
  if (!total) return <p className="muted">Chưa có phương án nào được chốt trong kỳ.</p>;
  return <figure className="chart">
    <div className="stack-bar" role="img" aria-label={rows.map((r) => `${r.label} ${r.pct}%`).join(', ')}>
      {rows.filter((r) => r.count).map((r) => <span key={r.method} title={`${r.label}: ${r.count} (${r.pct}%)`} style={{ width: `${r.pct}%`, background: SERIES[['sua', 'tai_che', 'huy', 'khac'].indexOf(r.method)] }} />)}
    </div>
    <figcaption className="legend">{rows.map((r, i) => <span key={r.method}><i className="swatch" style={{ background: SERIES[i] }} />{r.label}: <strong>{r.count}</strong> ({r.pct.toLocaleString('vi-VN')}%)</span>)}</figcaption>
  </figure>;
}
