import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, Outlet, useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import { api, ApiError } from '../lib/api';
import { useMe } from '../lib/queries';
import { HelperChip } from './HelperConnect';
import { ModelPicker } from './ModelPicker';
import { Avatar, Spinner } from './ui';

export function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <img src="/favicon.svg" alt="" className="size-7" />
      <span className="text-[15px] font-semibold tracking-tight text-ink">API Test Studio</span>
    </span>
  );
}

export function AppShell() {
  const me = useMe();
  if (me.isPending) return <Spinner />;
  if (me.error) {
    if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace />;
    return <div className="p-10 text-center text-sm text-red-700">Cannot reach the portal server. Make sure it is running, then reload.</div>;
  }
  return (
    <div className="flex h-full flex-col">
      <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between border-b border-line bg-surface/95 px-4 backdrop-blur sm:px-6">
        <Link to="/" className="rounded-md"><Logo /></Link>
        <div className="flex items-center gap-2 sm:gap-3">
          <ModelPicker />
          <HelperChip />
          <UserMenu name={me.data.name} email={me.data.email} />
        </div>
      </header>
      <div className="min-h-0 flex-1"><Outlet /></div>
    </div>
  );
}

function UserMenu({ name, email }: { name: string; email: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const client = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api.post('/auth/logout'),
    onSettled: () => { client.clear(); navigate('/login'); },
  });
  useEffect(() => {
    const close = (event: MouseEvent) => ref.current && !ref.current.contains(event.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="cursor-pointer rounded-full" aria-label="Account menu"><Avatar name={name} /></button>
      {open && (
        <div className="absolute right-0 top-11 w-64 rounded-xl border border-line bg-surface p-1.5 shadow-lg animate-pop-in">
          <div className="px-3 py-2.5">
            <p className="truncate text-sm font-medium text-ink">{name}</p>
            <p className="truncate text-sm text-muted">{email}</p>
          </div>
          <div className="my-1 h-px bg-line" />
          <button onClick={() => logout.mutate()} className="flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-soft hover:bg-canvas">
            <LogOut className="size-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
