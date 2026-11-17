// Thành phần giao diện dùng chung. Vùng chạm >= 44px; trạng thái luôn có chữ, không chỉ màu.
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { LoaderCircle, X } from 'lucide-react';
import { STATUS_LABELS, STATUS_TONE } from '../lib/labels';

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost';
export function Button({ variant = 'secondary', busy, children, className = '', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return <button type="button" {...rest} disabled={rest.disabled || busy} aria-busy={busy || undefined} className={`btn btn-${variant} ${className}`}>
    {busy && <LoaderCircle className="spin" size={18} aria-hidden />}{children}
  </button>;
}

export function Field({ label, hint, error, children, required }: { label: string; hint?: ReactNode; error?: string; children: (id: string, describedBy?: string) => ReactNode; required?: boolean }) {
  const id = useId();
  const describedBy = error ? id + '-error' : hint ? id + '-hint' : undefined;
  return <div className={`field ${error ? 'has-error' : ''}`}>
    <label htmlFor={id}>{label}{required && <span className="required" aria-hidden> *</span>}</label>
    {children(id, describedBy)}
    {hint && !error && <p className="hint" id={id + '-hint'}>{hint}</p>}
    {error && <p className="error-text" id={id + '-error'} role="alert">{error}</p>}
  </div>;
}

export function TextInput({ label, hint, error, required, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: ReactNode; error?: string }) {
  return <Field label={label} hint={hint} error={error} required={required}>{(id, d) => <input id={id} aria-describedby={d} aria-invalid={!!error || undefined} required={required} {...rest} />}</Field>;
}

export function TextArea({ label, hint, error, required, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: ReactNode; error?: string }) {
  return <Field label={label} hint={hint} error={error} required={required}>{(id, d) => <textarea id={id} aria-describedby={d} aria-invalid={!!error || undefined} required={required} rows={3} {...rest} />}</Field>;
}

export function Select({ label, hint, error, required, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; hint?: ReactNode; error?: string }) {
  return <Field label={label} hint={hint} error={error} required={required}>{(id, d) => <select id={id} aria-describedby={d} required={required} {...rest}>{children}</select>}</Field>;
}

export function Checkbox({ label, hint, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode; hint?: ReactNode }) {
  return <label className="check"><input type="checkbox" {...rest} /><span>{label}{hint && <small className="hint">{hint}</small>}</span></label>;
}

export function Badge({ tone = 'neutral', children, icon }: { tone?: string; children: ReactNode; icon?: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{icon}{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] || 'neutral'}>{STATUS_LABELS[status] || status}</Badge>;
}

export function Card({ title, actions, children, className = '' }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>
    {(title || actions) && <header className="card-head">{title && <h2>{title}</h2>}{actions && <div className="card-actions">{actions}</div>}</header>}
    {children}
  </section>;
}

export function PageHeader({ title, subtitle, actions, onBack }: { title: string; subtitle?: ReactNode; actions?: ReactNode; onBack?: () => void }) {
  return <div className="page-head">
    {onBack && <button type="button" className="icon-btn" onClick={onBack} aria-label="Quay lại">‹</button>}
    <div className="page-title"><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
    {actions && <div className="page-actions">{actions}</div>}
  </div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><strong>{title}</strong>{children && <p>{children}</p>}</div>;
}

export function Loading({ text = 'Đang tải…' }: { text?: string }) {
  return <div className="loading" role="status"><LoaderCircle className="spin" size={22} aria-hidden /> {text}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return <div className="alert alert-error" role="alert"><span>{error}</span>{onRetry && <Button onClick={onRetry}>Thử lại</Button>}</div>;
}

export function Alert({ tone = 'info', title, children }: { tone?: 'info' | 'warn' | 'error' | 'ok' | 'priority'; title?: string; children?: ReactNode }) {
  return <div className={`alert alert-${tone}`} role={tone === 'error' || tone === 'priority' ? 'alert' : 'status'}>
    <div>{title && <strong>{title}</strong>}{children && <div>{children}</div>}</div>
  </div>;
}

export function Modal({ title, onClose, children, footer, wide }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('input,select,textarea,button')?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [onClose]);
  return <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
      <header className="modal-head"><h2>{title}</h2><button type="button" className="icon-btn" onClick={onClose} aria-label="Đóng"><X size={20} /></button></header>
      <div className="modal-body">{children}</div>
      {footer && <footer className="modal-foot">{footer}</footer>}
    </div>
  </div>;
}

/** Hộp xác nhận có thể bắt buộc lý do. */
export function ConfirmDialog({ title, message, confirmLabel, danger, requireReason, reasonLabel = 'Lý do', onConfirm, onClose }: {
  title: string; message?: ReactNode; confirmLabel: string; danger?: boolean; requireReason?: boolean; reasonLabel?: string;
  onConfirm: (reason: string) => Promise<void> | void; onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async () => {
    if (requireReason && reason.trim().length < 3) { setError('Vui lòng nhập lý do (ít nhất 3 ký tự)'); return; }
    setBusy(true); setError('');
    try { await onConfirm(reason.trim()); onClose(); } catch (e) { setError(e instanceof Error ? e.message : 'Có lỗi xảy ra'); } finally { setBusy(false); }
  };
  return <Modal title={title} onClose={onClose} footer={<>
    <Button onClick={onClose}>Hủy bỏ</Button>
    <Button variant={danger ? 'danger' : 'primary'} busy={busy} onClick={submit}>{confirmLabel}</Button>
  </>}>
    {message && <div className="stack">{message}</div>}
    {requireReason && <TextArea label={reasonLabel} required value={reason} onChange={(e) => setReason(e.target.value)} />}
    {error && <p className="error-text" role="alert">{error}</p>}
  </Modal>;
}

/** Nhóm chip lọc (nút bật/tắt). */
export function Chips<T extends string>({ options, value, onChange, label }: { options: { value: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void; label: string }) {
  return <div className="chips" role="group" aria-label={label}>
    {options.map((o) => <button type="button" key={o.value} className={`chip ${value === o.value ? 'active' : ''}`} aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
      {o.label}{o.count !== undefined && <span className="chip-count">{o.count}</span>}
    </button>)}
  </div>;
}

/** Nhóm lựa chọn dạng nút lớn (radio). */
export function Segmented<T extends string>({ options, value, onChange, label, required, error }: { options: { value: T; label: string; disabled?: boolean }[]; value: T | ''; onChange: (v: T) => void; label: string; required?: boolean; error?: string }) {
  return <fieldset className={`segmented ${error ? 'has-error' : ''}`}>
    <legend>{label}{required && <span className="required" aria-hidden> *</span>}</legend>
    <div className="segmented-row">
      {options.map((o) => <label key={o.value} className={`seg ${value === o.value ? 'active' : ''} ${o.disabled ? 'disabled' : ''}`}>
        <input type="radio" checked={value === o.value} disabled={o.disabled} onChange={() => onChange(o.value)} />
        <span>{o.label}</span>
      </label>)}
    </div>
    {error && <p className="error-text" role="alert">{error}</p>}
  </fieldset>;
}

export function Stepper({ value, onChange, min = 1, max = 999, label }: { value: number; onChange: (v: number) => void; min?: number; max?: number; label: string }) {
  return <div className="field"><span className="field-label">{label}</span>
    <div className="stepper">
      <button type="button" aria-label="Giảm" onClick={() => onChange(Math.max(min, value - 1))} disabled={value <= min}>−</button>
      <input type="number" inputMode="numeric" aria-label={label} value={value} min={min} max={max} onChange={(e) => { const n = parseInt(e.target.value, 10); if (!Number.isNaN(n)) onChange(Math.min(max, Math.max(min, n))); }} />
      <button type="button" aria-label="Tăng" onClick={() => onChange(Math.min(max, value + 1))} disabled={value >= max}>+</button>
    </div></div>;
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return <nav className="pager" aria-label="Phân trang">
    <Button disabled={page <= 1} onClick={() => onPage(page - 1)}>Trang trước</Button>
    <span>Trang {page}/{pages} · {total} mục</span>
    <Button disabled={page >= pages} onClick={() => onPage(page + 1)}>Trang sau</Button>
  </nav>;
}

// ---------- Thông báo nổi (toast) ----------
type Toast = { id: number; text: string; tone: 'ok' | 'error' | 'info' };
const ToastContext = createContext<(text: string, tone?: Toast['tone']) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast['tone'] = 'ok') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 8000 : 4000);
  }, []);
  return <ToastContext.Provider value={push}>{children}
    <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.tone === 'error' ? 'Lỗi: ' : ''}{t.text}</div>)}</div>
  </ToastContext.Provider>;
}
export const useToast = () => useContext(ToastContext);

// ---------- Tải dữ liệu ----------
export function useLoad<T = any>(loader: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: '', loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: '' }));
    loader(controller.signal).then((data) => { if (!controller.signal.aborted) setState({ data, error: '', loading: false }); })
      .catch((e) => { if (!controller.signal.aborted) setState((s) => ({ ...s, error: e instanceof Error ? e.message : 'Lỗi tải dữ liệu', loading: false })); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}
