// Thời gian lưu UTC, hiển thị giờ Việt Nam.
const TZ = 'Asia/Ho_Chi_Minh';

export function formatTime(value: any): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString('vi-VN', { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function formatDate(value: any): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString('vi-VN', { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatMoney(value: any): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString('vi-VN', { maximumFractionDigits: 0 }) + ' ₫';
}

export function formatNumber(value: any, digits = 1): string {
  if (value === null || value === undefined || value === '') return '—';
  return Number(value).toLocaleString('vi-VN', { maximumFractionDigits: digits });
}

export function formatPercent(value: any, digits = 1): string {
  if (value === null || value === undefined) return '—';
  return Number(value).toLocaleString('vi-VN', { maximumFractionDigits: digits }) + '%';
}

/** Chuỗi ngày theo giờ VN (YYYY-MM-DD) cho ô input type=date. */
export function vnDateInput(d = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  return parts;
}

/** Đầu ngày theo giờ Việt Nam (UTC+7, không có giờ mùa hè) dạng ISO có múi giờ. */
export function vnStartOfDay(date: string): string { return `${date}T00:00:00+07:00`; }

export function relativeDeadline(value: any): string {
  if (!value) return '';
  const diff = new Date(value).getTime() - Date.now();
  const hours = Math.round(Math.abs(diff) / 36e5);
  const text = hours >= 48 ? `${Math.round(hours / 24)} ngày` : `${hours} giờ`;
  return diff < 0 ? `quá hạn ${text}` : `còn ${text}`;
}
