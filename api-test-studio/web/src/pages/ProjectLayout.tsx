import type { ReactNode } from 'react';
import { Link, NavLink, Outlet } from 'react-router';
import { ArrowLeft, FileCode, FolderCog, History, ListChecks, Network, Settings, Users, Workflow, ShieldCheck } from 'lucide-react';
import { ApiError } from '../lib/api';
import { useProject } from '../lib/queries';
import { Card, EmptyState, RoleBadge, Spinner, cx } from '../components/ui';
import { Assistant } from '../components/Assistant';

export function ProjectLayout() {
  const project = useProject();
  if (project.isPending) return <Spinner />;
  if (project.error) {
    const missing = project.error instanceof ApiError && project.error.status === 404;
    return (
      <div className="mx-auto max-w-xl p-10">
        <Card><EmptyState icon={<FolderCog className="size-6" />} title={missing ? 'Project not available' : 'Something went wrong'}
          description={missing ? 'This project does not exist or you are not a member. Ask the project lead to add you.' : project.error.message}
          action={<Link to="/" className="text-sm font-medium text-brand-600 hover:underline">Back to projects</Link>} /></Card>
      </div>
    );
  }
  const { data } = project;
  const lead = data.role === 'lead';
  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="border-b border-line px-4 py-4">
          <Link to="/" className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-ink"><ArrowLeft className="size-3.5" /> All projects</Link>
          <div className="flex items-start justify-between gap-2">
            <p className="font-semibold leading-snug text-ink">{data.name}</p>
            <RoleBadge role={data.role} />
          </div>
        </div>
        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
          <NavGroup>
            <Item to="" end icon={<Settings />} label="Configuration" />
            <Item to="apis" icon={<Network />} label="APIs" count={data.spec?.endpointCount} />
          </NavGroup>
          <NavGroup title="Test design">
            <Item to="unit-cases" icon={<ListChecks />} label="Unit test cases" />
            <Item to="flow-cases" icon={<Workflow />} label="Flow test cases" />
            <Item to="role-cases" icon={<ShieldCheck />} label="Role test cases" />
            <Item to="scripts" icon={<FileCode />} label="Scripts" />
          </NavGroup>
          <NavGroup title="Project">
            {lead && <Item to="members" icon={<Users />} label="Members" count={data.memberCount} />}
            <Item to="activity" icon={<History />} label="Activity" />
          </NavGroup>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <MobileNav lead={lead} />
        <div className="mx-auto max-w-6xl px-4 py-8 sm:px-8"><Outlet /></div>
        <Assistant />
      </main>
    </div>
  );
}

function NavGroup({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div>
      {title && <p className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-faint">{title}</p>}
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Item({ to, icon, label, count, soon, end }: { to: string; icon: ReactNode; label: string; count?: number; soon?: boolean; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => cx(
      'flex h-9 items-center gap-3 rounded-lg px-3 text-sm transition-colors [&>svg]:size-4 [&>svg]:shrink-0',
      isActive ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-soft hover:bg-canvas')}>
      {icon}
      <span className="flex-1 truncate">{label}</span>
      {soon && <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-muted">Soon</span>}
      {count !== undefined && !soon && <span className="text-xs text-faint">{count}</span>}
    </NavLink>
  );
}

function MobileNav({ lead }: { lead: boolean }) {
  const links = [['', 'Configuration'], ['apis', 'APIs'], ['unit-cases', 'Unit cases'], ['flow-cases', 'Flow cases'], ['role-cases', 'Role cases'], ['scripts', 'Scripts'], ...(lead ? [['members', 'Members']] : []), ['activity', 'Activity']];
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-2 md:hidden">
      {links.map(([to, label]) => (
        <NavLink key={to} to={to} end={to === ''} className={({ isActive }) => cx('shrink-0 rounded-md px-3 py-1.5 text-sm', isActive ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-soft')}>{label}</NavLink>
      ))}
    </div>
  );
}
