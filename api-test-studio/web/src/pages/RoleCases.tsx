import { useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, CircleAlert, CircleCheck, FileUp, KeyRound, Search, ShieldCheck, Sparkles, Trash2, TriangleAlert, Upload } from 'lucide-react';
import { api, type AccessRow, type CaseStatus, type RolesOverview } from '../lib/api';
import { jobActive, useHelper, useProjectId, useRoles } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { STATUS_DOT, STATUS_LABEL } from '../components/cases';
import { HelperDialog } from '../components/HelperConnect';
import { ExportMenu } from '../components/CaseTools';
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Input, MethodBadge, PageHeader, Select, Spinner, cx, useToast } from '../components/ui';
import { JobBanner } from './UnitCases';

type Row = RolesOverview['endpoints'][number];
type Access = 'allowed' | 'own' | 'denied' | 'unknown';
const ACCESS: Access[] = ['allowed', 'own', 'denied', 'unknown'];
const NEXT: Record<Access, Access> = { allowed: 'own', own: 'denied', denied: 'unknown', unknown: 'allowed' };
const CELL: Record<Access, { label: string; className: string; title: string }> = {
  allowed: { label: 'Allowed', className: 'bg-emerald-50 text-emerald-800 border-emerald-200', title: 'May call it' },
  own: { label: 'Own only', className: 'bg-sky-50 text-sky-800 border-sky-200', title: 'Only for their own records' },
  denied: { label: 'Denied', className: 'bg-red-50 text-red-800 border-red-200', title: 'Must be refused' },
  unknown: { label: '?', className: 'bg-amber-50 text-amber-800 border-amber-300', title: 'Not decided: click to choose' },
};
const FORMATS = '.xlsx,.csv,.json,.yaml,.yml,.md,.txt,.docx';

function accessOf(row: AccessRow | null, role: string): Access {
  if (!row) return 'unknown';
  return ACCESS.find((a) => row[a].includes(role)) ?? 'unknown';
}

export function RoleCasesPage() {
  const roles = useRoles();
  const helper = useHelper();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [connecting, setConnecting] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ['project', projectId] });
  const analyze = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/roles/analyze`),
    onSuccess: () => { void refresh(); toast.success('Claude is reading your roles file on your computer.'); },
    onError: toast.error,
  });
  const generate = useMutation({
    mutationFn: (endpointIds: string[]) => api.post(`/projects/${projectId}/roles/generate`, { endpointIds }),
    onSuccess: () => { setSelected(new Set()); void refresh(); toast.success('Role test case generation started on your computer.'); },
    onError: toast.error,
  });
  const cancel = useMutation({ mutationFn: (jobId: string) => api.post(`/projects/${projectId}/jobs/${jobId}/cancel`), onSuccess: refresh, onError: toast.error });

  const data = roles.data;
  const rows = data?.endpoints ?? [];
  const visible = useMemo(() => {
    const text = query.trim().toLowerCase();
    return rows.filter((row) => (!text || `${row.method} ${row.path} ${row.summary}`.toLowerCase().includes(text))
      && (!roleFilter || row.roles.includes(roleFilter)));
  }, [rows, query, roleFilter]);

  if (roles.isPending) return <Spinner />;
  if (!data) return <Alert tone="error">{roles.error?.message}</Alert>;
  if (!rows.length) {
    return (
      <>
        <PageHeader title="Role test cases" />
        <Card><EmptyState icon={<ShieldCheck className="size-6" />} title="Upload an API spec first" description="Role test cases check, for every endpoint, which roles may call it."
          action={<Link to="../apis" className="text-sm font-medium text-brand-600 hover:underline">Go to APIs</Link>} /></Card>
      </>
    );
  }

  const analysis = data.analysis;
  const generating = jobActive(data.job?.status);
  const analyzing = jobActive(data.analyzeJob?.status);
  const roleNames = analysis?.model.roles.map((r) => r.name) ?? [];
  const decided = (row: Row) => !!row.access && (row.access.allowed.length + row.access.own.length + row.access.denied.length > 0);
  const allVisibleSelected = visible.length > 0 && visible.every((row) => selected.has(row.id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const notGenerated = rows.filter((row) => decided(row) && (!row.coverage || row.coverage.error || row.coverage.outdated));
  const blocker = !helper.data?.connected ? 'Connect your computer first.' : !data.document ? 'Upload the roles file first.'
    : !analysis?.ready ? 'Analyze the roles file first.' : generating || analyzing ? 'A role job is already running.' : null;

  return (
    <>
      <PageHeader title="Role test cases"
        description="Checks, for every endpoint, that each role can do exactly what your roles file allows: allowed roles succeed, others are refused, and users cannot reach each other's records."
        action={analysis && (
          <div className="flex gap-2">
            {Object.values(data.totals).some(Boolean) && <ExportMenu module="role" />}
            <Button icon={<Sparkles className="size-4" />} disabled={!selected.size || !!blocker} title={blocker ?? undefined}
              loading={generate.isPending} onClick={() => generate.mutate([...selected])}>
              {selected.size ? `Generate for ${plural(selected.size, 'endpoint')}` : 'Select endpoints to generate'}
            </Button>
          </div>
        )} />

      <div className="space-y-6">
        {!helper.data?.connected && (
          <Alert tone="info" title="Connect your computer to analyze and generate" action={<Button size="sm" variant="secondary" onClick={() => setConnecting(true)}>Connect</Button>}>
            Claude runs on your computer with your Claude account. You can still review existing role cases.
          </Alert>
        )}
        {data.document ? (
          <p className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <FileUp className="size-4 text-brand-600" />
            Roles file <span className="font-medium text-ink-soft">{data.document.filename}</span> · uploaded {timeAgo(data.document.uploadedAt)}
            <Link to=".." className="font-medium text-brand-600 hover:underline">Change it in Configuration</Link>
          </p>
        ) : (
          <Card><EmptyState icon={<FileUp className="size-6" />} title="Upload your roles file first"
            description="Role test cases are generated only from your roles file: the roles of your application and what each may do. Upload it in Configuration."
            action={<Link to=".." className="text-sm font-medium text-brand-600 hover:underline">Go to Configuration</Link>} /></Card>
        )}

        {data.document && (
          <>
            {data.analyzeJob && (analyzing || data.analyzeJob.status === 'failed') && (
              <JobBanner job={data.analyzeJob} onCancel={() => cancel.mutate(data.analyzeJob!.id)} hint="Reading the roles file against every operation usually takes a few minutes." />
            )}
            {!analysis ? (
              <Card className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="max-w-2xl">
                    <p className="text-sm font-semibold text-ink">Next: let Claude map your roles onto the API</p>
                    <p className="mt-1 text-sm text-muted">Claude reads your roles file with every operation of the spec and builds a permission grid. You can correct any cell before generating.</p>
                  </div>
                  <Button icon={<Sparkles className="size-4" />} disabled={!helper.data?.connected || analyzing} loading={analyze.isPending} onClick={() => analyze.mutate()}>Analyze roles file</Button>
                </div>
              </Card>
            ) : (
              <>
                <AnalysisCard data={data} analyzing={analyzing} onReanalyze={() => analyze.mutate()} reanalyzing={analyze.isPending} canRun={!!helper.data?.connected} />
                <PermissionGrid rows={rows} roles={roleNames} onChanged={refresh} />
              </>
            )}
          </>
        )}

        {analysis && (
          <>
            {data.job && <JobBanner job={data.job} onCancel={() => cancel.mutate(data.job!.id)} hint="Results appear below as each endpoint finishes." />}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {(Object.keys(STATUS_LABEL) as CaseStatus[]).map((status) => (
                <Card key={status} className="px-4 py-3.5">
                  <p className="flex items-center gap-2 text-xs font-medium text-muted"><span className={cx('size-2 rounded-full', STATUS_DOT[status])} />{STATUS_LABEL[status]}</p>
                  <p className="mt-1 text-2xl font-semibold text-ink">{data.totals[status] ?? 0}</p>
                </Card>
              ))}
            </div>
            <Card>
              <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                  <input type="checkbox" className="size-4 accent-brand-600" checked={allVisibleSelected}
                    onChange={() => setSelected(allVisibleSelected ? new Set() : new Set(visible.filter(decided).map((r) => r.id)))} /> Select all
                </label>
                {notGenerated.length > 0 && (
                  <button className="cursor-pointer text-sm font-medium text-brand-600 hover:underline" onClick={() => setSelected(new Set(notGenerated.map((r) => r.id)))}>
                    Select {notGenerated.length} to generate
                  </button>
                )}
                <div className="ml-auto flex w-full flex-wrap gap-2 sm:w-auto">
                  <Select className="h-9 w-full sm:w-48" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="Filter by role">
                    <option value="">All roles</option>
                    {roleNames.map((role) => <option key={role} value={role}>Cases for {role}</option>)}
                  </Select>
                  <div className="relative w-full sm:w-64">
                    <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
                    <Input className="h-9 pl-9" placeholder="Search endpoints" value={query} onChange={(e) => setQuery(e.target.value)} />
                  </div>
                </div>
              </div>
              <div className="hidden grid-cols-[2rem_minmax(0,1fr)_13rem_10rem_9rem_1.5rem] gap-4 border-b border-line bg-canvas/60 px-5 py-2 text-xs font-medium text-muted md:grid">
                <span /><span>Endpoint</span><span>Permissions</span><span>Role checks</span><span>Review progress</span><span />
              </div>
              {visible.length === 0 ? <p className="px-5 py-10 text-center text-sm text-muted">{roleFilter ? `No role cases for ${roleFilter} yet.` : 'No endpoints match.'}</p> : (
                <ul className="divide-y divide-line">
                  {visible.map((row) => <EndpointRow key={row.id} row={row} role={roleFilter} decided={decided(row)} checked={selected.has(row.id)} onToggle={() => toggle(row.id)} />)}
                </ul>
              )}
            </Card>
          </>
        )}
      </div>
      {connecting && <HelperDialog onClose={() => setConnecting(false)} />}
    </>
  );
}

export function RolesFileCard({ data, onChanged }: { data: RolesOverview; onChanged: () => void }) {
  const projectId = useProjectId();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const upload = useMutation({
    mutationFn: (file: File) => api.upload<{ filename: string; changed: boolean }>(`/projects/${projectId}/roles/document`, file),
    onSuccess: (result) => { onChanged(); toast.success(result.changed ? `${result.filename} uploaded. Analyze it to update the permissions.` : 'The file has not changed.'); },
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/roles/document`),
    onSuccess: () => { onChanged(); toast.success('Roles file removed. Role test cases will not be generated.'); },
    onError: toast.error,
  });
  const picker = (
    <input ref={input} type="file" accept={FORMATS} className="hidden"
      onChange={(e) => { const file = e.target.files?.[0]; if (file) upload.mutate(file); e.target.value = ''; }} />
  );
  const document = data.document;
  if (!document) {
    return (
      <Card>
        <div className="flex flex-col items-center px-6 py-10 text-center">
          <div className="flex size-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600"><FileUp className="size-6" /></div>
          <p className="mt-4 text-base font-semibold text-ink">Upload your roles file</p>
          <p className="mt-1 max-w-xl text-sm text-muted">
            List the roles of your application and what each may do, e.g. <span className="text-ink-soft">"Receptionist: register walk-in patients, check in appointments; cannot see medical records"</span>.
            Role test cases are generated only from this file.
          </p>
          <p className="mt-2 text-xs text-faint">Excel, CSV, JSON, YAML, Markdown, text or Word · up to 2 MB</p>
          <Button className="mt-5" icon={<Upload className="size-4" />} loading={upload.isPending} onClick={() => input.current?.click()}>Choose file</Button>
          <p className="mt-4 flex items-center gap-1.5 text-xs text-muted"><KeyRound className="size-3.5" /> No passwords here: credentials stay in your framework's .env file. Files containing passwords or tokens are refused.</p>
          {picker}
        </div>
      </Card>
    );
  }
  return (
    <Card className="flex flex-wrap items-center gap-4 px-5 py-4">
      <div className="flex size-10 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><FileUp className="size-5" /></div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink">{document.filename}</p>
        <p className="text-xs text-muted">Roles file · uploaded {timeAgo(document.uploadedAt)}{document.uploadedBy ? ` by ${document.uploadedBy}` : ''}</p>
      </div>
      <Button size="sm" variant="secondary" icon={<Upload className="size-4" />} loading={upload.isPending} onClick={() => input.current?.click()}>Replace</Button>
      <Button size="sm" variant="ghost" icon={<Trash2 className="size-4" />} loading={remove.isPending} onClick={() => remove.mutate()}>Remove</Button>
      {picker}
    </Card>
  );
}

function AnalysisCard({ data, analyzing, onReanalyze, reanalyzing, canRun }:
  { data: RolesOverview; analyzing: boolean; onReanalyze: () => void; reanalyzing: boolean; canRun: boolean }) {
  const [open, setOpen] = useState(false);
  const analysis = data.analysis!;
  const model = analysis.model;
  const unknown = model.operations.reduce((n, row) => n + row.unknown.length, 0);
  return (
    <Card>
      <CardHeader title="Roles and permissions"
        description={`Claude's reading of your roles file · ${timeAgo(analysis.generatedAt)}${analysis.generatedBy ? ` by ${analysis.generatedBy}` : ''}${analysis.editedBy ? ` · corrected by ${analysis.editedBy}` : ''}`}
        action={<Button size="sm" variant="secondary" icon={<Sparkles className="size-4" />} disabled={!canRun || analyzing} loading={reanalyzing} onClick={onReanalyze}>Analyze again</Button>} />
      <div className="space-y-4 px-5 py-4">
        {analysis.outdated && <Alert tone="warning" title="The roles file or the API spec changed">Analyze again so the permissions match. Your corrections in the grid are replaced by the new analysis.</Alert>}
        {model.summary && <p className="text-sm leading-relaxed text-ink-soft">{model.summary}</p>}
        <div className="flex flex-wrap gap-2">
          {model.roles.map((role) => (
            <div key={role.name} className="rounded-lg border border-line px-3 py-2" title={role.description}>
              <p className="text-sm font-medium text-ink">{role.name}</p>
              <p className="text-xs text-muted">{role.users > 1 ? `${role.users} test users` : '1 test user'}</p>
            </div>
          ))}
        </div>
        {unknown > 0 && <Alert tone="warning" title={`${plural(unknown, 'permission')} not decided`}>Neither your roles file nor the spec decides them. Choose them in the grid below; undecided roles are not tested.</Alert>}
        {model.missingFromFile.length > 0 && (
          <p className="text-sm text-ink-soft"><span className="font-medium text-ink">The spec also mentions:</span> {model.missingFromFile.join(', ')}. Add them to your roles file if they should be tested.</p>
        )}
        {model.systemCallers.length > 0 && <p className="text-sm text-ink-soft"><span className="font-medium text-ink">System callers:</span> {model.systemCallers.join(', ')}</p>}
        <button onClick={() => setOpen(!open)} className="inline-flex cursor-pointer items-center gap-1 text-sm font-medium text-brand-600 hover:underline">
          {open ? 'Hide' : 'Show'} credentials, access rules and questions <ChevronDown className={cx('size-4 transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <div className="grid gap-4 lg:grid-cols-3">
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Credentials in your framework</p>
              <p className="mb-2 text-xs text-muted">Scripts sign in with these variables from your framework's .env file (they use your own names when the framework already has them).</p>
              <ul className="space-y-1 font-mono text-xs text-ink-soft">
                {data.credentials.map((c) => (
                  <li key={c.role}>{c.prefix}_USERNAME / {c.prefix}_PASSWORD{c.users > 1 && <><br />{c.prefix}_2_USERNAME / {c.prefix}_2_PASSWORD</>}</li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Access rules</p>
              {model.rules.length ? <ul className="space-y-1.5 text-sm text-ink-soft">{model.rules.map((r, i) => <li key={i}>{r.rule} <span className="text-xs text-muted">({r.kind.replace('_', ' ')})</span></li>)}</ul>
                : <p className="text-sm text-muted">None found.</p>}
            </div>
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Questions to confirm</p>
              {model.questions.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-ink-soft">{model.questions.map((q) => <li key={q}>{q}</li>)}</ul>
                : <p className="text-sm text-muted">None.</p>}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function PermissionGrid({ rows, roles, onChanged }: { rows: Row[]; roles: string[]; onChanged: () => void }) {
  const projectId = useProjectId();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [onlyUnknown, setOnlyUnknown] = useState(false);
  const save = useMutation({
    mutationFn: ({ row, role }: { row: Row; role: string }) => {
      const current = accessOf(row.access, role);
      const next = NEXT[current];
      const lists: Record<Access, string[]> = { allowed: [], own: [], denied: [], unknown: [] };
      for (const name of roles) lists[name === role ? next : accessOf(row.access, name)].push(name);
      return api.put(`/projects/${projectId}/roles/access/${row.operationId}`, lists);
    },
    onSuccess: onChanged,
    onError: toast.error,
  });
  const unknownRows = rows.filter((row) => row.access && row.access.unknown.length > 0);
  const shown = onlyUnknown ? unknownRows : rows;
  return (
    <Card>
      <CardHeader title="Permission grid" description="Who may call each endpoint. Click a cell to change it: Allowed → Own only → Denied → ? (not decided)."
        action={<Button size="sm" variant="secondary" onClick={() => setOpen(!open)}>{open ? 'Hide grid' : `Show grid${unknownRows.length ? ` · ${unknownRows.length} to decide` : ''}`}</Button>} />
      {open && (
        <div className="px-5 pb-5">
          <label className="mb-3 flex w-fit cursor-pointer items-center gap-2 text-sm text-ink-soft">
            <input type="checkbox" className="size-4 accent-brand-600" checked={onlyUnknown} onChange={() => setOnlyUnknown(!onlyUnknown)} /> Only endpoints with undecided roles
          </label>
          <div className="max-h-[32rem] overflow-auto rounded-lg border border-line">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="sticky top-0 z-10 bg-canvas text-left text-xs font-semibold text-muted">
                <tr>
                  <th className="px-3 py-2">Endpoint</th>
                  {roles.map((role) => <th key={role} className="px-2 py-2 text-center">{role}</th>)}
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.id} className="border-t border-line">
                    <td className="px-3 py-1.5" title={row.access?.evidence || undefined}>
                      <span className="flex items-center gap-2"><MethodBadge method={row.method} /><span className="truncate font-mono text-xs text-ink">{row.path}</span></span>
                      {row.access?.editedBy && <span className="text-[11px] text-muted">corrected by {row.access.editedBy}</span>}
                    </td>
                    {roles.map((role) => {
                      const access = accessOf(row.access, role);
                      return (
                        <td key={role} className="px-1.5 py-1.5 text-center">
                          <button disabled={save.isPending} onClick={() => save.mutate({ row, role })} title={`${role}: ${CELL[access].title}`}
                            className={cx('h-7 w-full min-w-16 cursor-pointer rounded-md border px-1.5 text-xs font-medium', CELL[access].className)}>{CELL[access].label}</button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted">Hover an endpoint to see the text the permission is based on. Endpoints whose permissions change are marked for regeneration.</p>
        </div>
      )}
    </Card>
  );
}

function EndpointRow({ row, role, decided, checked, onToggle }: { row: Row; role: string; decided: boolean; checked: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const open = () => navigate(role ? `${row.id}?role=${encodeURIComponent(role)}` : row.id);
  const a = row.access;
  return (
    <li className="grid cursor-pointer grid-cols-[2rem_minmax(0,1fr)_1.5rem] items-center gap-4 px-5 py-3 hover:bg-canvas md:grid-cols-[2rem_minmax(0,1fr)_13rem_10rem_9rem_1.5rem]" onClick={open}>
      <input type="checkbox" className="size-4 cursor-pointer accent-brand-600 disabled:cursor-not-allowed" disabled={!decided} checked={checked}
        onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${row.method} ${row.path}`} title={decided ? undefined : 'No role is decided for this endpoint yet'} />
      <div className="flex min-w-0 items-center gap-3">
        <MethodBadge method={row.method} />
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] text-ink">{row.path}</p>
          <p className="truncate text-xs text-muted">{row.summary || '—'}</p>
        </div>
      </div>
      <div className="hidden flex-wrap gap-1 md:flex">
        {a ? ACCESS.map((key) => a[key].length > 0 && <Badge key={key} tone={key === 'allowed' ? 'green' : key === 'denied' ? 'red' : key === 'own' ? 'brand' : 'amber'}>{a[key].length} {key === 'own' ? 'own only' : key === 'unknown' ? 'undecided' : key}</Badge>)
          : <span className="text-sm text-faint">—</span>}
      </div>
      <div className="hidden md:block"><ChecksChip row={row} /></div>
      <div className="hidden md:block"><Progress row={row} /></div>
      <ChevronRight className="size-4 text-faint" />
    </li>
  );
}

function ChecksChip({ row }: { row: Row }) {
  const coverage = row.coverage;
  if (!coverage) return <span className="text-sm text-faint">Not generated</span>;
  if (coverage.error && !row.caseCount) return <span className="inline-flex items-center gap-1.5 text-sm text-red-700" title={coverage.error}><CircleAlert className="size-4" /> Not generated</span>;
  const complete = coverage.covered === coverage.total;
  return (
    <span className="flex flex-col">
      <span className={cx('inline-flex items-center gap-1.5 text-sm font-medium', complete ? 'text-emerald-700' : 'text-amber-700')}>
        {complete ? <CircleCheck className="size-4" /> : <TriangleAlert className="size-4" />} {coverage.covered}/{coverage.total} checks
      </span>
      {coverage.outdated && <span className="text-xs text-amber-700">Permissions changed: regenerate</span>}
    </span>
  );
}

function Progress({ row }: { row: Row }) {
  if (!row.caseCount) return <span className="text-sm text-faint">—</span>;
  const order: CaseStatus[] = ['approved', 'in_review', 'needs_changes', 'rejected'];
  return (
    <div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-gray-100">
        {order.map((status) => row.cases[status] > 0 && <span key={status} className={STATUS_DOT[status]} style={{ width: `${(100 * row.cases[status]) / row.caseCount}%` }} />)}
      </div>
      <p className="mt-1 text-xs text-muted">{row.cases.approved} of {plural(row.caseCount, 'case')} approved</p>
    </div>
  );
}
