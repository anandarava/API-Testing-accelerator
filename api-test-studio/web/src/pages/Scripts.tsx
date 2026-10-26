import { useState } from 'react';
import { Link } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, CircleCheck, CircleDashed, CircleX, FileCode, FolderOpen, Sparkles } from 'lucide-react';
import { api, type CheckSummary, type FlowScriptRow, type ScriptRow, type ScriptState } from '../lib/api';
import { jobActive, useHelper, useProjectId, useScriptDetail, useScripts } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { HelperDialog } from '../components/HelperConnect';
import { Alert, Badge, Button, Card, CopyButton, Drawer, EmptyState, MethodBadge, PageHeader, Spinner, cx, useToast, type Tone } from '../components/ui';
import { JobBanner } from './UnitCases';

const STATE: Record<ScriptState, { label: string; tone: Tone }> = {
  not_generated: { label: 'Not generated', tone: 'gray' },
  up_to_date: { label: 'Up to date', tone: 'green' },
  needs_update: { label: 'Needs update', tone: 'amber' },
  checks_failed: { label: 'Checks failed', tone: 'red' },
  failed: { label: 'Failed', tone: 'red' },
};
const CHECK_LABEL = { typecheck: 'TypeScript', lint: 'Lint', discovery: 'Playwright' };

export function ScriptsPage() {
  const scripts = useScripts();
  const helper = useHelper();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedFlows, setSelectedFlows] = useState<Set<string>>(new Set());
  const [selectedRoles, setSelectedRoles] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<{ id: string; kind: 'endpoint' | 'flow' | 'role' } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ['project', projectId] });
  const generate = useMutation({
    mutationFn: (ids?: { endpointIds: string[]; flowIds: string[]; roleEndpointIds: string[] }) =>
      api.post(`/projects/${projectId}/scripts/generate`, ids ?? { endpointIds: [...selected], flowIds: [...selectedFlows], roleEndpointIds: [...selectedRoles] }),
    onSuccess: () => { setSelected(new Set()); setSelectedFlows(new Set()); setSelectedRoles(new Set()); void refresh(); toast.success('Script generation started on your computer.'); },
    onError: toast.error,
  });
  const cancel = useMutation({ mutationFn: (jobId: string) => api.post(`/projects/${projectId}/jobs/${jobId}/cancel`), onSuccess: refresh, onError: toast.error });

  if (scripts.isPending) return <Spinner />;
  const data = scripts.data!;
  const rows = data.endpoints;
  const flowRows = data.flows;
  const roleRows = data.roleEndpoints ?? [];
  const count = selected.size + selectedFlows.size + selectedRoles.size;
  const missingEndpoints = rows.filter((r) => r.approved > 0 && r.state !== 'up_to_date' && r.state !== 'checks_failed').map((r) => r.id);
  const missingFlows = flowRows.filter((r) => r.approved > 0 && r.state !== 'up_to_date' && r.state !== 'checks_failed').map((r) => r.id);
  const missingRoles = roleRows.filter((r) => r.approved > 0 && r.state !== 'up_to_date' && r.state !== 'checks_failed').map((r) => r.id);
  const missing = missingEndpoints.length + missingFlows.length + missingRoles.length;
  const running = jobActive(data.job?.status);
  const blocker = data.profileStatus !== 'confirmed' ? 'profile' : !data.frameworkPathSet ? 'folder' : !helper.data?.connected ? 'helper' : null;
  const all = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleFlow = (id: string) => setSelectedFlows((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleRole = (id: string) => setSelectedRoles((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const needing = rows.filter((r) => r.state !== 'up_to_date');

  return (
    <>
      <PageHeader title="Scripts"
        description="Approved test cases become Playwright + TypeScript tests in your framework folder, following the confirmed framework profile. Nothing is run; you run the tests yourself."
        action={
          <div className="flex flex-wrap gap-2">
            {missing > 0 && !count && (
              <Button icon={<Sparkles className="size-4" />} disabled={!!blocker || running} loading={generate.isPending}
                onClick={() => generate.mutate({ endpointIds: missingEndpoints, flowIds: missingFlows, roleEndpointIds: missingRoles })}>Generate missing scripts ({missing})</Button>
            )}
            {(count > 0 || !missing) && (
              <Button icon={<Sparkles className="size-4" />} disabled={!count || !!blocker || running} loading={generate.isPending}
                onClick={() => generate.mutate(undefined)}>{count ? `Generate ${plural(count, 'script file')}` : 'Select tests to generate'}</Button>
            )}
          </div>
        } />

      <div className="space-y-6">
        {blocker === 'profile' && <Alert tone="info" title="Confirm the framework profile first" action={<Link to=".." className="text-sm font-medium text-brand-700 hover:underline">Open Configuration</Link>}>Scripts follow your team's conventions, so the profile must be reviewed and confirmed.</Alert>}
        {blocker === 'folder' && <Alert tone="info" title="Set your framework folder" action={<Link to=".." className="text-sm font-medium text-brand-700 hover:underline">Open Configuration</Link>}>Scripts are written into your own copy of the framework repository.</Alert>}
        {blocker === 'helper' && <Alert tone="info" title="Connect your computer to generate scripts" action={<Button size="sm" variant="secondary" onClick={() => setConnecting(true)}>Connect</Button>}>Generation runs on your computer and writes into your local framework folder.</Alert>}
        {data.job && <JobBanner job={data.job} onCancel={() => cancel.mutate(data.job!.id)} hint="Results appear below as each file is written and checked." />}

        {!rows.length && !flowRows.length && !roleRows.length && (
          <Card><EmptyState icon={<FileCode className="size-6" />} title="No approved test cases yet"
            description="Approve unit or flow test cases first. Every endpoint and flow with approved cases appears here."
            action={<Link to="../unit-cases" className="text-sm font-medium text-brand-600 hover:underline">Go to unit test cases</Link>} /></Card>
        )}
        {rows.length > 0 && (
          <Card>
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="size-4 accent-brand-600" checked={all} onChange={() => setSelected(all ? new Set() : new Set(rows.map((r) => r.id)))} /> Select all
              </label>
              {needing.length > 0 && needing.length < rows.length && (
                <button className="cursor-pointer text-sm font-medium text-brand-600 hover:underline" onClick={() => setSelected(new Set(needing.map((r) => r.id)))}>Select {needing.length} that need scripts</button>
              )}
            </div>
            <div className="hidden grid-cols-[2rem_minmax(0,1fr)_9rem_8rem_11rem_1.5rem] gap-4 border-b border-line bg-canvas/60 px-5 py-2 text-xs font-medium text-muted lg:grid">
              <span /><span>Endpoint</span><span>Tests</span><span>Status</span><span>Checks</span><span />
            </div>
            <ul className="divide-y divide-line">
              {rows.map((row) => <Row key={row.id} row={row} checked={selected.has(row.id)} onToggle={() => toggle(row.id)} onOpen={() => setOpen({ id: row.id, kind: 'endpoint' })} />)}
            </ul>
          </Card>
        )}
        {flowRows.length > 0 && (
          <Card>
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
              <h2 className="text-sm font-semibold text-ink">Flow tests</h2>
              <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="size-4 accent-brand-600" checked={flowRows.every((r) => selectedFlows.has(r.id))}
                  onChange={() => setSelectedFlows(flowRows.every((r) => selectedFlows.has(r.id)) ? new Set() : new Set(flowRows.map((r) => r.id)))} /> Select all flows
              </label>
            </div>
            <ul className="divide-y divide-line">
              {flowRows.map((row) => <FlowRow key={row.id} row={row} checked={selectedFlows.has(row.id)} onToggle={() => toggleFlow(row.id)} onOpen={() => setOpen({ id: row.id, kind: 'flow' })} />)}
            </ul>
          </Card>
        )}
        {roleRows.length > 0 && (
          <Card>
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
              <h2 className="text-sm font-semibold text-ink">Role tests</h2>
              <span className="text-xs text-muted">One file per endpoint (.roles.spec.ts); each role signs in with its credentials from your framework's .env</span>
              <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="size-4 accent-brand-600" checked={roleRows.every((r) => selectedRoles.has(r.id))}
                  onChange={() => setSelectedRoles(roleRows.every((r) => selectedRoles.has(r.id)) ? new Set() : new Set(roleRows.map((r) => r.id)))} /> Select all
              </label>
            </div>
            <ul className="divide-y divide-line">
              {roleRows.map((row) => <Row key={row.id} row={row} checked={selectedRoles.has(row.id)} onToggle={() => toggleRole(row.id)} onOpen={() => setOpen({ id: row.id, kind: 'role' })} />)}
            </ul>
          </Card>
        )}
      </div>
      {open && <ScriptDrawer endpointId={open.id} kind={open.kind} onClose={() => setOpen(null)} />}
      {connecting && <HelperDialog onClose={() => setConnecting(false)} />}
    </>
  );
}

function Row({ row, checked, onToggle, onOpen }: { row: ScriptRow; checked: boolean; onToggle: () => void; onOpen: () => void }) {
  const pending = row.changed + row.new + row.removed;
  return (
    <li className="grid cursor-pointer grid-cols-[2rem_minmax(0,1fr)_1.5rem] items-center gap-4 px-5 py-3 hover:bg-canvas lg:grid-cols-[2rem_minmax(0,1fr)_9rem_8rem_11rem_1.5rem]" onClick={onOpen}>
      <input type="checkbox" className="size-4 cursor-pointer accent-brand-600" checked={checked} onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${row.method} ${row.path}`} />
      <div className="flex min-w-0 items-center gap-3">
        <MethodBadge method={row.method} />
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] text-ink">{row.path}</p>
          <p className="truncate text-xs text-muted">{row.filePath ? <span className="font-mono">{row.filePath}</span> : row.summary}</p>
        </div>
      </div>
      <div className="hidden text-sm lg:block">
        <p className="text-ink-soft">{row.scripted} of {row.approved} approved</p>
        {pending > 0 && row.generatedAt && <p className="text-xs text-amber-700">{plural(pending, 'change')} to apply</p>}
      </div>
      <span className="hidden lg:block"><span className="inline-flex"><Badge tone={STATE[row.state].tone}>{STATE[row.state].label}</Badge></span></span>
      <div className="hidden lg:block"><Checks checks={row.checks} /></div>
      <ChevronRight className="size-4 text-faint" />
    </li>
  );
}

function FlowRow({ row, checked, onToggle, onOpen }: { row: FlowScriptRow; checked: boolean; onToggle: () => void; onOpen: () => void }) {
  return (
    <li className="grid cursor-pointer grid-cols-[2rem_minmax(0,1fr)_1.5rem] items-center gap-4 px-5 py-3 hover:bg-canvas lg:grid-cols-[2rem_minmax(0,1fr)_8rem_11rem_1.5rem]" onClick={onOpen}>
      <input type="checkbox" className="size-4 cursor-pointer accent-brand-600" checked={checked} onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${row.code}`} />
      <div className="min-w-0">
        <p className="truncate text-sm text-ink"><span className="font-mono text-xs text-muted">{row.code}</span> {row.title}</p>
        <p className="truncate text-xs text-muted">{row.filePath ? <span className="font-mono">{row.filePath}</span> : plural(row.steps, 'step')}</p>
      </div>
      <span className="hidden lg:block"><span className="inline-flex"><Badge tone={STATE[row.state].tone}>{STATE[row.state].label}</Badge></span></span>
      <div className="hidden lg:block"><Checks checks={row.checks} /></div>
      <ChevronRight className="size-4 text-faint" />
    </li>
  );
}

function CheckIcon({ status }: { status: CheckSummary['status'] }) {
  if (status === 'passed') return <CircleCheck className="size-4 text-emerald-600" />;
  if (status === 'failed') return <CircleX className="size-4 text-red-600" />;
  return <CircleDashed className="size-4 text-faint" />;
}

function Checks({ checks }: { checks: CheckSummary[] }) {
  if (!checks.length) return <span className="text-sm text-faint">—</span>;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1">
      {checks.map((c) => <span key={c.name} title={c.detail} className="inline-flex items-center gap-1 text-xs text-ink-soft"><CheckIcon status={c.status} />{CHECK_LABEL[c.name]}</span>)}
    </div>
  );
}

function ScriptDrawer({ endpointId, kind, onClose }: { endpointId: string; kind: 'endpoint' | 'flow' | 'role'; onClose: () => void }) {
  const flow = kind === 'flow';
  const detail = useScriptDetail(endpointId, kind);
  const [tab, setTab] = useState<'code' | 'changes'>('code');
  const data = detail.data;
  return (
    <Drawer onClose={onClose}
      title={data ? (flow ? <span className="text-base font-semibold text-ink">{data.endpoint.path}</span>
        : <div className="flex items-center gap-3"><MethodBadge method={data.endpoint.method} /><span className="truncate font-mono text-sm font-medium text-ink">{data.endpoint.path}</span></div>) : 'Loading…'}
      subtitle={data?.filePath && <span className="inline-flex items-center gap-1.5 font-mono text-xs"><FolderOpen className="size-3.5" />{data.filePath}</span>}>
      {!data ? <Spinner /> : (
        <div className="space-y-6 px-6 py-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATE[data.state].tone}>{STATE[data.state].label}</Badge>
            {data.generatedAt && <span className="text-sm text-muted">Generated {timeAgo(data.generatedAt)} on {data.generatedBy}'s computer{data.fixRounds ? ` · ${plural(data.fixRounds, 'automatic fix round')}` : ''}</span>}
          </div>
          {data.error && <Alert tone="error" title="The last generation failed">{data.error}</Alert>}
          {data.state === 'needs_update' && (
            <Alert tone="warning" title="Approved cases changed since this file was generated">
              {[data.changed && `${data.changed} edited`, data.new && `${data.new} newly approved`, data.removed && `${data.removed} no longer approved`].filter(Boolean).join(' · ')}. Generate again to update the file.
            </Alert>
          )}

          {data.checksFull.length > 0 && (
            <section>
              <h3 className="mb-2 text-sm font-semibold text-ink">Checks on your computer</h3>
              <ul className="divide-y divide-line rounded-lg border border-line">
                {data.checksFull.map((c) => (
                  <li key={c.name} className="px-4 py-2.5">
                    <div className="flex items-center gap-2 text-sm"><CheckIcon status={c.status} /><span className="font-medium text-ink">{CHECK_LABEL[c.name]}</span><span className="text-muted">{c.detail}</span></div>
                    {c.output && <pre className="mt-2 max-h-48 overflow-auto rounded-md bg-gray-900 p-3 font-mono text-xs text-gray-100">{c.output}</pre>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(data.envVariables.length > 0 || data.notes) && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-ink">Before you run</h3>
              {data.envVariables.length > 0 && (
                <p className="flex flex-wrap items-center gap-1.5 text-sm text-muted">Environment variables:
                  {data.envVariables.map((v) => <code key={v} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-ink-soft">{v}</code>)}</p>
              )}
              {data.notes && <p className="whitespace-pre-line text-sm text-ink-soft">{data.notes}</p>}
            </section>
          )}

          {data.content && (
            <section>
              <div className="mb-2 flex items-center justify-between">
                <div className="flex gap-1 rounded-lg bg-canvas p-1">
                  {(['code', 'changes'] as const).map((value) => (
                    <button key={value} onClick={() => setTab(value)} className={cx('h-7 cursor-pointer rounded-md px-3 text-sm font-medium',
                      tab === value ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink')}>{value === 'code' ? 'Code' : 'Changes'}</button>
                  ))}
                </div>
                <div className="rounded-md bg-gray-900"><CopyButton text={data.content} /></div>
              </div>
              {tab === 'code' ? <CodeView text={data.content} /> : <DiffView diff={data.diff} />}
            </section>
          )}

          <section>
            <h3 className="mb-2 text-sm font-semibold text-ink">Approved cases ({data.cases.length})</h3>
            <ul className="divide-y divide-line rounded-lg border border-line">
              {data.cases.map((c) => (
                <li key={c.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                  <span className="font-mono text-xs text-muted">{c.code}</span>
                  <span className="min-w-0 flex-1 truncate text-ink-soft">{c.title}</span>
                  {c.state === 'current' ? <Badge tone="green">In file</Badge> : c.state === 'changed' ? <Badge tone="amber">Edited</Badge> : <Badge>Not yet</Badge>}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </Drawer>
  );
}

function CodeView({ text }: { text: string }) {
  const lines = text.split('\n');
  return (
    <pre className="max-h-[32rem] overflow-auto rounded-lg bg-gray-900 py-3 font-mono text-xs leading-relaxed text-gray-100">
      {lines.map((line, i) => (
        <div key={i} className="flex"><span className="w-10 shrink-0 select-none pr-3 text-right text-gray-500">{i + 1}</span><span className="whitespace-pre pr-4">{line || ' '}</span></div>
      ))}
    </pre>
  );
}

function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) return <p className="rounded-lg border border-line px-4 py-6 text-center text-sm text-muted">No changes compared with the previous version.</p>;
  return (
    <pre className="max-h-[32rem] overflow-auto rounded-lg bg-gray-900 py-3 font-mono text-xs leading-relaxed">
      {diff.split('\n').map((line, i) => (
        <div key={i} className={cx('whitespace-pre px-4', line.startsWith('+') && !line.startsWith('+++') ? 'bg-emerald-950 text-emerald-200'
          : line.startsWith('-') && !line.startsWith('---') ? 'bg-red-950 text-red-200' : line.startsWith('@@') ? 'text-sky-300' : 'text-gray-400')}>{line || ' '}</div>
      ))}
    </pre>
  );
}
