import { useMemo, useState, type ReactNode } from 'react';
import { ChevronDown, CircleAlert, CircleCheck, Search } from 'lucide-react';
import type { DomainModel, FlowCase, FlowGroupProgress, FlowsOverview, Job } from '../lib/api';
import { timeAgo } from '../lib/format';
import { Card, cx } from './ui';

type Analysis = NonNullable<FlowsOverview['analysis']>;
type Requirement = Analysis['requirements'][number];
type Operations = FlowsOverview['operations'];
type Category = 'operation' | 'dependency' | 'lifecycle' | 'business_rule' | 'locked_state' | 'side_effect';
type Tab = 'coverage' | 'areas' | 'lifecycles' | 'rules' | 'records';

const CATEGORIES: { key: Category; label: string; hint: string; filter: string }[] = [
  { key: 'operation', label: 'API operations used', hint: 'Each endpoint is called in a flow', filter: 'Operations' },
  { key: 'dependency', label: 'IDs passed between steps', hint: 'An ID from one call is used by a later call', filter: 'IDs' },
  { key: 'lifecycle', label: 'Status changes tested', hint: 'A record moves from one status to the next', filter: 'Status changes' },
  { key: 'business_rule', label: 'Business rules tested', hint: 'A rule from the spec is checked', filter: 'Rules' },
  { key: 'locked_state', label: 'Locked records refuse changes', hint: 'e.g. a signed consultation cannot be edited', filter: 'Locked states' },
  { key: 'side_effect', label: 'Side effects verified', hint: 'What else changes is read back', filter: 'Side effects' },
];
const RULE_KIND: Record<string, string> = {
  validation: 'Validation', uniqueness: 'Uniqueness', state: 'State', ownership: 'Ownership', role: 'Role', idempotency: 'Idempotency',
  concurrency: 'Concurrency', time: 'Time window', money: 'Money', side_effect: 'Side effect', external: 'External system', other: 'Other',
};
const KIND: Record<string, string> = {
  operation: 'Operation', dependency: 'ID hand-off', lifecycle: 'Status change', business_rule: 'Business rule',
  locked_state: 'Locked record', side_effect: 'Side effect',
};
const PAGE = 50;

/** "getLocationById" -> "get location by id". */
function humanize(operationId: string) {
  return operationId.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').toLowerCase();
}

function operationName(operationId: string, operations: Operations) {
  const summary = operations[operationId]?.summary?.trim().replace(/\.$/, '');
  return summary || capitalize(humanize(operationId));
}

function capitalize(text: string) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** A requirement in plain words, built from its id (older analyses store developer wording). */
export function requirementText(requirement: Requirement, operations: Operations): string {
  const [kind, ...rest] = requirement.id.split(':');
  if (kind === 'op') {
    const op = operations[rest.join(':')];
    if (!op) return requirement.description;
    return `${op.method} ${op.path}${op.summary ? ` · ${op.summary.trim().replace(/\.$/, '')}` : ''}`;
  }
  if (kind === 'dep' && rest.length >= 2) {
    const target = rest[rest.length - 1];
    const operation = rest.slice(0, -1).join(':');
    const field = target.split('.').pop() || target;
    return `${operationName(operation, operations)} uses the ${field} returned by an earlier step`;
  }
  if (kind === 'transition') {
    const match = requirement.id.match(/^transition:(.+?):(.*)->(.*)$/);
    const op = requirement.description.match(/\(([\w.-]+)\)\s*$/)?.[1];
    if (match) {
      const from = match[2] === '(none)' || !match[2] ? 'new' : match[2];
      return `${match[1]}: ${from} → ${match[3]}${op ? ` (${operationName(op, operations).toLowerCase()})` : ''}`;
    }
  }
  return requirement.description;
}

/** The usual path through an entity's statuses, and the statuses it can also end in. */
export function lifecycle(entity: DomainModel['entities'][number], transitions: DomainModel['transitions']) {
  const moves = transitions.filter((t) => t.entity === entity.name && t.fromState !== t.toState);
  const next = new Map<string, string[]>();
  for (const t of moves) next.set(t.fromState, [...(next.get(t.fromState) ?? []), t.toState]);
  const start = moves.find((t) => t.fromState === '(none)' || !t.fromState)?.toState ?? entity.states[0];
  let best: string[] = start ? [start] : [];
  const walk = (path: string[]) => {
    if (path.length > best.length) best = path;
    if (path.length > 20) return;
    for (const to of next.get(path[path.length - 1]) ?? []) if (!path.includes(to)) walk([...path, to]);
  };
  if (start && moves.length) walk([start]);
  const all = [...new Set([...entity.states, ...moves.map((t) => t.toState)])].filter((s) => s && s !== '(none)');
  return { path: moves.length ? best : [], others: all.filter((s) => !(moves.length ? best : []).includes(s)), hasMoves: moves.length > 0 };
}

function StatePill({ state, muted }: { state: string; muted?: boolean }) {
  return <span className={cx('rounded-full px-2 py-0.5 text-xs font-medium', muted ? 'bg-gray-100 text-ink-soft' : 'bg-brand-50 text-brand-700')}>{state}</span>;
}

function Lifecycle({ entity, domain }: { entity: DomainModel['entities'][number]; domain: DomainModel }) {
  const { path, others, hasMoves } = lifecycle(entity, domain.transitions);
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
      <span className="w-44 shrink-0 pt-0.5 text-sm font-semibold text-ink">{entity.name}</span>
      <div className="flex flex-wrap items-center gap-1.5">
        {hasMoves ? (
          <>
            {path.map((state, i) => (
              <span key={state} className="flex items-center gap-1.5">
                {i > 0 && <span className="text-xs text-muted" aria-hidden="true">›</span>}
                <StatePill state={state} />
              </span>
            ))}
            {others.length > 0 && <span className="ml-2 text-xs text-ink-soft">can also be</span>}
          </>
        ) : <span className="text-xs text-ink-soft">Statuses:</span>}
        {(hasMoves ? others : others.length ? others : entity.states).map((state) => <StatePill key={state} state={state} muted />)}
      </div>
    </div>
  );
}

function entitiesOfArea(domain: DomainModel, operations: string[]) {
  const ops = new Set(operations);
  return domain.entities
    .map((e) => ({ name: e.name, hits: e.operations.filter((o) => ops.has(o)).length }))
    .filter((e) => e.hits > 0)
    .sort((a, b) => b.hits - a.hits)
    .slice(0, 3)
    .map((e) => e.name);
}

function Tile({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div className="rounded-xl border border-line px-4 py-3">
      <p className="text-xl font-bold text-ink">{value}</p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  );
}

function Bar({ covered, total }: { covered: number; total: number }) {
  const percent = total ? Math.round((100 * covered) / total) : 100;
  return (
    <div className="h-2 overflow-hidden rounded-full bg-gray-200">
      <div className={cx('h-full rounded-full transition-all duration-500', covered === total ? 'bg-emerald-600' : 'bg-brand-600')} style={{ width: `${Math.max(covered ? 2 : 0, percent)}%` }} />
    </div>
  );
}

function useCoverage(analysis: Analysis) {
  return useMemo(() => CATEGORIES.map((c) => {
    const items = analysis.requirements.filter((r) => r.category === c.key);
    return { ...c, total: items.length, covered: items.filter((r) => r.covered).length };
  }).filter((c) => c.total > 0), [analysis]);
}

// --- Shared sections -----------------------------------------------------------------------------

function Areas({ domain, flows, groups }: { domain: DomainModel; flows: FlowCase[]; groups?: FlowGroupProgress[] }) {
  const [all, setAll] = useState(false);
  const areas = domain.areas ?? [];
  const byGroup = new Map(groups?.map((g) => [g.name, g]));
  const shown = all ? areas : areas.slice(0, 8);
  const status = (name: string): [string, string] => {
    const group = byGroup.get(name);
    const count = flows.filter((f) => f.content.area === name).length;
    if (group?.status === 'working') return [capitalize(group.step) || 'Designing flows', 'text-brand-700 font-semibold'];
    if (group?.status === 'waiting') return ['Not designed yet', 'text-muted'];
    if (group?.status === 'failed') return ['Design failed', 'text-red-700 font-semibold'];
    if (group?.status === 'done' || count) return [`${group?.flows ?? count} flows saved`, 'text-emerald-700 font-semibold'];
    return groups ? ['Not designed yet', 'text-muted'] : ['No flows', 'text-muted'];
  };
  if (!areas.length) return null;
  return (
    <div>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {shown.map((area) => {
          const [text, tone] = status(area.name);
          const entities = entitiesOfArea(domain, area.operations);
          return (
            <div key={area.name} className="flex flex-col gap-1 rounded-xl border border-line px-3.5 py-3" title={area.description}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-ink">{area.name}</p>
                <span className="shrink-0 text-xs text-muted">{area.operations.length} ops</span>
              </div>
              {entities.length > 0 && <p className="text-xs text-muted">{entities.join(', ')}</p>}
              <p className={cx('text-xs', tone)}>{text}</p>
            </div>
          );
        })}
      </div>
      {areas.length > 8 && (
        <button onClick={() => setAll(!all)} className="mt-2.5 cursor-pointer text-sm font-medium text-brand-600 hover:underline">
          {all ? 'Show fewer areas' : `Show all ${areas.length} areas`}
        </button>
      )}
    </div>
  );
}

function Lifecycles({ domain, limit }: { domain: DomainModel; limit?: number }) {
  const [all, setAll] = useState(false);
  const entities = domain.entities
    .filter((e) => e.states.length > 1 || domain.transitions.some((t) => t.entity === e.name))
    .sort((a, b) => domain.transitions.filter((t) => t.entity === b.name).length - domain.transitions.filter((t) => t.entity === a.name).length);
  const shown = limit && !all ? entities.slice(0, limit) : entities;
  if (!entities.length) return <p className="text-sm text-muted">No status lifecycles were found in this API.</p>;
  return (
    <div className="space-y-3">
      {shown.map((entity) => <Lifecycle key={entity.name} entity={entity} domain={domain} />)}
      {limit && entities.length > limit && (
        <button onClick={() => setAll(!all)} className="cursor-pointer text-sm font-medium text-brand-600 hover:underline">
          {all ? 'Show fewer' : `Show all ${entities.length} lifecycles`}
        </button>
      )}
    </div>
  );
}

// --- Coverage (finished) -------------------------------------------------------------------------

function CoverageTab({ analysis, operations, flows, onOpenFlow }: { analysis: Analysis; operations: Operations; flows: FlowCase[]; onOpenFlow: (id: string) => void }) {
  const categories = useCoverage(analysis);
  const [filter, setFilter] = useState<'all' | 'missing' | Category>('all');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const coveredBy = useMemo(() => {
    const map = new Map<string, FlowCase[]>();
    for (const flow of flows) for (const id of flow.content.covers ?? []) map.set(id, [...(map.get(id) ?? []), flow]);
    return map;
  }, [flows]);
  const rows = useMemo(() => analysis.requirements.map((r) => ({ ...r, text: requirementText(r, operations) })), [analysis, operations]);
  const missing = rows.filter((r) => !r.covered);
  const needle = query.trim().toLowerCase();
  const visible = rows.filter((r) => (filter === 'all' || (filter === 'missing' ? !r.covered : r.category === filter))
    && (!needle || r.text.toLowerCase().includes(needle)));
  const chip = (value: typeof filter, label: string) => (
    <button key={value} onClick={() => { setFilter(value); setLimit(PAGE); }}
      className={cx('h-8 cursor-pointer rounded-full border px-3 text-xs font-medium',
        filter === value ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}>{label}</button>
  );
  return (
    <div className="space-y-5">
      {missing.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3.5">
          <p className="text-sm font-semibold text-amber-900">{missing.length === 1 ? '1 thing no flow tests yet' : `${missing.length} things no flow tests yet`}</p>
          <ul className="mt-2 space-y-1.5">
            {missing.slice(0, 6).map((r) => (
              <li key={r.id} className="flex items-baseline gap-2.5 text-sm text-ink-soft">
                <span className="shrink-0 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-900">{KIND[r.category] ?? r.category}</span>
                {r.text}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-sm text-ink-soft">
            {missing.length > 6 && <><button onClick={() => setFilter('missing')} className="cursor-pointer font-medium text-brand-700 hover:underline">See all {missing.length}</button> · </>}
            Use <span className="font-semibold">Redesign flows</span> to close them.
          </p>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {categories.map((c) => (
          <button key={c.key} onClick={() => setFilter(c.key)} className="cursor-pointer rounded-xl border border-line px-4 py-3 text-left hover:bg-canvas">
            <p className="text-sm font-semibold text-ink">{c.label}</p>
            <p className="mb-2 mt-1 text-lg font-bold tabular-nums text-ink">{c.covered} / {c.total}</p>
            <Bar covered={c.covered} total={c.total} />
          </button>
        ))}
      </div>
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label className="relative">
            <span className="sr-only">Search requirements</span>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input value={query} onChange={(e) => { setQuery(e.target.value); setLimit(PAGE); }} placeholder="Search, e.g. appointment"
              className="h-9 w-64 rounded-lg border border-line-strong bg-surface pl-8 pr-3 text-sm text-ink outline-none focus:border-brand-600" />
          </label>
          {chip('all', 'All')}
          {missing.length > 0 && chip('missing', `Not covered · ${missing.length}`)}
          {categories.map((c) => chip(c.key, c.filter))}
        </div>
        {visible.length === 0 ? <p className="rounded-xl border border-line px-4 py-8 text-center text-sm text-muted">Nothing matches.</p> : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
            {visible.slice(0, limit).map((r) => {
              const by = coveredBy.get(r.id) ?? [];
              return (
                <li key={r.id} className="flex flex-col gap-1.5 px-4 py-2.5 text-sm sm:flex-row sm:items-center sm:gap-3">
                  <span className="flex items-center gap-2.5 sm:min-w-0 sm:flex-1">
                    {r.covered ? <CircleCheck className="size-4 shrink-0 text-emerald-600" aria-label="Covered" /> : <CircleAlert className="size-4 shrink-0 text-amber-600" aria-label="Not covered" />}
                    <span className="w-28 shrink-0 text-xs text-muted">{KIND[r.category] ?? r.category}</span>
                    <span className="min-w-0 text-ink">{r.text}</span>
                  </span>
                  <span className="flex flex-wrap gap-1 pl-[26px] sm:justify-end sm:pl-0">
                    {by.slice(0, 4).map((f) => (
                      <button key={f.id} onClick={() => onOpenFlow(f.id)} title={f.title}
                        className="cursor-pointer rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 hover:bg-brand-100">{f.code}</button>
                    ))}
                    {by.length > 4 && <span className="px-1 text-xs text-muted">+{by.length - 4}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-2 text-sm text-muted">
          Showing {Math.min(limit, visible.length)} of {visible.length}
          {visible.length > limit && <> · <button onClick={() => setLimit(limit + PAGE)} className="cursor-pointer font-medium text-brand-600 hover:underline">Show more</button></>}
        </p>
      </div>
    </div>
  );
}

function RulesTab({ analysis, flows, onOpenFlow }: { analysis: Analysis; flows: FlowCase[]; onOpenFlow: (id: string) => void }) {
  const { domain } = analysis;
  const covered = new Map(analysis.requirements.map((r) => [r.id, r.covered]));
  return (
    <div className="space-y-5">
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line">
        {domain.businessRules.map((rule) => {
          const id = `rule:${rule.key}`;
          const by = flows.filter((f) => f.content.covers?.includes(id));
          return (
            <li key={rule.key} className="flex flex-col gap-1.5 px-4 py-2.5 text-sm sm:flex-row sm:items-center sm:gap-3">
              <span className="flex items-start gap-2.5 sm:flex-1">
                {covered.get(id) ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" aria-label="Covered" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" aria-label="Not covered" />}
                <span className="text-ink">
                  {rule.kind && rule.kind !== 'other' && <span className="mr-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-ink-soft">{RULE_KIND[rule.kind] ?? rule.kind}</span>}
                  {rule.rule}
                  {rule.needsSupport && <span className="mt-0.5 block text-xs text-amber-800">Needs test support: {rule.needsSupport}</span>}
                </span>
              </span>
              <span className="flex flex-wrap gap-1 pl-[26px] sm:pl-0">
                {by.slice(0, 4).map((f) => (
                  <button key={f.id} onClick={() => onOpenFlow(f.id)} title={f.title}
                    className="cursor-pointer rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 hover:bg-brand-100">{f.code}</button>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
      {domain.assumptions.length > 0 && (
        <div className="rounded-xl border border-line px-4 py-3.5">
          <p className="text-sm font-semibold text-ink">Assumptions to check with the API owner</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-soft">{domain.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

function RecordsTab({ domain }: { domain: DomainModel }) {
  return (
    <div className="space-y-5">
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {domain.entities.map((e) => (
          <div key={e.name} className="rounded-xl border border-line px-3.5 py-3">
            <p className="text-sm font-semibold text-ink">{e.name}</p>
            {e.description && <p className="mt-0.5 text-xs leading-relaxed text-muted">{e.description}</p>}
            {e.states.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{e.states.map((s) => <StatePill key={s} state={s} muted />)}</div>}
            {(e.lockedStates?.length ?? 0) > 0 && <p className="mt-1.5 text-xs text-muted">Can't be changed when {e.lockedStates!.join(', ')}</p>}
          </div>
        ))}
      </div>
      {(domain.sideEffects?.length ?? 0) > 0 && (
        <div className="rounded-xl border border-line px-4 py-3.5">
          <p className="text-sm font-semibold text-ink">What else changes</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-soft">
            {domain.sideEffects!.map((s, i) => <li key={i}><span className="font-mono text-xs">{s.operationId}</span>: {s.effect}{s.verifyWith && <span className="text-muted"> (seen with {s.verifyWith})</span>}</li>)}
          </ul>
        </div>
      )}
      {domain.relationships.length > 0 && (
        <div className="rounded-xl border border-line px-4 py-3.5">
          <p className="text-sm font-semibold text-ink">How records relate</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-soft">{domain.relationships.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

// --- The card ------------------------------------------------------------------------------------

/** "How your API works" and its coverage: area-first while flows are generated, tabs once they are done. */
export function ApiOverview({ analysis, operations, flows, job, onOpenFlow }:
  { analysis: Analysis; operations: Operations; flows: FlowCase[]; job: Job | null; onOpenFlow: (id: string) => void }) {
  const [tab, setTab] = useState<Tab>('coverage');
  const [fullSummary, setFullSummary] = useState(false);
  const [open, setOpen] = useState(false);
  const categories = useCoverage(analysis);
  const { domain } = analysis;
  const generating = job?.status === 'running' || job?.status === 'queued';
  const groups = generating ? job?.progress.detail?.groups : undefined;
  const areas = domain.areas ?? [];
  const lifecycles = domain.entities.filter((e) => e.states.length > 1 || domain.transitions.some((t) => t.entity === e.name)).length;
  const percent = analysis.total ? Math.round((100 * analysis.covered) / analysis.total) : 100;
  const finishedAreas = groups?.filter((g) => g.status === 'done' || g.status === 'failed').length ?? 0;
  const longSummary = domain.summary.length > 320;

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        <h2 className="text-base font-semibold text-ink">How your API works</h2>
        <p className="mt-0.5 text-xs text-muted">Claude's understanding of the API · {timeAgo(analysis.generatedAt)}{analysis.generatedBy ? ` by ${analysis.generatedBy}` : ''}</p>
        <p className="mt-3 text-sm leading-relaxed text-ink-soft">
          {longSummary && !fullSummary ? `${domain.summary.slice(0, 300).replace(/\s+\S*$/, '')}… ` : `${domain.summary} `}
          {longSummary && <button onClick={() => setFullSummary(!fullSummary)} className="cursor-pointer font-medium text-brand-600 hover:underline">{fullSummary ? 'Show less' : 'Read more'}</button>}
        </p>
      </div>
      {!generating && (
        <div className="text-right">
          <p className={cx('text-3xl font-bold tabular-nums', analysis.covered === analysis.total ? 'text-emerald-700' : 'text-ink')}>{percent}%</p>
          <p className="text-xs text-muted">covered · {analysis.covered} of {analysis.total}</p>
        </div>
      )}
    </div>
  );

  if (generating) {
    return (
      <div className="space-y-6">
        <Card className="space-y-6 p-5 sm:p-6">
          {header}
          <div className="grid gap-3 sm:grid-cols-4">
            <Tile value={areas.length || '–'} label="business areas" />
            <Tile value={Object.keys(operations).length} label="operations" />
            <Tile value={domain.entities.length} label="records (entities)" />
            <Tile value={domain.businessRules.length} label="business rules" />
          </div>
          <section>
            <h3 className="mb-2.5 text-sm font-semibold text-ink">Business areas</h3>
            <Areas domain={domain} flows={flows} groups={groups} />
          </section>
          <section>
            <h3 className="mb-2.5 text-sm font-semibold text-ink">How records change status</h3>
            <Lifecycles domain={domain} limit={3} />
          </section>
        </Card>
        <Card className="space-y-4 p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-ink">Coverage</h2>
              <p className="mt-0.5 text-sm text-muted">Does every part of the API appear in at least one flow?</p>
            </div>
            <span className="rounded-full bg-brand-100 px-2.5 py-1 text-xs font-semibold text-brand-700">
              Updating{groups?.length ? ` · ${finishedAreas} of ${groups.length} areas designed` : ''}
            </span>
          </div>
          <p className="rounded-lg border border-brand-100 bg-brand-50/50 px-4 py-3 text-sm text-ink-soft">
            Coverage fills in as each area is saved. Gaps are listed once all areas are done, so nothing here is a problem yet.
          </p>
          <ul className="divide-y divide-line">
            {categories.map((c) => (
              <li key={c.key} className="grid grid-cols-1 gap-2 py-3 sm:grid-cols-[240px_minmax(0,1fr)_90px] sm:items-center sm:gap-4">
                <span>
                  <span className="block text-sm font-medium text-ink">{c.label}</span>
                  <span className="text-xs text-muted">{c.hint}</span>
                </span>
                <Bar covered={c.covered} total={c.total} />
                <span className="text-sm font-semibold tabular-nums text-ink sm:text-right">{c.covered} / {c.total}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    );
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'coverage', label: `Coverage · ${percent}%` },
    ...(areas.length ? [{ key: 'areas' as Tab, label: `Business areas · ${areas.length}` }] : []),
    { key: 'lifecycles', label: `Status lifecycles · ${lifecycles}` },
    { key: 'rules', label: `Business rules · ${domain.businessRules.length}` },
    { key: 'records', label: `Records · ${domain.entities.length}` },
  ];
  const counts = [areas.length && `${areas.length} business areas`, `${lifecycles} status lifecycles`,
    `${domain.businessRules.length} business rules`, `${domain.entities.length} records`].filter(Boolean).join(' · ');
  return (
    <Card className="overflow-hidden">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className={cx('flex w-full cursor-pointer items-start gap-3 px-5 py-4 text-left hover:bg-canvas/60 sm:px-6', open && 'border-b border-line')}>
        <ChevronDown className={cx('mt-0.5 size-4 shrink-0 text-muted transition-transform', !open && '-rotate-90')} />
        <span className="min-w-0 flex-1">
          <span className="block text-base font-semibold text-ink">API analysis & coverage</span>
          <span className="mt-0.5 block text-sm text-muted">
            How the AI understood your API, and how much of it the flows test · {timeAgo(analysis.generatedAt)}{analysis.generatedBy ? ` by ${analysis.generatedBy}` : ''}
          </span>
          {!open && <span className="mt-1.5 block text-xs text-ink-soft">{counts}</span>}
        </span>
        <span className="shrink-0 text-right">
          <span className={cx('block text-2xl font-bold leading-tight tabular-nums', analysis.covered === analysis.total ? 'text-emerald-700' : 'text-ink')}>{percent}%</span>
          <span className="block text-xs text-muted">covered · {analysis.covered} of {analysis.total}</span>
        </span>
      </button>
      {open && <>
      <div className="px-5 pt-5 sm:px-6">
        <h2 className="text-sm font-semibold text-ink">How your API works</h2>
        <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-ink-soft">
          {longSummary && !fullSummary ? `${domain.summary.slice(0, 300).replace(/\s+\S*$/, '')}… ` : `${domain.summary} `}
          {longSummary && <button onClick={() => setFullSummary(!fullSummary)} className="cursor-pointer font-medium text-brand-600 hover:underline">{fullSummary ? 'Show less' : 'Read more'}</button>}
        </p>
        <div role="tablist" className="mt-5 flex gap-1 overflow-x-auto border-b border-line">
          {tabs.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
              className={cx('-mb-px shrink-0 cursor-pointer whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm',
                tab === t.key ? 'border-brand-600 font-semibold text-brand-700' : 'border-transparent font-medium text-ink-soft hover:text-ink')}>
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="p-5 sm:p-6" role="tabpanel">
        {tab === 'coverage' && <CoverageTab analysis={analysis} operations={operations} flows={flows} onOpenFlow={onOpenFlow} />}
        {tab === 'areas' && <Areas domain={domain} flows={flows} />}
        {tab === 'lifecycles' && <Lifecycles domain={domain} />}
        {tab === 'rules' && <RulesTab analysis={analysis} flows={flows} onOpenFlow={onOpenFlow} />}
        {tab === 'records' && <RecordsTab domain={domain} />}
      </div>
      </>}
    </Card>
  );
}
