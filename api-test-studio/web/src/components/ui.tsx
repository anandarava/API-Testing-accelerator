import { createContext, useCallback, useContext, useEffect, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert, CircleCheck, Copy, Check, LoaderCircle, X } from 'lucide-react';
import { initials } from '../lib/format';

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(' ');
}

// --- Buttons -----------------------------------------------------------------

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
const variants: Record<Variant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 shadow-sm',
  secondary: 'bg-surface text-ink-soft border border-line-strong hover:bg-canvas shadow-sm',
  ghost: 'text-ink-soft hover:bg-canvas',
  danger: 'bg-red-600 text-white hover:bg-red-700 shadow-sm',
};

export function Button({ variant = 'primary', size = 'md', loading, icon, children, className, disabled, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...props}
      disabled={disabled || loading}
      className={cx('inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors cursor-pointer',
        'disabled:cursor-not-allowed disabled:opacity-50', size === 'sm' ? 'h-8 px-3 text-sm' : 'h-10 px-4 text-sm',
        variants[variant], className)}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// --- Form fields ----------------------------------------------------------------

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink-soft">{label}</span>
      {children}
      {error ? <span className="mt-1.5 block text-sm text-red-600">{error}</span> : hint && <span className="mt-1.5 block text-sm text-muted">{hint}</span>}
    </label>
  );
}

const fieldClass = 'w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-faint shadow-sm transition-colors focus:border-brand-500 focus:outline-none focus:ring-3 focus:ring-brand-100 disabled:bg-canvas';

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(fieldClass, 'h-10', className)} />;
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(fieldClass, 'py-2 leading-relaxed', className)} />;
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldClass, 'h-10 pr-8', className)}>{children}</select>;
}

// --- Surfaces -------------------------------------------------------------------

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(16,24,40,.04)]', className)}>{children}</div>;
}

export function CardHeader({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div>
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon: ReactNode; title: string; description: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 flex size-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600">{icon}</div>
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-muted">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
      <LoaderCircle className="size-5 animate-spin" /> {label ?? 'Loading…'}
    </div>
  );
}

export function Alert({ tone = 'info', title, children, action }: { tone?: 'info' | 'warning' | 'error' | 'success'; title?: string; children?: ReactNode; action?: ReactNode }) {
  const tones = {
    info: 'border-blue-200 bg-blue-50 text-blue-900',
    warning: 'border-amber-200 bg-amber-50 text-amber-900',
    error: 'border-red-200 bg-red-50 text-red-900',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  };
  return (
    <div className={cx('flex items-start gap-3 rounded-lg border px-4 py-3 text-sm', tones[tone])}>
      {tone === 'success' ? <CircleCheck className="mt-0.5 size-4 shrink-0" /> : <CircleAlert className="mt-0.5 size-4 shrink-0" />}
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cx(title && 'mt-0.5', 'opacity-90')}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

// --- Badges -------------------------------------------------------------------------

const badgeTones = {
  gray: 'bg-gray-100 text-gray-700 ring-gray-200',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
  purple: 'bg-violet-50 text-violet-700 ring-violet-200',
  brand: 'bg-brand-50 text-brand-700 ring-brand-100',
};
export type Tone = keyof typeof badgeTones;

export function Badge({ tone = 'gray', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset', badgeTones[tone], className)}>{children}</span>;
}

const methodTones: Record<string, string> = {
  GET: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  POST: 'bg-blue-50 text-blue-700 ring-blue-200',
  PUT: 'bg-amber-50 text-amber-800 ring-amber-200',
  PATCH: 'bg-violet-50 text-violet-700 ring-violet-200',
  DELETE: 'bg-red-50 text-red-700 ring-red-200',
};

export function MethodBadge({ method }: { method: string }) {
  return (
    <span className={cx('inline-flex w-16 shrink-0 justify-center rounded-md py-0.5 font-mono text-[11px] font-semibold ring-1 ring-inset',
      methodTones[method] ?? 'bg-gray-100 text-gray-700 ring-gray-200')}>{method}</span>
  );
}

export function RoleBadge({ role }: { role: 'lead' | 'employee' }) {
  return role === 'lead' ? <Badge tone="brand">Lead</Badge> : <Badge tone="gray">Employee</Badge>;
}

export function Avatar({ name, size = 'md' }: { name: string; size?: 'sm' | 'md' }) {
  return (
    <span className={cx('inline-flex shrink-0 items-center justify-center rounded-full bg-brand-100 font-semibold text-brand-700',
      size === 'sm' ? 'size-7 text-[11px]' : 'size-9 text-xs')}>{initials(name)}</span>
  );
}

export function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
      <div className="h-full rounded-full bg-brand-600 transition-all duration-500" style={{ width: `${Math.max(4, Math.min(100, percent))}%` }} />
    </div>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => { void navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
      className="inline-flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-faint hover:bg-white/10 hover:text-white"
      aria-label="Copy"
    >
      {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
    </button>
  );
}

export function CommandLine({ command }: { command: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg bg-gray-900 py-1 pl-3 pr-1 font-mono text-[13px] leading-relaxed text-gray-100">
      <span className="select-none py-1.5 text-gray-500">&gt;</span>
      <code className="min-w-0 flex-1 break-all py-1.5">{command}</code>
      <CopyButton text={command} />
    </div>
  );
}

// --- Overlays --------------------------------------------------------------------------

function useEscape(onClose: () => void) {
  useEffect(() => {
    const listener = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', listener);
    return () => window.removeEventListener('keydown', listener);
  }, [onClose]);
}

export function Dialog({ title, description, onClose, children, footer, width = 'max-w-lg' }:
  { title: string; description?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: string }) {
  useEscape(onClose);
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-gray-900/40 p-4 pt-[10vh] animate-fade-in" onMouseDown={onClose}>
      <div className={cx('w-full rounded-2xl bg-surface shadow-xl animate-pop-in', width)} onMouseDown={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label={title}>
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <div>
            <h2 className="text-lg font-semibold text-ink">{title}</h2>
            {description && <p className="mt-1 text-sm text-muted">{description}</p>}
          </div>
          <button onClick={onClose} className="-mr-2 cursor-pointer rounded-md p-1.5 text-faint hover:bg-canvas hover:text-ink" aria-label="Close"><X className="size-5" /></button>
        </div>
        <div className="px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 rounded-b-2xl border-t border-line bg-canvas/60 px-6 py-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ title, subtitle, onClose, children, footer }: { title: ReactNode; subtitle?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEscape(onClose);
  return createPortal(
    <div className="fixed inset-0 z-40 flex justify-end bg-gray-900/30 animate-fade-in" onMouseDown={onClose}>
      <aside className="flex h-full w-full max-w-2xl flex-col bg-surface shadow-2xl animate-slide-in" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0">{title}{subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}</div>
          <button onClick={onClose} className="-mr-2 cursor-pointer rounded-md p-1.5 text-faint hover:bg-canvas hover:text-ink" aria-label="Close"><X className="size-5" /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {footer && <div className="flex flex-wrap items-center gap-2 border-t border-line bg-canvas/60 px-6 py-3">{footer}</div>}
      </aside>
    </div>,
    document.body,
  );
}

// --- Toasts ----------------------------------------------------------------------------------

interface Toast { id: number; tone: 'success' | 'error'; message: string }
const ToastContext = createContext<(tone: Toast['tone'], message: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((tone: Toast['tone'], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, tone, message }]);
    setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), tone === 'error' ? 6000 : 3500);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-96 max-w-[calc(100vw-2.5rem)] flex-col gap-2">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-sm shadow-lg animate-pop-in">
            {toast.tone === 'success' ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-red-600" />}
            <span className="text-ink-soft">{toast.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const show = useContext(ToastContext);
  return { success: (message: string) => show('success', message), error: (error: unknown) => show('error', error instanceof Error ? error.message : String(error)) };
}
