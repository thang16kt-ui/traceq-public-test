// Router nhẹ theo hash (#/duong-dan?x=1). Đường dẫn QR /q/<mã> được chuyển thành #/quet/<mã>.
import { useEffect, useState } from 'react';

export interface Route { path: string; parts: string[]; params: URLSearchParams }

function parse(): Route {
  if (location.pathname.startsWith('/q/')) {
    const token = decodeURIComponent(location.pathname.slice(3));
    history.replaceState(null, '', '/#/quet/' + encodeURIComponent(token));
  }
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, search = ''] = raw.split('?');
  return { path, parts: path.split('/').filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(search) };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const update = () => { setRoute(parse()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return route;
}

export function navigate(path: string, replace = false) {
  const target = '#' + path;
  if (!replace && location.hash !== target) { location.hash = path; return; } // trình duyệt tự phát hashchange
  if (replace) history.replaceState(null, '', target);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

export function back(fallback: string) {
  if (history.length > 1) history.back(); else navigate(fallback);
}
