// Thẻ "Hệ thống đã kiểm tra trước" (luật) + gợi ý/độ tin cậy (khi tự động duyệt ở chế độ Chỉ gợi ý/Tự động).
import type { Row } from '../lib/api';
import { Badge, Card } from '../ui/components';
import { DETAIL_SECTIONS } from './Detail';

const RESULT: Row = { ok: ['ok', 'Đạt'], canh_bao: ['warn', 'Cảnh báo'], loi: ['error', 'Không đạt'], chua_ho_tro: ['neutral', 'Chưa hỗ trợ'] };
const ACTIONS: Row = { xac_nhan_loi: 'Xác nhận lỗi', tu_choi: 'Từ chối', dong_de_xuat: 'Đóng đề xuất', yeu_cau_lam_lai: 'Yêu cầu làm lại', sua: 'Sửa', tai_che: 'Tái chế', huy: 'Hủy', khac: 'Khác' };

export function PrecheckCard({ p }: { p: Row }) {
  const pre = p.precheck;
  if (!pre) return null;
  const suggestion = p.suggestion;
  return <Card title="Hệ thống đã kiểm tra trước" className="precheck">
    <ul className="check-list">{pre.checks.map((c: Row, n: number) => <li key={n}><Badge tone={RESULT[c.result][0]}>{RESULT[c.result][1]}</Badge> {c.text}</li>)}</ul>
    {suggestion ? <p className="suggestion"><strong>Gợi ý: {ACTIONS[suggestion.action] || suggestion.action}</strong> · độ tin cậy {Math.round(suggestion.confidence * 100)}% <span className="muted">({suggestion.basis})</span></p>
      : <p className="muted">Gợi ý tự động: chưa bật cho bước này. Quyết định do giám sát.</p>}
  </Card>;
}

DETAIL_SECTIONS.push((p) => ['cho_xac_nhan', 'cho_phuong_an', 'cho_dong'].includes(p.status) && p.can_review ? <PrecheckCard p={p} /> : null);
