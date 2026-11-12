// Điều hướng theo vai trò (đặc tả mục 4).
import { Bell, BookOpen, Bot, ClipboardCheck, ClipboardList, FileBarChart, History, LayoutDashboard, ListChecks, Package, QrCode, ScrollText, Server, Settings2, Tags, User, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface NavItem { path: string; label: string; icon: LucideIcon }

export const BOTTOM_NAV: Record<string, NavItem[]> = {
  nguoi_tao: [
    { path: '/viec-cua-toi', label: 'Việc của tôi', icon: ClipboardList },
    { path: '/quet', label: 'Quét QR', icon: QrCode },
    { path: '/thong-bao', label: 'Thông báo', icon: Bell },
    { path: '/toi', label: 'Tôi', icon: User },
  ],
  giam_sat: [
    { path: '/can-duyet', label: 'Cần duyệt', icon: ClipboardCheck },
    { path: '/quet', label: 'Quét QR', icon: QrCode },
    { path: '/thong-bao', label: 'Thông báo', icon: Bell },
    { path: '/toi', label: 'Tôi', icon: User },
  ],
  cap_tren: [
    { path: '/cho-phe-duyet', label: 'Chờ phê duyệt', icon: ListChecks },
    { path: '/lich-su', label: 'Lịch sử', icon: History },
    { path: '/thong-bao', label: 'Thông báo', icon: Bell },
    { path: '/toi', label: 'Tôi', icon: User },
  ],
  quan_ly: [
    { path: '/tong-quan', label: 'Tổng quan', icon: LayoutDashboard },
    { path: '/de-xuat', label: 'Đề xuất', icon: ClipboardList },
    { path: '/bao-cao', label: 'Báo cáo', icon: FileBarChart },
    { path: '/thiet-lap', label: 'Thiết lập', icon: Settings2 },
  ],
  admin: [
    { path: '/nguoi-dung', label: 'Người dùng', icon: Users },
    { path: '/danh-muc', label: 'Danh mục', icon: Tags },
    { path: '/nhat-ky', label: 'Nhật ký', icon: ScrollText },
    { path: '/he-thong', label: 'Hệ thống', icon: Server },
  ],
};

// Thanh bên trái trên máy tính cho Quản lý/Admin.
export const SIDEBAR: Record<string, NavItem[]> = {
  quan_ly: [
    { path: '/tong-quan', label: 'Tổng quan', icon: LayoutDashboard },
    { path: '/de-xuat', label: 'Đề xuất', icon: ClipboardList },
    { path: '/bao-cao', label: 'Báo cáo', icon: FileBarChart },
    { path: '/tu-dong-duyet', label: 'Tự động duyệt', icon: Bot },
    { path: '/danh-muc', label: 'Danh mục lỗi', icon: Tags },
    { path: '/san-pham', label: 'Sản phẩm/lô/ca', icon: Package },
    { path: '/nguoi-dung', label: 'Người dùng', icon: Users },
    { path: '/nhat-ky', label: 'Nhật ký', icon: ScrollText },
  ],
  admin: [
    { path: '/nguoi-dung', label: 'Người dùng', icon: Users },
    { path: '/danh-muc', label: 'Danh mục lỗi', icon: Tags },
    { path: '/san-pham', label: 'Sản phẩm/lô/ca', icon: Package },
    { path: '/nhat-ky', label: 'Nhật ký', icon: ScrollText },
    { path: '/he-thong', label: 'Hệ thống', icon: Server },
  ],
};

export const HOME: Record<string, string> = {
  nguoi_tao: '/viec-cua-toi', giam_sat: '/can-duyet', cap_tren: '/cho-phe-duyet', quan_ly: '/tong-quan', admin: '/nguoi-dung',
};

export const EXTRA_LINKS: NavItem[] = [
  { path: '/tra-cuu', label: 'Tra cứu', icon: BookOpen },
];
