// Bảng định tuyến: đường dẫn → màn hình, kèm kiểm tra vai trò ở giao diện (server vẫn kiểm tra lại).
import type { ReactNode } from 'react';
import type { Route } from './lib/router';
import type { Session } from './lib/session';
import { hasRole } from './lib/session';
import { HOME } from './lib/nav';
import { Empty, PageHeader } from './ui/components';
import Me from './screens/Me';
import Users from './screens/Users';
import AuditLog from './screens/AuditLog';
import ProposalList from './screens/Proposals';
import Create from './screens/Create';
import Sheet, { AfterSubmit } from './screens/Sheet';
import Evidence from './screens/Evidence';
import Detail from './screens/Detail';
import Scan from './screens/Scan';
import Notifications from './screens/Notifications';
import Search from './screens/Search';
import Dashboard from './screens/Dashboard';
import Reports from './screens/Reports';
import './screens/Review';
import './screens/TreatmentStep';
import './screens/CompleteStep';
import DefectTypes from './screens/DefectTypes';
import { ProductsScreen, SetupHub } from './screens/Catalog';

const MANAGERS = ['quan_ly', 'admin'];

function Soon({ title }: { title: string }) {
  return <div className="page"><PageHeader title={title} /><Empty title="Màn hình đang được xây dựng">Chức năng này sẽ có ở bước tiếp theo.</Empty></div>;
}

function Forbidden() {
  return <div className="page"><Empty title="Bạn không có quyền xem màn hình này">Đổi chế độ làm việc ở màn “Tôi” nếu tài khoản có nhiều vai trò.</Empty></div>;
}

type Entry = { roles?: string[]; render: (route: Route, session: Session) => ReactNode };

export const ROUTES: Record<string, Entry> = {
  'toi': { render: () => <Me /> },
  'nguoi-dung': { roles: MANAGERS, render: () => <Users /> },
  'danh-muc': { roles: MANAGERS, render: () => <DefectTypes /> },
  'san-pham': { roles: MANAGERS, render: (r) => <ProductsScreen tab={r.parts[1]} /> },
  'thiet-lap': { roles: MANAGERS, render: () => <SetupHub /> },
  'nhat-ky': { roles: MANAGERS, render: () => <AuditLog /> },
  'viec-cua-toi': { roles: ['nguoi_tao', 'quan_ly'], render: () => <ProposalList title="Việc của tôi" subtitle="Đề xuất do bạn tạo" view="mine" canCreate extraFilters={[{ value: 'nhap', label: 'Nháp' }]} /> },
  'can-duyet': { roles: ['giam_sat', 'quan_ly'], render: () => <ProposalList title="Cần duyệt" subtitle="Đề xuất của sản phẩm bạn giám sát" view="review" extraFilters={[{ value: 'cho_phuong_an', label: 'Chờ chọn phương án' }, { value: 'dang_xu_ly', label: 'Đang xử lý' }, { value: 'cho_dong', label: 'Chờ kiểm tra đóng' }]} /> },
  'cho-phe-duyet': { roles: ['cap_tren'], render: () => <ProposalList title="Chờ phê duyệt" subtitle="Đề xuất cần cấp trên duyệt (chi phí vượt ngưỡng, Hủy, hoặc lỗi ưu tiên)" view="approve" /> },
  'lich-su': { roles: ['cap_tren'], render: () => <ProposalList title="Lịch sử" subtitle="Đề xuất đã qua bước cấp trên" view="approved" extraFilters={[{ value: 'dang_xu_ly', label: 'Đang xử lý' }, { value: 'da_dong', label: 'Đã đóng' }]} /> },
  'tao': { roles: ['nguoi_tao', 'quan_ly'], render: (r) => <Create key={r.parts[1] || 'new'} editId={r.parts[1]} token={r.params.get('qr') || r.params.get('serial') || undefined} /> },
  'thong-bao': { render: () => <Notifications /> },
  'tra-cuu': { render: () => <Search /> },
  'bao-cao': { roles: ['quan_ly', 'admin', 'cap_tren'], render: () => <Reports /> },
  'tong-quan': { roles: ['quan_ly', 'admin', 'cap_tren'], render: () => <Dashboard /> },
  'quet': { render: (r) => <Scan key={r.parts[1] || ''} token={r.parts[1]} /> },
  'de-xuat': { render: (r, session) => {
    const [, id, sub] = r.parts;
    if (!id) return hasRole(session.user, ...MANAGERS) ? <ProposalList title="Đề xuất" view="all" canCreate={hasRole(session.user, 'quan_ly')}
      extraFilters={[{ value: 'cho_phuong_an', label: 'Chờ chọn phương án' }, { value: 'cho_cap_tren', label: 'Chờ cấp trên' }, { value: 'dang_xu_ly', label: 'Đang xử lý' }, { value: 'cho_dong', label: 'Chờ kiểm tra đóng' }, { value: 'da_dong', label: 'Đã đóng' }]} /> : <Forbidden />;
    if (sub === 'tong-quan') return <Sheet id={id} />;
    if (sub === 'da-gui') return <AfterSubmit id={id} />;
    if (sub === 'minh-chung') return <Evidence id={id} />;
    return <Detail key={id} id={id} />;
  } },
};

const TITLES: Record<string, string> = {
  'viec-cua-toi': 'Việc của tôi', 'quet': 'Quét QR', 'thong-bao': 'Thông báo', 'can-duyet': 'Cần duyệt', 'cho-phe-duyet': 'Chờ phê duyệt',
  'lich-su': 'Lịch sử', 'tong-quan': 'Tổng quan', 'de-xuat': 'Đề xuất', 'bao-cao': 'Báo cáo', 'thiet-lap': 'Thiết lập', 'danh-muc': 'Danh mục lỗi',
  'nhat-ky': 'Nhật ký', 'he-thong': 'Hệ thống', 'tu-dong-duyet': 'Tự động duyệt', 'san-pham': 'Sản phẩm/lô/ca', 'tra-cuu': 'Tra cứu',
};

export function routeElement(route: Route, session: Session): ReactNode {
  const key = route.parts[0] || HOME[session.activeRole].slice(1);
  const entry = ROUTES[key];
  if (!entry) return <Soon title={TITLES[key] || 'Không tìm thấy trang'} />;
  if (entry.roles && !hasRole(session.user, ...entry.roles)) return <Forbidden />;
  return entry.render(route, session);
}
