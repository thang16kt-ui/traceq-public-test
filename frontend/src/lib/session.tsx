import { createContext, useContext } from 'react';
import type { Row } from './api';
import { ROLE_ORDER } from './labels';

export interface Session {
  user: Row;
  environment: string;
  activeRole: string;
  setActiveRole: (role: string) => void;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export const SessionContext = createContext<Session | null>(null);
export function useSession(): Session {
  const value = useContext(SessionContext);
  if (!value) throw new Error('Chưa đăng nhập');
  return value;
}

export function hasRole(user: Row | null | undefined, ...roles: string[]) {
  return !!user && roles.some((r) => (user.roles || []).includes(r));
}

export function defaultRole(user: Row): string {
  const saved = safeStorage.get('traceq.activeRole.' + user.id);
  if (saved && user.roles.includes(saved)) return saved;
  return ROLE_ORDER.find((r) => user.roles.includes(r)) || user.roles[0];
}

// localStorage có thể bị chặn (chế độ riêng tư): luôn bọc try/catch.
export const safeStorage = {
  get(key: string) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* bỏ qua */ } },
  remove(key: string) { try { localStorage.removeItem(key); } catch { /* bỏ qua */ } },
  clearPrefix(prefix: string) {
    try { Object.keys(localStorage).filter((k) => k.startsWith(prefix)).forEach((k) => localStorage.removeItem(k)); } catch { /* bỏ qua */ }
  },
};
