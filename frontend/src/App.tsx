// Khung ứng dụng: đăng nhập, điều hướng theo vai trò, banner máy chủ đang khởi động.
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Bell, User as UserIcon } from 'lucide-react';
import { get, onServerState, onUnauthorized, post, setCSRF } from './lib/api';
import type { Row, ServerState } from './lib/api';
import { ROLE_LABELS } from './lib/labels';
import { BOTTOM_NAV, HOME, SIDEBAR } from './lib/nav';
import { navigate, useRoute } from './lib/router';
import { defaultRole, safeStorage, SessionContext } from './lib/session';
import type { Session } from './lib/session';
import { Card, Loading, ToastProvider } from './ui/components';
import { routeElement } from './routes';
import { clearOffline, startBackgroundSync } from './lib/offline';
import Login from './screens/Login';
import { ChangePassword } from './screens/Me';

function ServerBanner() {
  const [state, setState] = useState<ServerState>('ok');
  useEffect(() => onServerState(setState), []);
  if (state === 'ok') return null;
  return <div className={`server-banner ${state}`} role="status">
    {state === 'offline' ? 'Mất kết nối mạng. Dữ liệu đang nhập vẫn được giữ trên máy.' : 'Máy chủ đang khởi động, tự thử lại… Dữ liệu đang nhập không bị mất.'}
  </div>;
}

function Shell({ session, children, path, unread }: { session: Session; children: ReactNode; path: string; unread: number }) {
  const { activeRole, user } = session;
  const bottom = BOTTOM_NAV[activeRole] || [];
  const side = SIDEBAR[activeRole];
  const isActive = (p: string) => path === p || path.startsWith(p + '/');
  return <div className={`shell ${side ? 'has-sidebar' : ''}`}>
    {side && <aside className="sidebar" aria-label="Điều hướng chính">
      <a className="side-brand" href={'#' + HOME[activeRole]}><span className="logo" aria-hidden>TQ</span> TraceQ</a>
      <nav>{side.map((item) => <a key={item.path} href={'#' + item.path} className={`side-item ${isActive(item.path) ? 'active' : ''}`} aria-current={isActive(item.path) ? 'page' : undefined}><item.icon size={20} aria-hidden />{item.label}</a>)}</nav>
      <div className="side-foot">
        <a href="#/thong-bao" className={`side-item ${isActive('/thong-bao') ? 'active' : ''}`}><Bell size={20} aria-hidden />Thông báo{unread > 0 && <span className="count">{unread}</span>}</a>
        <a href="#/toi" className={`side-item ${isActive('/toi') ? 'active' : ''}`}><UserIcon size={20} aria-hidden />{user.display_name}<small>{ROLE_LABELS[activeRole]}</small></a>
      </div>
    </aside>}
    <header className="topbar">
      <a className="top-brand" href={'#' + HOME[activeRole]}><span className="logo" aria-hidden>TQ</span><span>TraceQ</span></a>
      <span className="top-role">{ROLE_LABELS[activeRole]}</span>
      <a href="#/thong-bao" className="icon-btn" aria-label={`Thông báo${unread ? `, ${unread} chưa đọc` : ''}`}><Bell size={22} />{unread > 0 && <span className="dot">{unread > 99 ? '99+' : unread}</span>}</a>
      <a href="#/toi" className="icon-btn" aria-label="Tôi"><UserIcon size={22} /></a>
    </header>
    <ServerBanner />
    <main className="content" id="main">{children}</main>
    <nav className="bottom-nav" aria-label="Điều hướng">
      {bottom.map((item) => <a key={item.path} href={'#' + item.path} className={isActive(item.path) ? 'active' : ''} aria-current={isActive(item.path) ? 'page' : undefined}>
        <item.icon size={22} aria-hidden /><span>{item.label}</span>
        {item.path === '/thong-bao' && unread > 0 && <span className="dot">{unread > 99 ? '99+' : unread}</span>}
      </a>)}
    </nav>
  </div>;
}

export default function App() {
  const route = useRoute();
  const [state, setState] = useState<{ loading: boolean; user: Row | null; environment: string }>({ loading: true, user: null, environment: '' });
  const [activeRole, setRole] = useState('');
  const [unread, setUnread] = useState(0);

  const accept = useCallback((data: Row) => {
    setCSRF(data.csrf_token);
    setState({ loading: false, user: data.user, environment: data.environment });
    setRole(defaultRole(data.user));
  }, []);

  const refreshUser = useCallback(async () => { accept(await get('/auth/me')); }, [accept]);

  useEffect(() => {
    get('/auth/me').then(accept).catch(() => {
      get('/auth/config').then((c) => setState({ loading: false, user: null, environment: c.environment })).catch(() => setState({ loading: false, user: null, environment: '' }));
    });
    onUnauthorized(() => setState((s) => ({ ...s, user: null })));
  }, [accept]);

  useEffect(() => { if (state.user) return startBackgroundSync(); }, [state.user]);

  useEffect(() => {
    if (!state.user || state.user.must_change_password) return;
    let alive = true;
    const load = () => get('/notifications/unread-count').then((d) => { if (alive) setUnread(d.count); }).catch(() => {});
    load();
    const timer = setInterval(load, 60000);
    window.addEventListener('traceq:notifications', load);
    return () => { alive = false; clearInterval(timer); window.removeEventListener('traceq:notifications', load); };
  }, [state.user]);

  const session: Session | null = useMemo(() => state.user ? {
    user: state.user, environment: state.environment, activeRole,
    setActiveRole: (role: string) => { safeStorage.set('traceq.activeRole.' + state.user!.id, role); setRole(role); navigate(HOME[role]); },
    logout: async () => {
      try { await post('/auth/logout'); } catch { /* vẫn xóa dữ liệu trên máy */ }
      await clearOffline();
      safeStorage.clearPrefix('traceq.draft.');
      window.dispatchEvent(new Event('traceq:logout'));
      setState((s) => ({ ...s, user: null })); navigate('/', true);
    },
    refreshUser,
  } : null, [state.user, state.environment, activeRole, refreshUser]);

  if (state.loading) return <Loading text="Đang mở TraceQ…" />;
  if (!session) return <ToastProvider><ServerBanner /><Login environment={state.environment} onLogin={(data) => { accept(data); navigate(HOME[defaultRole(data.user)], true); }} /></ToastProvider>;
  if (session.user.must_change_password) return <ToastProvider><SessionContext.Provider value={session}>
    <main className="login"><Card title="Đổi mật khẩu" className="login-card"><ChangePassword forced onDone={refreshUser} /></Card></main>
  </SessionContext.Provider></ToastProvider>;

  const path = route.path === '/' ? HOME[activeRole] : route.path;
  return <ToastProvider><SessionContext.Provider value={session}>
    <Shell session={session} path={path} unread={unread}>{routeElement(route, session)}</Shell>
  </SessionContext.Provider></ToastProvider>;
}
