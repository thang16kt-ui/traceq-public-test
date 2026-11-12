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
