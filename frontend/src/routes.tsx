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
import AutoApproval from './screens/AutoApproval';
import System from './screens/System';
import './screens/Review';
import './screens/TreatmentStep';
import './screens/CompleteStep';
import DefectTypes from './screens/DefectTypes';
import { ProductsScreen, SetupHub } from './screens/Catalog';

const MANAGERS = ['quan_ly', 'admin'];

function NotFound() {
  return <div className="page"><PageHeader title="Không tìm thấy trang" /><Empty title="Đường dẫn không tồn tại">Dùng thanh điều hướng để chọn màn hình.</Empty></div>;
}

function Forbidden() {
  return <div className="page"><Empty title="Vai trò hiện tại không dùng được màn hình này">
    Tạo đề xuất cần vai trò Người tạo hoặc Quản lý; duyệt lỗi thường cần Giám sát, lỗi ưu tiên cần Quản lý. Nếu tài khoản có nhiều vai trò, đổi “Chế độ làm việc” ở thanh trên.
    Nếu chưa có vai trò cần thiết, nhờ Admin thêm ở màn Người dùng.</Empty></div>;
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
  'can-duyet': { roles: ['giam_sat', 'quan_ly'], render: () => <ProposalList title="Cần duyệt" subtitle="Lỗi thường hệ thống chưa tự duyệt được (Hủy, vượt ngưỡng, độ tin cậy thấp…) và đề xuất đang xử lý. Lỗi ưu tiên do Quản lý duyệt." view="review" extraFilters={[{ value: 'cho_phuong_an', label: 'Chờ chọn phương án' }, { value: 'dang_xu_ly', label: 'Đang xử lý' }, { value: 'cho_dong', label: 'Chờ kiểm tra đóng' }]} /> },
  'duyet-uu-tien': { roles: ['quan_ly'], render: () => <ProposalList title="Duyệt lỗi ưu tiên" subtitle="Một cấp duyệt: lỗi ưu tiên do Quản lý xác nhận, chốt phương án và đóng. Lỗi thường hệ thống tự duyệt khi đủ ảnh." view="manager" extraFilters={[{ value: 'cho_phuong_an', label: 'Chờ chọn phương án' }, { value: 'cho_dong', label: 'Chờ kiểm tra đóng' }]} /> },
  'tao': { roles: ['nguoi_tao', 'quan_ly'], render: (r) => <Create key={r.parts[1] || 'new'} editId={r.parts[1]} token={r.params.get('qr') || r.params.get('serial') || undefined} /> },
  'thong-bao': { render: () => <Notifications /> },
  'tra-cuu': { render: () => <Search /> },
  'he-thong': { roles: MANAGERS, render: () => <System /> },
  'tu-dong-duyet': { roles: ['quan_ly', 'admin', 'cap_tren'], render: () => <AutoApproval /> },
  'bao-cao': { roles: ['quan_ly', 'admin', 'cap_tren'], render: () => <Reports /> },
  'tong-quan': { roles: ['quan_ly', 'admin', 'cap_tren'], render: () => <Dashboard /> },
  'quet': { render: (r) => <Scan key={r.parts[1] || ''} token={r.parts[1]} /> },
  'de-xuat': { render: (r, session) => {
    const [, id, sub] = r.parts;
    if (!id) return hasRole(session.user, ...MANAGERS) ? <ProposalList title="Đề xuất" view="all" canCreate={hasRole(session.user, 'quan_ly')}
      extraFilters={[{ value: 'cho_phuong_an', label: 'Chờ chọn phương án' }, { value: 'dang_xu_ly', label: 'Đang xử lý' }, { value: 'cho_dong', label: 'Chờ kiểm tra đóng' }, { value: 'da_dong', label: 'Đã đóng' }]} /> : <Forbidden />;
    if (sub === 'tong-quan') return <Sheet id={id} />;
    if (sub === 'da-gui') return <AfterSubmit id={id} />;
    if (sub === 'minh-chung') return <Evidence id={id} />;
    return <Detail key={id} id={id} />;
  } },
};



export function routeElement(route: Route, session: Session): ReactNode {
  const key = route.parts[0] || HOME[session.activeRole].slice(1);
  const entry = ROUTES[key];
  if (!entry) return <NotFound />;
  if (entry.roles && !hasRole(session.user, ...entry.roles)) return <Forbidden />;
  return entry.render(route, session);
}
