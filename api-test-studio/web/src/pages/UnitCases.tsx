import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronRight, CircleAlert, CircleCheck, ListChecks, Search, Sparkles, TriangleAlert } from 'lucide-react';
import { api, type CaseStatus, type Job, type UnitEndpointRow } from '../lib/api';
import { jobActive, useHelper, useProjectId, useUnitOverview } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { STATUS_DOT, STATUS_LABEL } from '../components/cases';
import { HelperDialog } from '../components/HelperConnect';
import { describeModels, modelLabel } from '../components/ModelPicker';
import { ExportMenu } from '../components/CaseTools';
import { Alert, Button, Card, EmptyState, Input, MethodBadge, PageHeader, ProgressBar, Spinner, cx, useToast } from '../components/ui';

export function UnitCasesPage() {
  const overview = useUnitOverview();
  const helper = useHelper();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [connecting, setConnecting] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ['project', projectId] });

  const generate = useMutation({
    mutationFn: (endpointIds: string[]) => api.post(`/projects/${projectId}/unit/generate`, { endpointIds }),
    onSuccess: () => { setSelected(new Set()); void refresh(); toast.success('Generation started on your computer.'); },
    onError: toast.error,
  });
  const cancel = useMutation({ mutationFn: (jobId: string) => api.post(`/projects/${projectId}/jobs/${jobId}/cancel`), onSuccess: refresh, onError: toast.error });

  const rows = overview.data?.endpoints ?? [];
  const visible = useMemo(() => {
    const text = query.trim().toLowerCase();
    return rows.filter((row) => !text || `${row.method} ${row.path} ${row.summary}`.toLowerCase().includes(text));
  }, [rows, query]);

  if (overview.isPending) return <Spinner />;
  if (!rows.length) {
    return (
      <>
        <PageHeader title="Unit test cases" />
        <Card><EmptyState icon={<ListChecks className="size-6" />} title="Upload an API spec first" description="Unit test cases are designed per endpoint from your OpenAPI or Swagger file."
          action={<Link to="../apis" className="text-sm font-medium text-brand-600 hover:underline">Go to APIs</Link>} /></Card>
      </>
    );
  }

  const job = overview.data!.job;
  const running = jobActive(job?.status);
  const totals = overview.data!.totals;
  const allVisibleSelected = visible.length > 0 && visible.every((row) => selected.has(row.id));
  const toggle = (id: string) => setSelected((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const toggleAll = () => setSelected(allVisibleSelected ? new Set() : new Set(visible.map((row) => row.id)));
  const notGenerated = rows.filter((row) => !row.coverage || row.coverage.error);
  const blocker = !helper.data?.connected ? 'Connect your computer to generate test cases.' : running ? 'A generation is already running.' : null;

  return (
    <>
      <PageHeader
        title="Unit test cases"
        description="Claude designs every scenario for each endpoint. Requirements from the spec are checked automatically, then your team reviews each case."
        action={
          <div className="flex gap-2">
            {Object.values(totals).some(Boolean) && <ExportMenu module="unit" />}
            <Button icon={<Sparkles className="size-4" />} disabled={!selected.size || !!blocker} title={blocker ?? undefined}
              loading={generate.isPending} onClick={() => generate.mutate([...selected])}>
              {selected.size ? `Generate for ${plural(selected.size, 'endpoint')}` : 'Select endpoints to generate'}
            </Button>
          </div>
        }
      />

      <div className="space-y-6">
        {!helper.data?.connected && (
          <Alert tone="info" title="Connect your computer to generate" action={<Button size="sm" variant="secondary" onClick={() => setConnecting(true)}>Connect</Button>}>
            Generation runs on your computer with your Claude account. You can still review existing cases.
          </Alert>
        )}
        {job && <JobBanner job={job} onCancel={() => cancel.mutate(job.id)} />}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(Object.keys(STATUS_LABEL) as CaseStatus[]).map((status) => (
            <Card key={status} className="px-4 py-3.5">
              <p className="flex items-center gap-2 text-xs font-medium text-muted"><span className={cx('size-2 rounded-full', STATUS_DOT[status])} />{STATUS_LABEL[status]}</p>
              <p className="mt-1 text-2xl font-semibold text-ink">{totals[status] ?? 0}</p>
            </Card>
          ))}
        </div>

        <Card>
          <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" className="size-4 accent-brand-600" checked={allVisibleSelected} onChange={toggleAll} /> Select all
            </label>
            {notGenerated.length > 0 && notGenerated.length < rows.length && (
              <button className="cursor-pointer text-sm font-medium text-brand-600 hover:underline" onClick={() => setSelected(new Set(notGenerated.map((r) => r.id)))}>
                Select {notGenerated.length} without cases
              </button>
            )}
            <div className="relative ml-auto w-full sm:w-72">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
              <Input className="h-9 pl-9" placeholder="Search endpoints" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
          <div className="hidden grid-cols-[2rem_minmax(0,1fr)_10rem_11rem_1.5rem] gap-4 border-b border-line bg-canvas/60 px-5 py-2 text-xs font-medium text-muted md:grid">
            <span /><span>Endpoint</span><span>Coverage</span><span>Review progress</span><span />
          </div>
          <ul className="divide-y divide-line">
            {visible.map((row) => <EndpointRow key={row.id} row={row} checked={selected.has(row.id)} onToggle={() => toggle(row.id)} />)}
          </ul>
        </Card>
      </div>
      {connecting && <HelperDialog onClose={() => setConnecting(false)} />}
    </>
  );
}

function EndpointRow({ row, checked, onToggle }: { row: UnitEndpointRow; checked: boolean; onToggle: () => void }) {
  const navigate = useNavigate();
  const open = () => navigate(row.id);
  return (
    <li className="grid cursor-pointer grid-cols-[2rem_minmax(0,1fr)_1.5rem] items-center gap-4 px-5 py-3 hover:bg-canvas md:grid-cols-[2rem_minmax(0,1fr)_10rem_11rem_1.5rem]" onClick={open}>
      <input type="checkbox" className="size-4 cursor-pointer accent-brand-600" checked={checked} onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${row.method} ${row.path}`} />
      <div className="flex min-w-0 items-center gap-3">
        <MethodBadge method={row.method} />
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] text-ink">{row.path}</p>
          <p className="truncate text-xs text-muted">{row.summary || '—'}</p>
        </div>
      </div>
      <div className="hidden md:block"><CoverageChip row={row} /></div>
      <div className="hidden md:block"><ReviewProgress row={row} /></div>
      <ChevronRight className="size-4 text-faint" />
    </li>
  );
}

function CoverageChip({ row }: { row: UnitEndpointRow }) {
  const coverage = row.coverage;
  if (!coverage) return <span className="text-sm text-faint">Not generated</span>;
  if (coverage.error && !row.caseCount) return <span className="inline-flex items-center gap-1.5 text-sm text-red-700"><CircleAlert className="size-4" /> Failed</span>;
  const complete = coverage.gaps === 0;
  return (
    <span className="flex flex-col">
      <span className={cx('inline-flex items-center gap-1.5 text-sm font-medium', complete ? 'text-emerald-700' : 'text-amber-700')}>
        {complete ? <CircleCheck className="size-4" /> : <TriangleAlert className="size-4" />} {coverage.covered}/{coverage.total} requirements
      </span>
      {coverage.outdated && <span className="text-xs text-amber-700">Spec changed — regenerate</span>}
    </span>
  );
}

function ReviewProgress({ row }: { row: UnitEndpointRow }) {
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

function modelText(job: Job): string {
  if (job.models.length) return ` on ${describeModels(job.models)}`;
  if (job.model && job.model !== 'default') return ` on ${modelLabel(job.model)}`;
  return '';
}

export function JobBanner({ job, onCancel, hint = 'Results appear below as each endpoint finishes.', usage }: { job: Job; onCancel: () => void; hint?: string; usage?: (job: Job) => string }) {
  if (jobActive(job.status)) {
    return (
      <Card className="border-brand-100 bg-brand-50/40 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink">{job.status === 'queued' ? 'Waiting for the Local Helper…' : job.progress.message || 'Generating…'}</p>
            <p className="mt-0.5 text-sm text-muted">Running on {job.requestedByName}'s computer{modelText(job)} · started {timeAgo(job.createdAt)}. {hint}</p>
          </div>
          <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
        <div className="mt-4"><ProgressBar percent={job.progress.percent ?? 2} /></div>
      </Card>
    );
  }
  if (job.status === 'failed' && job.finishedAt && Date.now() / 1000 - job.finishedAt < 86400) {
    return <Alert tone="error" title="The last generation stopped">{job.error}{job.models.length > 0 && <span className="opacity-75"> (ran on {describeModels(job.models)})</span>}</Alert>;
  }
  if (job.status === 'succeeded' && job.finishedAt && Date.now() / 1000 - job.finishedAt < 86400 && job.models.length) {
    return <p className="text-xs text-muted">Last run finished {timeAgo(job.finishedAt)} on {describeModels(job.models)}{usage?.(job) ? ` · ${usage(job)}` : ''}.</p>;
  }
  return null;
}
