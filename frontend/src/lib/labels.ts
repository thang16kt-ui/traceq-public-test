// Nhãn tiếng Việt cố định trên giao diện (khớp mã ở server).
export const ROLE_LABELS: Record<string, string> = {
  nguoi_tao: 'Người tạo', giam_sat: 'Giám sát', cap_tren: 'Cấp trên', quan_ly: 'Quản lý', admin: 'Admin',
};
export const ROLE_ORDER = ['quan_ly', 'admin', 'giam_sat', 'cap_tren', 'nguoi_tao'];

export const STATUS_LABELS: Record<string, string> = {
  nhap: 'Nháp', cho_minh_chung: 'Chờ minh chứng', cho_xac_nhan: 'Chờ xác nhận', cho_phuong_an: 'Chờ chọn phương án',
  cho_cap_tren: 'Chờ cấp trên', dang_xu_ly: 'Đang xử lý', cho_dong: 'Chờ kiểm tra đóng', da_dong: 'Đã đóng', da_huy: 'Đã hủy',
};
export const STATUS_TONE: Record<string, string> = {
  nhap: 'neutral', cho_minh_chung: 'warn', cho_xac_nhan: 'info', cho_phuong_an: 'info', cho_cap_tren: 'info',
  dang_xu_ly: 'progress', cho_dong: 'info', da_dong: 'ok', da_huy: 'neutral',
};

export const LEVELS = ['nhe', 'trung_binh', 'nang'] as const;
export const LEVEL_LABELS: Record<string, string> = { nhe: 'Nhẹ', trung_binh: 'Trung bình', nang: 'Nặng' };

export const METHODS = ['sua', 'tai_che', 'huy', 'khac'] as const;
export const METHOD_LABELS: Record<string, string> = { sua: 'Sửa', tai_che: 'Tái chế', huy: 'Hủy', khac: 'Khác' };

export const COST_SOURCE_LABELS: Record<string, string> = {
  thuc_te: 'Dữ liệu thực tế', gia_thi_truong: 'Giá thị trường', hon_hop: 'Kết hợp thực tế + giá thị trường',
  gia_von: 'Giá vốn sản phẩm', gia_von_tru_thu_hoi: 'Giá vốn − giá trị thu hồi', chua_co: 'Chưa có dữ liệu giá',
};
export const COST_MODE_LABELS: Record<string, string> = { auto: 'Tự động', market: 'Chỉ giá thị trường', actual: 'Chỉ dữ liệu thực tế' };

export const ROOT_CAUSES = ['Con người', 'Máy móc', 'Nguyên vật liệu', 'Phương pháp', 'Đo lường', 'Môi trường', 'Chưa rõ'];

export const NOTIFY_LABELS: Record<string, string> = {
  uu_tien: 'Lỗi ưu tiên (luôn bật)', can_duyet: 'Có đề xuất cần tôi duyệt', qua_han: 'Đề xuất quá hạn', bi_tu_choi: 'Đề xuất bị từ chối',
  nhac_cuoi_ngay: 'Nhắc cuối ngày', nhac_chi_phi: 'Nhắc nhập chi phí thực tế', loi_lap_lai: 'Cảnh báo lỗi lặp lại',
};
