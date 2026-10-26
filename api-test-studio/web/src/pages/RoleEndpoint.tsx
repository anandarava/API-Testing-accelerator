import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, CircleCheck, CircleHelp, CircleX, MessageSquareWarning, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { api, type CaseStatus, type RoleEndpointDetail, type TestCase } from '../lib/api';
import { jobActive, useHelper, useProjectId, useRoleEndpoint, useRoles } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { PriorityBadge, ROLE_KIND_LABEL, STATUS_LABEL, StatusBadge, statusTone } from '../components/cases';
import { CaseDrawer, ReviewDialog } from '../components/CaseDrawer';
import { ExportMenu } from '../components/CaseTools';
import { Alert, Badge, Button, Card, CardHeader, Dialog, EmptyState, MethodBadge, ProgressBar, Spinner, cx, useToast } from '../components/ui';

type Filter = 'all' | CaseStatus;

export function RoleEndpointPage() {
  const { endpointId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const roles = useRoles();
  const live = jobActive(roles.data?.job?.status);
  const detail = useRoleEndpoint(endpointId, live);
  const helper = useHelper();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openCase, setOpenCase] = useState<string | null>(null);
  const [dialog, setDialog] = useState<'needs_changes' | 'reject' | 'confirm_approve' | null>(null);
  const role = params.get('role') ?? '';
  const setRole = (value: string) => { setSelected(new Set()); setParams(value ? { role: value } : {}); };

  const refresh = () => client.invalidateQueries({ queryKey: ['project', projectId] });
  const regenerate = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/roles/generate`, { endpointIds: [endpointId] }),
    onSuccess: () => { void refresh(); toast.success('Role case generation started. Approved cases are kept.'); },
    onError: toast.error,
  });
  const review = useMutation({
    mutationFn: ({ action, comment = '' }: { action: string; comment?: string }) =>
      api.post<{ updated: number }>(`/projects/${projectId}/unit/cases/review`, { caseIds: [...selected], action, comment }),
    onSuccess: (result) => { setSelected(new Set()); setDialog(null); void refresh(); toast.success(`${plural(result.updated, 'case')} updated.`); },
    onError: toast.error,
  });

  const cases = detail.data?.cases ?? [];
  const visible = useMemo(() => cases.filter((c) => (filter === 'all' || c.status === filter) && (!role || (c.content.roles ?? []).includes(role))),
    [cases, filter, role]);
  if (detail.isPending) return <Spinner />;
  if (!detail.data) return <Alert tone="error">{detail.error?.message}</Alert>;
  const data = detail.data;
  const { endpoint, coverage } = data;
  const roleNames = roles.data?.analysis?.model.roles.map((r) => r.name) ?? [];
  const current = cases.find((c) => c.id === openCase) ?? null;
  const counts = cases.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }), {});
  const allSelected = visible.length > 0 && visible.every((c) => selected.has(c.id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const unconfirmed = cases.filter((c) => selected.has(c.id) && c.needsConfirmation).length;
  const ready = roles.data?.analysis?.ready;
  const canGenerate = helper.data?.connected && !live && ready;

  return (
    <>
      <Link to=".." relative="path" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-ink"><ArrowLeft className="size-4" /> Role test cases</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3"><MethodBadge method={endpoint.method} /><h1 className="truncate font-mono text-xl font-semibold text-ink">{endpoint.path}</h1></div>
          <p className="mt-1.5 text-sm text-muted">{endpoint.summary || endpoint.operationId}{coverage && ` · generated ${timeAgo(coverage.generatedAt)}`}</p>
        </div>
        <div className="flex gap-2">
          {cases.length > 0 && <ExportMenu module="role" />}
          <Button variant={cases.length ? 'secondary' : 'primary'} icon={cases.length ? <RefreshCw className="size-4" /> : <Sparkles className="size-4" />}
            disabled={!canGenerate} title={!helper.data?.connected ? 'Connect your computer first' : !ready ? 'Analyze the roles file first' : live ? 'A generation is running' : undefined}
            loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
            {cases.length ? 'Regenerate' : 'Generate role cases'}
          </Button>
        </div>
      </div>

      <div className="space-y-6">
        {live && roles.data?.job && <Alert tone="info" title="Generation in progress">{roles.data.job.progress.message}</Alert>}
        {coverage?.outdated && <Alert tone="warning" title="The permissions of this endpoint changed">Regenerate so the cases follow the current permission grid. Approved cases are kept.</Alert>}
        {coverage?.error && <Alert tone="error" title="Role cases were not generated for this endpoint">{coverage.error}</Alert>}
        <AccessCard data={data} />
        {!coverage && !cases.length ? (
          <Card><EmptyState icon={<ShieldCheck className="size-6" />} title="No role cases yet"
            description="Claude will write a case for each allowed role, one for the roles that must be refused, and second-user checks where roles may only reach their own records." /></Card>
        ) : (
          <>
            <div className="grid gap-6 lg:grid-cols-2">
              <ChecksCard data={data} />
              <ReviewerCard data={data} />
            </div>
            <Card>
              <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
                {(['all', 'in_review', 'approved', 'needs_changes', 'rejected'] as Filter[]).map((value) => (
                  <button key={value} onClick={() => { setFilter(value); setSelected(new Set()); }}
                    className={cx('h-8 cursor-pointer rounded-full border px-3 text-xs font-medium',
                      filter === value ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}>
                    {value === 'all' ? 'All' : STATUS_LABEL[value]} <span className="opacity-70">{value === 'all' ? cases.length : counts[value] ?? 0}</span>
                  </button>
                ))}
                {roleNames.length > 0 && (
                  <div className="ml-auto flex flex-wrap items-center gap-1">
                    <span className="mr-1 text-xs text-muted">Role:</span>
                    {['', ...roleNames].map((name) => (
                      <button key={name || 'all'} onClick={() => setRole(name)}
                        className={cx('h-7 cursor-pointer rounded-full border px-2.5 text-xs font-medium',
                          role === name ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-line bg-surface text-ink-soft hover:bg-canvas')}>{name || 'All'}</button>
                    ))}
                  </div>
                )}
              </div>
              {selected.size > 0 && (
                <div className="flex flex-wrap items-center gap-2 border-b border-line bg-brand-50/50 px-5 py-2.5 text-sm">
                  <span className="mr-2 font-medium text-ink">{plural(selected.size, 'case')} selected</span>
                  <Button size="sm" icon={<CircleCheck className="size-4" />} loading={review.isPending && review.variables?.action === 'approve'}
                    onClick={() => (unconfirmed ? setDialog('confirm_approve') : review.mutate({ action: 'approve' }))}>Approve</Button>
                  <Button size="sm" variant="secondary" icon={<MessageSquareWarning className="size-4" />} onClick={() => setDialog('needs_changes')}>Needs changes</Button>
                  <Button size="sm" variant="secondary" icon={<CircleX className="size-4" />} onClick={() => setDialog('reject')}>Reject</Button>
                  <button className="ml-auto cursor-pointer text-sm text-muted hover:text-ink" onClick={() => setSelected(new Set())}>Clear</button>
                </div>
              )}
              <div className="hidden grid-cols-[2rem_5.5rem_minmax(0,1fr)_12rem_4.5rem_7.5rem] gap-3 border-b border-line bg-canvas/60 px-5 py-2 text-xs font-medium text-muted md:grid">
                <input type="checkbox" className="size-4 accent-brand-600" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(visible.map((c) => c.id)))} aria-label="Select all" />
                <span>ID</span><span>Test case</span><span>Runs as</span><span>Expect</span><span>Status</span>
              </div>
              {visible.length === 0 ? <p className="px-5 py-10 text-center text-sm text-muted">{role ? `No cases for ${role} with this status.` : 'No cases with this status.'}</p> : (
                <ul className="divide-y divide-line">
                  {visible.map((c) => <CaseRow key={c.id} item={c} checked={selected.has(c.id)} onToggle={() => toggle(c.id)} onOpen={() => setOpenCase(c.id)} />)}
                </ul>
              )}
            </Card>
          </>
        )}
      </div>

      {current && <CaseDrawer item={current} regenerating={false} onClose={() => setOpenCase(null)} onChanged={refresh} />}
      {dialog === 'confirm_approve' && (
        <Dialog title={`Approve ${plural(selected.size, 'case')}?`} onClose={() => setDialog(null)}
          description={`${plural(unconfirmed, 'case')} ${unconfirmed === 1 ? 'has' : 'have'} an expected result the spec does not state exactly. Approving confirms it.`}
          footer={<><Button variant="secondary" onClick={() => setDialog(null)}>Cancel</Button><Button loading={review.isPending} onClick={() => review.mutate({ action: 'approve' })}>Approve and confirm</Button></>}>
          <p className="text-sm text-muted">Open a case to read its confirmation note before approving.</p>
        </Dialog>
      )}
      {(dialog === 'needs_changes' || dialog === 'reject') && (
        <ReviewDialog action={dialog} count={selected.size} loading={review.isPending} onClose={() => setDialog(null)}
          onSubmit={(comment) => review.mutate({ action: dialog, comment })} />
      )}
    </>
  );
}

function CaseRow({ item, checked, onToggle, onOpen }: { item: TestCase; checked: boolean; onToggle: () => void; onOpen: () => void }) {
  const serious = item.findings.filter((f) => f.severity !== 'minor').length;
  const roles = item.content.roles ?? [];
  return (
    <li className="grid cursor-pointer grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 px-5 py-3 hover:bg-canvas md:grid-cols-[2rem_5.5rem_minmax(0,1fr)_12rem_4.5rem_7.5rem]" onClick={onOpen}>
      <input type="checkbox" className="size-4 cursor-pointer accent-brand-600" checked={checked} onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${item.code}`} />
      <span className="hidden font-mono text-xs text-muted md:block">{item.code}</span>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">{item.title}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted">{ROLE_KIND_LABEL[item.category] ?? item.category}</span>
          <PriorityBadge priority={item.priority} />
          {item.needsConfirmation && <Badge tone="amber"><CircleHelp className="size-3" /> Confirm expected result</Badge>}
          {serious > 0 && <Badge tone="red">{plural(serious, 'review note')}</Badge>}
          {item.script === 'current' && <Badge tone="green">Scripted</Badge>}
          {item.script === 'outdated' && <Badge tone="amber">Script needs update</Badge>}
        </div>
      </div>
      <span className="hidden flex-wrap gap-1 md:flex">
        {roles.slice(0, 3).map((r) => <Badge key={r} tone="brand">{r}</Badge>)}
        {roles.length > 3 && <Badge>+{roles.length - 3}</Badge>}
        {item.content.userSlot === 'second' && <Badge tone="purple">2nd user</Badge>}
      </span>
      <span className="hidden md:block">{item.content.expected.status ? <Badge tone={statusTone(item.content.expected.status)}>{item.content.expected.status}</Badge> : '—'}</span>
      <span><StatusBadge status={item.status} /></span>
    </li>
  );
}

function AccessCard({ data }: { data: RoleEndpointDetail }) {
  const access = data.access;
  if (!access) return null;
  const groups: [keyof typeof access, string, 'green' | 'brand' | 'red' | 'amber'][] = [
    ['allowed', 'Allowed', 'green'], ['own', 'Own records only', 'brand'], ['denied', 'Denied', 'red'], ['unknown', 'Not decided (not tested)', 'amber'],
  ];
  return (
    <Card className="px-5 py-4">
      <div className="flex flex-wrap gap-x-8 gap-y-3">
        {groups.map(([key, label, tone]) => (access[key] as string[]).length > 0 && (
          <div key={key}>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">{label}</p>
            <div className="flex flex-wrap gap-1">{(access[key] as string[]).map((r) => <Badge key={r} tone={tone}>{r}</Badge>)}</div>
          </div>
        ))}
      </div>
      {access.evidence && <p className="mt-3 text-xs text-muted">Based on: "{access.evidence}"</p>}
      {data.rules.length > 0 && <ul className="mt-2 space-y-1 text-sm text-ink-soft">{data.rules.map((r, i) => <li key={i}>• {r.rule}</li>)}</ul>}
    </Card>
  );
}

function ChecksCard({ data }: { data: RoleEndpointDetail }) {
  const coverage = data.coverage;
  if (!coverage) return null;
  const complete = coverage.covered === coverage.total;
  return (
    <Card>
      <CardHeader title="Role checks" description="Computed from the cases themselves: every allowed role succeeds, every denied role is refused, and own-only roles are proven with a second user."
        action={<Badge tone={complete ? 'green' : 'amber'}>{coverage.covered}/{coverage.total}</Badge>} />
      <div className="px-5 py-4">
        <ProgressBar percent={coverage.total ? (100 * coverage.covered) / coverage.total : 100} />
        <ul className="mt-3 max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {data.requirements.map((r) => (
            <li key={r.id} className="flex items-start gap-2 px-3 py-2 text-sm">
              {r.covered ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-amber-600" />}
              <span className="min-w-0 flex-1 text-ink-soft">{r.description}</span>
              {r.cases.length > 0 && <span className="shrink-0 font-mono text-xs text-faint">{r.cases.join(', ')}</span>}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

function ReviewerCard({ data }: { data: RoleEndpointDetail }) {
  const review = data.review;
  if (!review) return null;
  const general = review.findings.filter((f) => f.scenarioKey === 'checklist');
  return (
    <Card>
      <CardHeader title="AI reviewer" description="A second Claude agent reviewed the role cases like a security-minded QA lead."
        action={review.verdict === 'ready' ? <Badge tone="green">Ready</Badge> : <Badge tone="amber">Needs attention</Badge>} />
      <div className="space-y-3 px-5 py-4">
        <p className="text-sm leading-relaxed text-ink-soft">{review.summary}</p>
        {general.length > 0 && (
          <div>
            <p className="mb-1.5 text-sm font-medium text-ink">Suggested additions</p>
            <ul className="space-y-2">{general.map((f, i) => <li key={i} className="text-sm text-muted"><span className="text-ink-soft">{f.issue}</span>{f.suggestion && <> — {f.suggestion}</>}</li>)}</ul>
          </div>
        )}
        <p className="text-xs text-faint">Notes about individual cases are shown on each case.</p>
      </div>
    </Card>
  );
}
