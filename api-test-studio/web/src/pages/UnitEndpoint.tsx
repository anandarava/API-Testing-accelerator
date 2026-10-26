import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ChevronDown, CircleCheck, CircleHelp, CircleX, MessageSquareWarning, RefreshCw, Sparkles } from 'lucide-react';
import { api, type CaseStatus, type TestCase, type UnitEndpointDetail } from '../lib/api';
import { jobActive, useHelper, useProjectId, useUnitEndpoint, useUnitOverview } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { CATEGORY_LABEL, PriorityBadge, STATUS_LABEL, StatusBadge, statusTone } from '../components/cases';
import { CaseDrawer, ReviewDialog } from '../components/CaseDrawer';
import { ExportMenu } from '../components/CaseTools';
import { Alert, Badge, Button, Card, CardHeader, Dialog, EmptyState, MethodBadge, ProgressBar, Spinner, cx, useToast } from '../components/ui';

type Filter = 'all' | CaseStatus;

export function UnitEndpointPage() {
  const { endpointId = '' } = useParams();
  const overview = useUnitOverview();
  const live = jobActive(overview.data?.job?.status);
  const detail = useUnitEndpoint(endpointId, live);
  const helper = useHelper();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openCase, setOpenCase] = useState<string | null>(null);
  const [dialog, setDialog] = useState<'needs_changes' | 'reject' | 'confirm_approve' | null>(null);

  const refresh = () => client.invalidateQueries({ queryKey: ['project', projectId] });
  const regenerate = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/unit/generate`, { endpointIds: [endpointId] }),
    onSuccess: () => { void refresh(); toast.success('Regeneration started. Approved cases are kept.'); },
    onError: toast.error,
  });
  const review = useMutation({
    mutationFn: ({ action, comment = '' }: { action: string; comment?: string }) =>
      api.post<{ updated: number }>(`/projects/${projectId}/unit/cases/review`, { caseIds: [...selected], action, comment }),
    onSuccess: (result) => { setSelected(new Set()); setDialog(null); void refresh(); toast.success(`${plural(result.updated, 'case')} updated.`); },
    onError: toast.error,
  });

  const cases = detail.data?.cases ?? [];
  const visible = useMemo(() => (filter === 'all' ? cases : cases.filter((c) => c.status === filter)), [cases, filter]);
  if (detail.isPending) return <Spinner />;
  if (!detail.data) return <Alert tone="error">{detail.error?.message}</Alert>;
  const data = detail.data;
  const { endpoint, coverage } = data;
  const current = cases.find((c) => c.id === openCase) ?? null;
  const counts = cases.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }), {});
  const allSelected = visible.length > 0 && visible.every((c) => selected.has(c.id));
  const toggle = (id: string) => setSelected((s) => { const next = new Set(s); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const unconfirmed = cases.filter((c) => selected.has(c.id) && c.needsConfirmation).length;
  const canGenerate = helper.data?.connected && !live;

  return (
    <>
      <Link to=".." relative="path" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-ink"><ArrowLeft className="size-4" /> Unit test cases</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-3"><MethodBadge method={endpoint.method} /><h1 className="truncate font-mono text-xl font-semibold text-ink">{endpoint.path}</h1></div>
          <p className="mt-1.5 text-sm text-muted">{endpoint.summary || endpoint.operationId}{coverage && ` · generated ${timeAgo(coverage.generatedAt)}${data.generatedBy ? ` by ${data.generatedBy}` : ''}`}</p>
        </div>
        <div className="flex gap-2">
        {cases.length > 0 && <ExportMenu module="unit" />}
        <Button variant={cases.length ? 'secondary' : 'primary'} icon={cases.length ? <RefreshCw className="size-4" /> : <Sparkles className="size-4" />}
          disabled={!canGenerate} title={!helper.data?.connected ? 'Connect your computer first' : live ? 'A generation is running' : undefined}
          loading={regenerate.isPending} onClick={() => regenerate.mutate()}>
          {cases.length ? 'Regenerate' : 'Generate test cases'}
        </Button>
        </div>
      </div>

      <div className="space-y-6">
        {live && overview.data?.job && <Alert tone="info" title="Generation in progress">{overview.data.job.progress.message}</Alert>}
        {coverage?.outdated && <Alert tone="warning" title="The API spec changed for this endpoint">Regenerate to design cases for the new contract. Approved cases are kept.</Alert>}
        {coverage?.error && <Alert tone="error" title="The last generation failed for this endpoint">{coverage.error}</Alert>}

        {!coverage && !cases.length ? (
          <Card><EmptyState icon={<Sparkles className="size-6" />} title="No test cases yet"
            description="Claude will design every scenario for this endpoint, check them against the spec's requirements and review them before they reach you." /></Card>
        ) : (
          <>
            <div className="grid gap-6 lg:grid-cols-2">
              <CoverageCard data={data} />
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
              <div className="hidden grid-cols-[2rem_5.5rem_minmax(0,1fr)_5rem_4.5rem_7.5rem] gap-3 border-b border-line bg-canvas/60 px-5 py-2 text-xs font-medium text-muted md:grid">
                <input type="checkbox" className="size-4 accent-brand-600" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(visible.map((c) => c.id)))} aria-label="Select all" />
                <span>ID</span><span>Test case</span><span>Priority</span><span>Expect</span><span>Status</span>
              </div>
              {visible.length === 0 ? <p className="px-5 py-10 text-center text-sm text-muted">No cases with this status.</p> : (
                <ul className="divide-y divide-line">
                  {visible.map((c) => <CaseRow key={c.id} item={c} regenerating={data.regenerating.includes(c.id)} checked={selected.has(c.id)} onToggle={() => toggle(c.id)} onOpen={() => setOpenCase(c.id)} />)}
                </ul>
              )}
            </Card>
          </>
        )}
      </div>

      {current && <CaseDrawer item={current} regenerating={data.regenerating.includes(current.id)} onClose={() => setOpenCase(null)} onChanged={refresh} />}
      {dialog === 'confirm_approve' && (
        <Dialog title={`Approve ${plural(selected.size, 'case')}?`} onClose={() => setDialog(null)}
          description={`${plural(unconfirmed, 'case')} ${unconfirmed === 1 ? 'has' : 'have'} an expected result the spec does not state exactly. Approving confirms that the expected results are correct.`}
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

function CaseRow({ item, regenerating, checked, onToggle, onOpen }: { item: TestCase; regenerating: boolean; checked: boolean; onToggle: () => void; onOpen: () => void }) {
  const serious = item.findings.filter((f) => f.severity !== 'minor').length;
  return (
    <li className="grid cursor-pointer grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 px-5 py-3 hover:bg-canvas md:grid-cols-[2rem_5.5rem_minmax(0,1fr)_5rem_4.5rem_7.5rem]" onClick={onOpen}>
      <input type="checkbox" className="size-4 cursor-pointer accent-brand-600" checked={checked} onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${item.code}`} />
      <span className="hidden font-mono text-xs text-muted md:block">{item.code}</span>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-ink">{item.title}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted">{CATEGORY_LABEL[item.category] ?? item.category}</span>
          {item.needsConfirmation && <Badge tone="amber"><CircleHelp className="size-3" /> Confirm expected result</Badge>}
          {serious > 0 && <Badge tone="red">{plural(serious, 'review note')}</Badge>}
          {item.outdated && <Badge tone="amber">Outdated</Badge>}
          {regenerating && <Badge tone="brand"><Sparkles className="size-3 animate-pulse" /> Regenerating…</Badge>}
          {item.script === 'current' && <Badge tone="green">Scripted</Badge>}
          {item.script === 'outdated' && <Badge tone="amber">Script needs update</Badge>}
        </div>
      </div>
      <span className="hidden md:block"><span className="inline-flex"><PriorityBadge priority={item.priority} /></span></span>
      <span className="hidden md:block">{item.content.expected.status ? <Badge tone={statusTone(item.content.expected.status)}>{item.content.expected.status}</Badge> : '—'}</span>
      <span><StatusBadge status={item.status} /></span>
    </li>
  );
}

function CoverageCard({ data }: { data: UnitEndpointDetail }) {
  const [open, setOpen] = useState(false);
  const coverage = data.coverage;
  if (!coverage) return null;
  const complete = coverage.gaps === 0;
  const missing = data.requirements.filter((r) => !r.covered);
  return (
    <Card>
      <CardHeader title="Spec requirements" description="Checked automatically against the contract: every required field, limit, documented status and auth rule."
        action={<Badge tone={complete ? 'green' : 'amber'}>{coverage.covered}/{coverage.total}</Badge>} />
      <div className="px-5 py-4">
        <ProgressBar percent={coverage.total ? (100 * coverage.covered) / coverage.total : 100} />
        <p className="mt-2 text-sm text-muted">
          {complete ? 'Every requirement is covered by at least one scenario.' : `${plural(missing.length, 'requirement')} not covered. Regenerate or add cases manually.`}
        </p>
        {missing.length > 0 && (
          <ul className="mt-3 space-y-1">{missing.map((r) => <li key={r.id} className="flex gap-2 text-sm text-amber-900"><CircleX className="mt-0.5 size-4 shrink-0 text-amber-600" />{r.description}</li>)}</ul>
        )}
        <button onClick={() => setOpen(!open)} className="mt-3 inline-flex cursor-pointer items-center gap-1 text-sm font-medium text-brand-600 hover:underline">
          {open ? 'Hide' : 'Show'} all requirements <ChevronDown className={cx('size-4 transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <ul className="mt-3 max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {data.requirements.map((r) => (
              <li key={r.id} className="flex items-start gap-2 px-3 py-2 text-sm">
                {r.covered ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-amber-600" />}
                <span className="min-w-0 flex-1 text-ink-soft">{r.description}</span>
                {r.scenarios.length > 0 && <span className="shrink-0 font-mono text-xs text-faint">{r.scenarios.join(', ')}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function ReviewerCard({ data }: { data: UnitEndpointDetail }) {
  const review = data.review;
  if (!review) return null;
  const general = review.findings.filter((f) => f.scenarioKey === 'checklist');
  const bySeverity = review.findings.reduce<Record<string, number>>((acc, f) => ({ ...acc, [f.severity]: (acc[f.severity] ?? 0) + 1 }), {});
  return (
    <Card>
      <CardHeader title="AI reviewer" description="A second Claude agent reviewed the cases like a QA lead."
        action={review.verdict === 'ready' ? <Badge tone="green">Ready</Badge> : <Badge tone="amber">Needs attention</Badge>} />
      <div className="space-y-3 px-5 py-4">
        <p className="text-sm leading-relaxed text-ink-soft">{review.summary}</p>
        <div className="flex flex-wrap gap-2">
          {(['blocker', 'major', 'minor'] as const).map((s) => bySeverity[s] ? <Badge key={s} tone={s === 'blocker' ? 'red' : s === 'major' ? 'amber' : 'gray'}>{bySeverity[s]} {s}</Badge> : null)}
        </div>
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
