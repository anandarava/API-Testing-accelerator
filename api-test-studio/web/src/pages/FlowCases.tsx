import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowDown, ChevronDown, CircleCheck, Play, CircleHelp, CircleX, MessageSquareWarning, Pencil, RotateCcw, Search, Sparkles, Trash2, Workflow } from 'lucide-react';
import { api, type CaseStatus, type FlowCase, type FlowsOverview } from '../lib/api';
import { jobActive, useHelper, useProjectId, useFlows } from '../lib/queries';
import { plural } from '../lib/format';
import { AUTH_LABEL, PriorityBadge, STATUS_LABEL, StatusBadge, statusTone, PRIORITY_LABEL } from '../components/cases';
import { ReviewDialog } from '../components/CaseDrawer';
import { HelperDialog } from '../components/HelperConnect';
import { ExportMenu, RegenerateDialog } from '../components/CaseTools';
import { Alert, Badge, Button, Card, Dialog, Drawer, EmptyState, Field, Input, MethodBadge, PageHeader, Select, Spinner, Textarea, cx, useToast } from '../components/ui';
import { JobBanner } from './UnitCases';
import { FlowJobProgress, usageText } from '../components/FlowProgress';
import { ApiOverview } from '../components/ApiOverview';

type Operations = FlowsOverview['operations'];
type Filter = 'all' | CaseStatus;

export const FLOW_TYPE: Record<string, string> = {
  happy_path: 'Happy path', alternate_path: 'Alternate path', negative: 'Negative', state_transition: 'State transition',
  role_based: 'Role based', end_to_end: 'End to end', data_integrity: 'Data integrity',
};

export function FlowCasesPage() {
  const flows = useFlows();
  const helper = useHelper();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [dialog, setDialog] = useState<'needs_changes' | 'reject' | 'confirm_approve' | 'confirm_redesign' | null>(null);
  const [connecting, setConnecting] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ['project', projectId] });
  const generate = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/flows/generate`),
    onSuccess: () => { setDialog(null); void refresh(); toast.success('Claude is analyzing your APIs on your computer.'); },
    onError: toast.error,
  });
  const resume = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/flows/continue`),
    onSuccess: () => { void refresh(); toast.success('Continuing the design on your computer. Finished areas are kept.'); },
    onError: toast.error,
  });
  const cancel = useMutation({ mutationFn: (jobId: string) => api.post(`/projects/${projectId}/jobs/${jobId}/cancel`), onSuccess: refresh, onError: toast.error });
  const review = useMutation({
    mutationFn: ({ action, comment = '' }: { action: string; comment?: string }) =>
      api.post<{ updated: number }>(`/projects/${projectId}/unit/cases/review`, { caseIds: [...selected], action, comment }),
    onSuccess: (r) => { setSelected(new Set()); setDialog(null); void refresh(); toast.success(`${plural(r.updated, 'flow')} updated.`); },
    onError: toast.error,
  });

  const all = flows.data?.flows ?? [];
  const query = search.trim().toLowerCase();
  const flowHit = useMemo(() => {
    const operations = flows.data?.operations ?? {};
    return (flow: FlowCase) => Boolean(query) && [flow.code, flow.title, FLOW_TYPE[flow.category] ?? flow.category,
      ...flow.content.steps.map((s) => `${operations[s.operationId]?.method ?? ''} ${operations[s.operationId]?.path ?? s.operationId}`)]
      .join('\n').toLowerCase().includes(query);
  }, [query, flows.data?.operations]);
  const visible = useMemo(() => all.filter((f) => (filter === 'all' || f.status === filter)
    && (!query || areaOf(f).toLowerCase().includes(query) || flowHit(f))), [all, filter, query, flowHit]);
  if (flows.isPending) return <Spinner />;
  const data = flows.data!;
  const running = jobActive(data.job?.status);
  const current = all.find((f) => f.id === open) ?? null;
  const allSelected = visible.length > 0 && visible.every((f) => selected.has(f.id));
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const unconfirmed = all.filter((f) => selected.has(f.id) && f.needsConfirmation).length;
  const hasOperations = Object.keys(data.operations).length > 0;

  return (
    <>
      <PageHeader title="Flow test cases"
        description="Claude studies all your APIs together, understands the business domain and designs end-to-end journeys with as many steps as each journey needs."
        action={hasOperations && (
          <div className="flex gap-2">
          {all.length > 0 && <ExportMenu module="flow" />}
          <Button variant={all.length ? 'secondary' : 'primary'} icon={<Sparkles className="size-4" />} loading={generate.isPending}
            disabled={!helper.data?.connected || running} title={!helper.data?.connected ? 'Connect your computer first' : undefined}
            onClick={() => (data.resume ? setDialog('confirm_redesign') : generate.mutate())}>{all.length ? 'Redesign flows' : 'Analyze APIs & design flows'}</Button>
          </div>
        )} />

      <div className="space-y-6">
        {!hasOperations && (
          <Card><EmptyState icon={<Workflow className="size-6" />} title="Upload an API spec first" description="Flows are designed from all operations of your OpenAPI or Swagger file."
            action={<Link to="../apis" className="text-sm font-medium text-brand-600 hover:underline">Go to APIs</Link>} /></Card>
        )}
        {hasOperations && !helper.data?.connected && (
          <Alert tone="info" title="Connect your computer to design flows" action={<Button size="sm" variant="secondary" onClick={() => setConnecting(true)}>Connect</Button>}>
            The analysis runs on your computer with your Claude account. You can still review existing flows.
          </Alert>
        )}
        {data.job && data.resume && !running ? (
          <Alert tone="warning" title={data.job.status === 'cancelled' ? 'The design was cancelled part-way' : 'The design stopped part-way'}
            action={<Button size="sm" icon={<Play className="size-4" />} loading={resume.isPending} disabled={!helper.data?.connected}
              title={!helper.data?.connected ? 'Connect your computer first' : undefined} onClick={() => resume.mutate()}>Continue generation</Button>}>
            <p>{data.job.error}</p>
            <p className="mt-1.5">
              <span className="font-semibold">{data.resume.doneGroups} of {data.resume.totalGroups} areas</span> are done and {plural(data.resume.flows, 'flow')} saved.
              {' '}Continue designs only the remaining {plural(Math.max(0, data.resume.totalGroups - data.resume.doneGroups), 'area')}, then checks coverage across all flows.
              {' '}Areas that were half-way through start again.
            </p>
            {usageText(data.job.usage) && <p className="mt-1.5 text-xs opacity-80">Used by the stopped run: {usageText(data.job.usage)}.</p>}
          </Alert>
        ) : data.job && (running && data.job.status === 'running' && data.job.progress.detail
          ? <FlowJobProgress job={data.job} onCancel={() => cancel.mutate(data.job!.id)} />
          : <JobBanner job={data.job} onCancel={() => cancel.mutate(data.job!.id)} usage={(job) => usageText(job.usage)} hint="Analysis, design, writing and review usually take 10–20 minutes. You can leave this page." />)}
        {data.analysis?.outdated && <Alert tone="warning" title="The API spec changed after these flows were designed">Redesign the flows to cover the new contract. Approved flows are kept.</Alert>}

        {hasOperations && !data.analysis && !running && (
          <Card><EmptyState icon={<Workflow className="size-6" />} title="No flows yet"
            description="Claude will map how your APIs depend on each other, describe the business domain, and design happy paths, state transitions, negative journeys and end-to-end processes. This takes a few minutes." /></Card>
        )}

        {data.analysis && (
          <>
            <ApiOverview analysis={data.analysis} operations={data.operations} flows={all} job={data.job} onOpenFlow={setOpen} />
            <ReviewCard analysis={data.analysis} />
          </>
        )}

        {all.length > 0 && (
          <div className="space-y-3">
          <Card className="sticky top-0 z-10">
            <div className="flex flex-wrap items-center gap-2 px-5 py-3">
              <label className="relative mr-1">
                <span className="sr-only">Search flows</span>
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
                <input type="search" value={search} onChange={(e) => { setSearch(e.target.value); setSelected(new Set()); }}
                  placeholder="Search areas, flows, TC codes, endpoints"
                  className="h-9 w-72 max-w-full rounded-lg border border-line-strong bg-surface pl-8 pr-3 text-sm text-ink outline-none focus:border-brand-600" />
              </label>
              {(['all', 'in_review', 'approved', 'needs_changes', 'rejected'] as Filter[]).map((value) => (
                <button key={value} onClick={() => { setFilter(value); setSelected(new Set()); }}
                  className={cx('h-8 cursor-pointer rounded-full border px-3 text-xs font-medium',
                    filter === value ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}>
                  {value === 'all' ? 'All' : STATUS_LABEL[value]} <span className="opacity-70">{value === 'all' ? all.length : data.totals[value] ?? 0}</span>
                </button>
              ))}
              <label className="ml-auto flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" className="size-4 accent-brand-600" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(visible.map((f) => f.id)))} /> Select all
              </label>
            </div>
            {selected.size > 0 && (
              <div className="flex flex-wrap items-center gap-2 rounded-b-xl border-t border-line bg-brand-50/50 px-5 py-2.5 text-sm">
                <span className="mr-2 font-medium text-ink">{plural(selected.size, 'flow')} selected</span>
                <Button size="sm" icon={<CircleCheck className="size-4" />} onClick={() => (unconfirmed ? setDialog('confirm_approve') : review.mutate({ action: 'approve' }))}>Approve</Button>
                <Button size="sm" variant="secondary" icon={<MessageSquareWarning className="size-4" />} onClick={() => setDialog('needs_changes')}>Needs changes</Button>
                <Button size="sm" variant="secondary" icon={<CircleX className="size-4" />} onClick={() => setDialog('reject')}>Reject</Button>
                <button className="ml-auto cursor-pointer text-sm text-muted hover:text-ink" onClick={() => setSelected(new Set())}>Clear</button>
              </div>
            )}
          </Card>
            {visible.length === 0 ? <Card><p className="px-5 py-10 text-center text-sm text-muted">{query ? `No areas or flows match “${search.trim()}”.` : 'No flows with this status.'}</p></Card> : (
              <FlowGroups flows={visible} all={all} domainAreas={data.analysis?.domain.areas ?? []} selected={selected} setSelected={setSelected}
                query={query} flowHit={flowHit}
                renderRow={(flow) => <FlowRow key={flow.id} flow={flow} grouped regenerating={data.regenerating.includes(flow.id)} operations={data.operations}
                  checked={selected.has(flow.id)} onToggle={() => toggle(flow.id)} onOpen={() => setOpen(flow.id)} />} />
            )}
          </div>
        )}
      </div>

      {current && <FlowDrawer flow={current} regenerating={data.regenerating.includes(current.id)} operations={data.operations} onClose={() => setOpen(null)} onChanged={refresh} />}
      {dialog === 'confirm_redesign' && data.resume && (
        <Dialog title="Start the design over?" onClose={() => setDialog(null)}
          description={`The last design stopped with ${data.resume.doneGroups} of ${data.resume.totalGroups} areas done. Continue generation keeps that work.`}
          footer={<><Button variant="secondary" onClick={() => setDialog(null)}>Keep my work</Button>
            <Button variant="secondary" loading={generate.isPending} onClick={() => generate.mutate()}>Start over</Button></>}>
          <p className="text-sm text-muted">Starting over analyzes the API again and replaces every flow that is not approved.</p>
        </Dialog>
      )}
      {dialog === 'confirm_approve' && (
        <Dialog title={`Approve ${plural(selected.size, 'flow')}?`} onClose={() => setDialog(null)}
          description={`${plural(unconfirmed, 'flow')} include results the spec does not state exactly. Approving confirms them.`}
          footer={<><Button variant="secondary" onClick={() => setDialog(null)}>Cancel</Button><Button loading={review.isPending} onClick={() => review.mutate({ action: 'approve' })}>Approve and confirm</Button></>}>
          <p className="text-sm text-muted">Open a flow to read its confirmation note first.</p>
        </Dialog>
      )}
      {(dialog === 'needs_changes' || dialog === 'reject') && (
        <ReviewDialog action={dialog} count={selected.size} loading={review.isPending} onClose={() => setDialog(null)} onSubmit={(comment) => review.mutate({ action: dialog, comment })} />
      )}
      {connecting && <HelperDialog onClose={() => setConnecting(false)} />}
    </>
  );
}

// --- Flows grouped by business area, then by test type ------------------------------------------

const TYPE_ORDER = ['happy_path', 'alternate_path', 'negative', 'state_transition', 'role_based', 'data_integrity', 'end_to_end'];
const TYPE_DOT: Record<string, string> = {
  happy_path: 'bg-emerald-600', alternate_path: 'bg-cyan-600', negative: 'bg-red-600', state_transition: 'bg-violet-600',
  role_based: 'bg-amber-600', data_integrity: 'bg-blue-600', end_to_end: 'bg-gray-900',
};
const JOURNEYS = 'Cross-area journeys';
const EXTRA = 'Additional coverage';

interface AreaGroup { name: string; description: string; flows: FlowCase[]; types: { type: string; flows: FlowCase[] }[] }

/** The area a flow is shown under; flows added to close coverage gaps have no area of their own. */
const areaOf = (flow: FlowCase) => (!flow.content.area || flow.content.area === 'Coverage gaps' ? EXTRA : flow.content.area);

/** Business areas in the domain analysis order, then cross-area journeys, then gap flows; each split by test type. */
export function groupFlows(flows: FlowCase[], domainAreas: { name: string; description: string }[]): AreaGroup[] {
  const known = new Map(domainAreas.map((a) => [a.name, a.description]));
  const names = [...new Set([...domainAreas.map((a) => a.name), ...flows.map(areaOf)])];
  const rank = (name: string) => (name === EXTRA ? 2 : name === JOURNEYS ? 1 : 0);
  names.sort((a, b) => rank(a) - rank(b));
  return names.map((name) => {
    const inArea = flows.filter((f) => areaOf(f) === name);
    const types = [...new Set([...TYPE_ORDER, ...inArea.map((f) => f.category)])]
      .map((type) => ({ type, flows: inArea.filter((f) => f.category === type) }))
      .filter((t) => t.flows.length);
    const description = known.get(name) ?? (name === JOURNEYS ? 'Journeys that span several business areas.'
      : name === EXTRA ? 'Flows added after the review to close coverage gaps.' : '');
    return { name, description, flows: inArea, types };
  }).filter((group) => group.flows.length);
}

function GroupCheckbox({ ids, selected, setSelected, label }: { ids: string[]; selected: Set<string>; setSelected: (s: Set<string>) => void; label: string }) {
  const count = ids.filter((id) => selected.has(id)).length;
  const all = count === ids.length;
  return (
    <input type="checkbox" aria-label={label} className="size-4 shrink-0 cursor-pointer accent-brand-600" checked={all}
      ref={(el) => { if (el) el.indeterminate = count > 0 && !all; }}
      onChange={() => { const next = new Set(selected); ids.forEach((id) => (all ? next.delete(id) : next.add(id))); setSelected(next); }} />
  );
}

function FlowGroups({ flows, all, domainAreas, selected, setSelected, renderRow, query, flowHit }: {
  flows: FlowCase[]; all: FlowCase[]; domainAreas: { name: string; description: string }[];
  selected: Set<string>; setSelected: (s: Set<string>) => void; renderRow: (flow: FlowCase) => React.ReactNode;
  query: string; flowHit: (flow: FlowCase) => boolean;
}) {
  // Areas and type groups start closed, so the page opens as a short list of business areas.
  const [openAreas, setOpenAreas] = useState<Set<string>>(new Set());
  const [openTypes, setOpenTypes] = useState<Set<string>>(new Set());
  const groups = groupFlows(flows, domainAreas);
  const flip = (set: Set<string>, key: string) => { const n = new Set(set); if (n.has(key)) n.delete(key); else n.add(key); return n; };
  const toggle = (name: string) => setOpenAreas((s) => flip(s, name));
  const typeKey = (area: string, type: string) => `${area}\u0000${type}`;
  // A search opens the areas it found; a type opens too when one of its flows matched (not just the area name).
  useEffect(() => {
    if (!query) { setOpenAreas(new Set()); setOpenTypes(new Set()); return; }
    setOpenAreas(new Set(groups.map((g) => g.name)));
    setOpenTypes(new Set(groups.flatMap((g) => g.types.filter((t) => t.flows.some(flowHit)).map((t) => typeKey(g.name, t.type)))));
  }, [query]);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end gap-4 px-1 text-xs">
        <button className="cursor-pointer py-1 font-medium text-brand-600 hover:underline"
          onClick={() => { setOpenAreas(new Set(groups.map((g) => g.name))); setOpenTypes(new Set(groups.flatMap((g) => g.types.map((t) => typeKey(g.name, t.type))))); }}>Expand all</button>
        <button className="cursor-pointer py-1 font-medium text-brand-600 hover:underline"
          onClick={() => { setOpenAreas(new Set()); setOpenTypes(new Set()); }}>Collapse all</button>
      </div>
      {groups.map((group) => {
        const open = openAreas.has(group.name);
        const inArea = all.filter((f) => areaOf(f) === group.name);
        const approved = inArea.filter((f) => f.status === 'approved').length;
        return (
          <section key={group.name} className={cx('rounded-2xl border bg-surface transition-shadow', open ? 'border-brand-500/40 shadow-sm' : 'border-line')}>
            <div className="flex items-start gap-3 rounded-2xl px-5 py-4 hover:bg-canvas/60">
              <span className="mt-1"><GroupCheckbox ids={group.flows.map((f) => f.id)} selected={selected} setSelected={setSelected} label={`Select all flows in ${group.name}`} /></span>
              <button onClick={() => toggle(group.name)} aria-expanded={open} className="flex min-w-0 flex-1 cursor-pointer items-start gap-2.5 text-left">
                <ChevronDown className={cx('mt-1 size-4 shrink-0 text-muted transition-transform', !open && '-rotate-90')} />
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="flex flex-wrap items-center gap-2.5">
                    <span className="text-base font-semibold text-ink">{group.name}</span>
                    <span className="inline-flex h-[22px] items-center rounded-full bg-brand-50 px-2 text-xs font-semibold text-brand-700">{plural(group.flows.length, 'flow')}</span>
                  </span>
                  {group.description && <span className="line-clamp-1 text-sm text-muted" title={group.description}>{group.description}</span>}
                  <span className="mt-0.5 flex flex-wrap gap-x-3.5 gap-y-1 text-xs text-ink-soft">
                    {group.types.map((t) => (
                      <span key={t.type} className="inline-flex items-center gap-1.5 whitespace-nowrap">
                        <span className={cx('size-[7px] rounded-full', TYPE_DOT[t.type] ?? 'bg-gray-400')} />
                        {FLOW_TYPE[t.type] ?? t.type} <span className="font-semibold">{t.flows.length}</span>
                      </span>
                    ))}
                  </span>
                </span>
                <span className="flex w-28 shrink-0 flex-col items-end gap-1.5 pt-0.5">
                  <span className="text-xl font-semibold leading-none text-ink tabular-nums">{approved}<span className="text-sm font-medium text-muted"> / {inArea.length}</span></span>
                  <span className="text-xs text-muted">approved</span>
                  <span className="block h-1.5 w-24 overflow-hidden rounded-full bg-gray-200">
                    <span className="block h-full rounded-full bg-emerald-600" style={{ width: `${inArea.length ? (100 * approved) / inArea.length : 0}%` }} />
                  </span>
                </span>
              </button>
            </div>
            {open && (
              <div className="flex flex-col gap-2 px-5 pb-5 pl-12">
                {group.types.map((t) => {
                  const key = typeKey(group.name, t.type);
                  const typeOpen = openTypes.has(key);
                  const label = FLOW_TYPE[t.type] ?? t.type;
                  const typeApproved = t.flows.filter((f) => f.status === 'approved').length;
                  return (
                    <div key={t.type} className="rounded-xl bg-canvas">
                      <div className="flex items-center gap-2.5 rounded-xl px-3.5 hover:bg-gray-100">
                        <GroupCheckbox ids={t.flows.map((f) => f.id)} selected={selected} setSelected={setSelected} label={`Select ${label} flows in ${group.name}`} />
                        <button onClick={() => setOpenTypes((s) => flip(s, key))} aria-expanded={typeOpen}
                          className="flex min-h-11 flex-1 cursor-pointer items-center gap-2 text-left">
                          <ChevronDown className={cx('size-3.5 shrink-0 text-muted transition-transform', !typeOpen && '-rotate-90')} />
                          <span className={cx('size-2 rounded-full', TYPE_DOT[t.type] ?? 'bg-gray-400')} />
                          <span className="text-sm font-semibold text-ink">{label}</span>
                          <span className="text-xs text-muted">{plural(t.flows.length, 'flow')}</span>
                          <span className="ml-auto text-xs text-muted">{typeApproved} of {t.flows.length} approved</span>
                        </button>
                      </div>
                      {typeOpen && (
                        <ul className="mx-2 mb-2 divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">{t.flows.map(renderRow)}</ul>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}

function FlowRow({ flow, grouped = false, regenerating, operations, checked, onToggle, onOpen }: { flow: FlowCase; grouped?: boolean; regenerating: boolean; operations: Operations; checked: boolean; onToggle: () => void; onOpen: () => void }) {
  const steps = flow.content.steps;
  const serious = flow.findings.filter((f) => f.severity !== 'minor').length;
  return (
    <li className="flex cursor-pointer items-start gap-4 px-5 py-3.5 hover:bg-canvas" onClick={onOpen}>
      <input type="checkbox" className="mt-1 size-4 cursor-pointer accent-brand-600" checked={checked} onClick={(e) => e.stopPropagation()} onChange={onToggle} aria-label={`Select ${flow.code}`} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs text-muted">{flow.code}</span>
          <span className="text-sm font-medium text-ink">{flow.title}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {steps.map((step, i) => (
            <span key={step.key} className="flex items-center gap-1">
              {i > 0 && <span className="text-faint">→</span>}
              <span className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">{operations[step.operationId]?.method ?? '?'} {shortPath(operations[step.operationId]?.path ?? step.operationId)}</span>
            </span>
          ))}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {!grouped && <Badge tone="purple">{FLOW_TYPE[flow.category] ?? flow.category}</Badge>}
          {!grouped && flow.content.area && <Badge tone="brand">{flow.content.area}</Badge>}
          <span className="text-xs text-muted">{plural(steps.length, 'step')}</span>
          {flow.needsConfirmation && <Badge tone="amber"><CircleHelp className="size-3" /> Confirm results</Badge>}
          {serious > 0 && <Badge tone="red">{plural(serious, 'review note')}</Badge>}
          {flow.outdated && <Badge tone="amber">Outdated</Badge>}
          {regenerating && <Badge tone="brand"><Sparkles className="size-3 animate-pulse" /> Regenerating…</Badge>}
          {flow.script === 'current' && <Badge tone="green">Scripted</Badge>}
          {flow.script === 'outdated' && <Badge tone="amber">Script needs update</Badge>}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5"><StatusBadge status={flow.status} /><PriorityBadge priority={flow.priority} /></div>
    </li>
  );
}

const shortPath = (path: string) => path.replace(/\{([^}]+)\}/g, ':$1');

function ReviewCard({ analysis }: { analysis: NonNullable<FlowsOverview['analysis']> }) {
  const [open, setOpen] = useState(false);
  const review = analysis.review;
  if (!review) return null;
  const plan = review.findings.filter((f) => f.flowKey === 'plan');
  return (
    <Card>
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className={cx('flex w-full cursor-pointer items-start gap-3 rounded-xl px-5 py-4 text-left hover:bg-canvas/60', open && 'rounded-b-none border-b border-line')}>
        <ChevronDown className={cx('mt-0.5 size-4 shrink-0 text-muted transition-transform', !open && '-rotate-90')} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-ink">AI reviewer</span>
          <span className="mt-0.5 block text-sm text-muted">
            A second AI agent reviewed the flows like a QA lead.{plan.length > 0 && ` ${plural(plan.length, 'suggested flow')}.`}{!open && ' Click to read the review.'}
          </span>
        </span>
        {review.verdict === 'ready' ? <Badge tone="green">Ready</Badge> : <Badge tone="amber">Needs attention</Badge>}
      </button>
      {open && <div className="space-y-3 px-5 py-4">
        <p className="text-sm leading-relaxed text-ink-soft">{review.summary}</p>
        {plan.length > 0 && (
          <div><p className="mb-1.5 text-sm font-medium text-ink">Suggested additional flows</p>
            <ul className="space-y-2">{plan.map((f, i) => <li key={i} className="text-sm text-muted"><span className="text-ink-soft">{f.issue}</span>{f.suggestion && <> — {f.suggestion}</>}</li>)}</ul></div>
        )}
      </div>}
    </Card>
  );
}

// --- Flow detail -------------------------------------------------------------------------------

function FlowDrawer({ flow, regenerating, operations, onClose, onChanged }: { flow: FlowCase; regenerating: boolean; operations: Operations; onClose: () => void; onChanged: () => void }) {
  const projectId = useProjectId();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<'needs_changes' | 'reject' | 'delete' | 'regenerate' | null>(null);
  const act = useMutation({
    mutationFn: ({ action, comment = '' }: { action: string; comment?: string }) =>
      api.post(`/projects/${projectId}/unit/cases/review`, { caseIds: [flow.id], action, comment }),
    onSuccess: () => { setDialog(null); onChanged(); },
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/unit/cases/${flow.id}`),
    onSuccess: () => { toast.success(`${flow.code} deleted.`); onChanged(); onClose(); },
    onError: toast.error,
  });
  const c = flow.content;
  const footer = editing ? undefined : (
    <>
      {flow.status !== 'approved' && <Button size="sm" icon={<CircleCheck className="size-4" />} onClick={() => act.mutate({ action: 'approve' })}>Approve</Button>}
      {flow.status !== 'needs_changes' && <Button size="sm" variant="secondary" icon={<MessageSquareWarning className="size-4" />} onClick={() => setDialog('needs_changes')}>Needs changes</Button>}
      {flow.status !== 'rejected' && <Button size="sm" variant="secondary" icon={<CircleX className="size-4" />} onClick={() => setDialog('reject')}>Reject</Button>}
      {flow.status !== 'in_review' && <Button size="sm" variant="ghost" icon={<RotateCcw className="size-4" />} onClick={() => act.mutate({ action: 'reopen' })}>Back to review</Button>}
      <div className="ml-auto flex gap-1">
        <Button size="sm" variant="ghost" icon={<Sparkles className="size-4" />} disabled={regenerating} onClick={() => setDialog('regenerate')}>Regenerate</Button>
        <Button size="sm" variant="ghost" icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>Edit</Button>
        <Button size="sm" variant="ghost" aria-label="Delete" onClick={() => setDialog('delete')}><Trash2 className="size-4" /></Button>
      </div>
    </>
  );
  return (
    <Drawer onClose={onClose} footer={footer}
      title={<div><p className="font-mono text-xs text-muted">{flow.code} · {flow.scenarioKey}</p><p className="mt-0.5 text-base font-semibold text-ink">{flow.title}</p></div>}
      subtitle={<div className="mt-1 flex flex-wrap gap-1.5"><StatusBadge status={flow.status} /><PriorityBadge priority={flow.priority} /><Badge tone="purple">{FLOW_TYPE[flow.category] ?? flow.category}</Badge><Badge>{plural(c.steps.length, 'step')}</Badge></div>}>
      {editing ? <FlowEditor flow={flow} onDone={() => setEditing(false)} onSaved={onChanged} /> : (
        <div className="space-y-6 px-6 py-5">
          {regenerating && <Alert tone="info" title="Claude is rewriting this flow">It updates here when it is done. Wait before editing.</Alert>}
          {flow.outdated && <Alert tone="warning" title="Outdated">The API spec changed after this flow was designed.</Alert>}
          {flow.reviewComment && <Alert tone={flow.status === 'rejected' ? 'error' : 'warning'} title={flow.status === 'rejected' ? 'Rejected' : 'Changes requested'}>{flow.reviewComment}</Alert>}
          {flow.needsConfirmation && <Alert tone="warning" title="Confirm the expected results">{c.confirmationNote || 'Some step results are not stated exactly by the contract.'} Approving confirms them.</Alert>}
          {flow.findings.length > 0 && (
            <div className="rounded-lg border border-line">
              <p className="border-b border-line px-4 py-2 text-sm font-medium text-ink">AI reviewer notes</p>
              <ul className="divide-y divide-line">{flow.findings.map((f, i) => (
                <li key={i} className="flex gap-3 px-4 py-2.5 text-sm"><Badge tone={f.severity === 'blocker' ? 'red' : f.severity === 'major' ? 'amber' : 'gray'} className="h-fit">{f.severity}</Badge>
                  <span className="text-ink-soft">{f.issue}{f.suggestion && <span className="block text-muted">Suggestion: {f.suggestion}</span>}</span></li>
              ))}</ul>
            </div>
          )}
          <section><h3 className="mb-1.5 text-sm font-semibold text-ink">Goal</h3><p className="text-sm leading-relaxed text-ink-soft">{c.objective || c.goal}</p></section>
          {c.preconditions.length > 0 && <section><h3 className="mb-1.5 text-sm font-semibold text-ink">Preconditions</h3><ol className="list-decimal space-y-1 pl-5 text-sm text-ink-soft">{c.preconditions.map((p, i) => <li key={i}>{p}</li>)}</ol></section>}
          <section>
            <h3 className="mb-3 text-sm font-semibold text-ink">Steps</h3>
            <ol>{c.steps.map((step, index) => <StepItem key={step.key} step={step} index={index} last={index === c.steps.length - 1} operations={operations} />)}</ol>
          </section>
          {c.cleanup.length > 0 && <section><h3 className="mb-1.5 text-sm font-semibold text-ink">Cleanup</h3><ol className="list-decimal space-y-1 pl-5 text-sm text-ink-soft">{c.cleanup.map((p, i) => <li key={i}>{p}</li>)}</ol></section>}
          {c.covers.length > 0 && <section><h3 className="mb-1.5 text-sm font-semibold text-ink">Covers</h3><div className="flex flex-wrap gap-1">{c.covers.map((id) => <code key={id} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">{id}</code>)}</div></section>}
        </div>
      )}
      {dialog === 'regenerate' && <RegenerateDialog caseId={flow.id} code={flow.code} reviewComment={flow.status === 'needs_changes' ? flow.reviewComment : ''} onClose={() => setDialog(null)} onStarted={onChanged} />}
      {(dialog === 'needs_changes' || dialog === 'reject') && <ReviewDialog action={dialog} count={1} loading={act.isPending} onClose={() => setDialog(null)} onSubmit={(comment) => act.mutate({ action: dialog, comment })} />}
      {dialog === 'delete' && (
        <Dialog title={`Delete ${flow.code}?`} description="This removes the flow for everyone in the project." onClose={() => setDialog(null)}
          footer={<><Button variant="secondary" onClick={() => setDialog(null)}>Cancel</Button><Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>Delete</Button></>}>
          <p className="text-sm text-ink-soft">{flow.title}</p>
        </Dialog>
      )}
    </Drawer>
  );
}

function StepItem({ step, index, last, operations }: { step: FlowCase['content']['steps'][number]; index: number; last: boolean; operations: Operations }) {
  const [open, setOpen] = useState(false);
  const op = operations[step.operationId];
  const uses = JSON.stringify(step.request).match(/\{\{steps\.(S\d+)\.([A-Za-z0-9_]+)\}\}/g) ?? [];
  const body = step.request.body;
  return (
    <li className="relative flex gap-4 pb-5">
      {!last && <span className="absolute left-[15px] top-8 h-[calc(100%-2rem)] w-px bg-line" />}
      <span className="z-10 flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-xs font-semibold text-ink-soft">{index + 1}</span>
      <div className="min-w-0 flex-1 rounded-lg border border-line p-3">
        <div className="flex flex-wrap items-center gap-2">
          <MethodBadge method={op?.method ?? '?'} /><span className="truncate font-mono text-[13px] text-ink">{op?.path ?? step.operationId}</span>
          <span className="ml-auto"><Badge tone={statusTone(step.expected.status)}>{step.expected.status ?? '—'}</Badge></span>
        </div>
        <p className="mt-1.5 text-sm text-ink-soft">{step.purpose}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[...new Set(uses)].map((u) => <span key={u} className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-0.5 text-xs text-blue-800"><ArrowDown className="size-3" />uses {u.replace(/[{}]/g, '').replace('steps.', '')}</span>)}
          {step.captures.map((cap) => <span key={cap.name} className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs text-emerald-800">saves {cap.name} = {cap.path}</span>)}
          {step.request.auth !== 'valid' && <Badge tone="purple">{AUTH_LABEL[step.request.auth]}</Badge>}
        </div>
        <button onClick={() => setOpen(!open)} className="mt-2 inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-brand-600 hover:underline">
          {open ? 'Hide' : 'Show'} request and checks <ChevronDown className={cx('size-3.5 transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <div className="mt-2 space-y-2 text-xs">
            {Object.keys(step.request.pathParams).length > 0 && <p className="font-mono text-ink-soft">path: {JSON.stringify(step.request.pathParams)}</p>}
            {Object.keys(step.request.query).length > 0 && <p className="font-mono text-ink-soft">query: {JSON.stringify(step.request.query)}</p>}
            {body !== null && body !== undefined && <pre className="overflow-auto rounded-md bg-gray-900 p-2.5 font-mono text-gray-100">{JSON.stringify(body, null, 2)}</pre>}
            {step.expected.bodyChecks.length > 0 && (
              <ul className="space-y-0.5">{step.expected.bodyChecks.map((ch, i) => <li key={i} className="font-mono text-ink-soft">✓ {ch.path} {ch.check.replaceAll('_', ' ')} {ch.value !== null && ch.value !== undefined ? JSON.stringify(ch.value) : ''}</li>)}</ul>
            )}
            {step.expected.notes && <p className="text-muted">{step.expected.notes}</p>}
          </div>
        )}
      </div>
    </li>
  );
}

function FlowEditor({ flow, onDone, onSaved }: { flow: FlowCase; onDone: () => void; onSaved: () => void }) {
  const projectId = useProjectId();
  const toast = useToast();
  const c = flow.content;
  const [form, setForm] = useState({ title: flow.title, objective: c.objective, type: flow.category, priority: flow.priority,
    preconditions: c.preconditions.join('\n'), steps: JSON.stringify(c.steps, null, 2), testData: c.testData, cleanup: c.cleanup.join('\n') });
  const [error, setError] = useState('');
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);
  const save = useMutation({
    mutationFn: () => {
      let steps: unknown;
      try { steps = JSON.parse(form.steps); } catch { throw new Error('Steps are not valid JSON.'); }
      return api.patch(`/projects/${projectId}/flows/${flow.id}`, { revision: flow.revision, title: form.title, objective: form.objective, type: form.type,
        priority: form.priority, preconditions: lines(form.preconditions), steps, testData: form.testData, cleanup: lines(form.cleanup) });
    },
    onSuccess: () => { toast.success(`${flow.code} saved and moved to review.`); onSaved(); onDone(); },
    onError: (e: Error) => setError(e.message),
  });
  return (
    <form className="space-y-5 px-6 py-5" onSubmit={(e) => { e.preventDefault(); setError(''); save.mutate(); }}>
      {flow.status === 'approved' && <Alert tone="info">Saving moves this approved flow back to review.</Alert>}
      <Field label="Title"><Input value={form.title} onChange={set('title')} required /></Field>
      <Field label="Goal"><Textarea rows={2} value={form.objective} onChange={set('objective')} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Type"><Select value={form.type} onChange={set('type')}>{Object.entries(FLOW_TYPE).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
        <Field label="Priority"><Select value={form.priority} onChange={set('priority')}>{Object.entries(PRIORITY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
      </div>
      <Field label="Preconditions" hint="One per line"><Textarea rows={3} value={form.preconditions} onChange={set('preconditions')} /></Field>
      <Field label="Steps (JSON)" hint="Add, remove or reorder steps. Use {{steps.S1.name}} to pass a captured value to a later step.">
        <Textarea rows={16} className="font-mono text-xs" value={form.steps} onChange={set('steps')} />
      </Field>
      <Field label="Test data"><Textarea rows={2} value={form.testData} onChange={set('testData')} /></Field>
      <Field label="Cleanup" hint="One step per line"><Textarea rows={2} value={form.cleanup} onChange={set('cleanup')} /></Field>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>Save changes</Button>
      </div>
    </form>
  );
}
