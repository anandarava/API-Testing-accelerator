import { useEffect, useState } from 'react';
import { Check, ChevronDown, LoaderCircle } from 'lucide-react';
import type { FlowGroupProgress, FlowProgress, Job, JobUsage } from '../lib/api';
import { describeModels, modelLabel } from './ModelPicker';
import { Button, Card, cx } from './ui';

const STAGES = ['analyze', 'design', 'coverage', 'done'] as const;
// How far through its own pipeline a working area is, by the step the helper reports.
const STEP_WEIGHT: [string, number][] = [['final review', 0.9], ['fixing', 0.8], ['reviewing', 0.7], ['writing', 0.4], ['designing', 0.05]];
const DETAILS_KEY = 'flowProgress.details';

function useNow(intervalMs = 10_000) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** 42 -> "<1 min", 300 -> "5 min", 3900 -> "1 h 5 min". */
export function duration(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (minutes < 1) return '<1 min';
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function compactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`;
  return String(value);
}

/** "1.2M tokens sent (64% from cache) · 38 Claude calls". */
export function usageText(usage?: JobUsage | null): string {
  if (!usage?.calls) return '';
  const sent = usage.inputTokens + usage.cacheReadTokens + usage.cacheWriteTokens;
  const cached = sent ? Math.round((100 * usage.cacheReadTokens) / sent) : 0;
  return `${compactNumber(sent)} tokens sent${cached ? ` (${cached}% from cache)` : ''} · ${usage.calls} Claude call${usage.calls === 1 ? '' : 's'}`;
}

function stepWeight(step: string) {
  return STEP_WEIGHT.find(([word]) => step.toLowerCase().includes(word))?.[1] ?? 0.05;
}

function capitalize(text: string) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

function stageDetail(stage: (typeof STAGES)[number], detail: FlowProgress, state: 'done' | 'active' | 'todo'): string {
  const groups = detail.groups;
  const finished = groups.filter((g) => g.status === 'done' || g.status === 'failed').length;
  switch (stage) {
    case 'analyze':
      return state === 'done' ? `${detail.entities ?? 0} entities · ${detail.rules ?? 0} rules · ${detail.areas ?? 0} areas` : `Reading ${detail.operations} operations`;
    case 'design':
      if (state === 'todo') return 'Each area: design, write, review, fix';
      return state === 'active' ? `${finished} of ${groups.length} areas done` : `${groups.reduce((n, g) => n + (g.status === 'done' ? g.flows : 0), 0)} flows saved`;
    case 'coverage':
      if (state === 'todo') return 'Fills any gaps it finds';
      if (state === 'active') return detail.gapFlows ? `Writing ${detail.gapFlows} flows for gaps` : 'Checking every requirement';
      return detail.gapFlows ? `${detail.gapFlows} gap flows added` : 'No gaps found';
    default:
      return 'You review and approve the flows';
  }
}

const TITLES: Record<(typeof STAGES)[number], string> = {
  analyze: 'Understand the API', design: 'Design & write flows', coverage: 'Check coverage', done: 'Ready for review',
};

function Stepper({ detail, now }: { detail: FlowProgress; now: number }) {
  const current = STAGES.indexOf(detail.stage);
  return (
    <ol className="grid gap-4 sm:grid-cols-4 sm:gap-3">
      {STAGES.map((stage, index) => {
        const state = index < current || detail.stage === 'done' ? 'done' : index === current ? 'active' : 'todo';
        const started = detail.stageStartedAt[stage];
        const ended = detail.stageStartedAt[STAGES[index + 1]];
        const time = started && stage !== 'done' ? duration((ended ?? now) - started) : '';
        return (
          <li key={stage} className="flex flex-col gap-2" aria-current={state === 'active' ? 'step' : undefined}>
            <span className={cx('h-1 rounded-full', state === 'done' ? 'bg-emerald-600' : state === 'active' ? 'bg-brand-600' : 'bg-gray-200')} />
            <span className="flex items-center gap-2.5">
              <span className={cx('flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                state === 'done' && 'bg-emerald-600 text-white',
                state === 'active' && 'bg-brand-600 text-white ring-4 ring-brand-100',
                state === 'todo' && 'border-2 border-gray-300 text-muted')}>
                {state === 'done' ? <Check className="size-4" /> : index + 1}
              </span>
              <span className={cx('text-sm font-semibold', state === 'active' ? 'text-brand-700' : state === 'done' ? 'text-ink' : 'text-muted')}>{TITLES[stage]}</span>
            </span>
            <span className="pl-[38px] text-xs text-muted">
              {stageDetail(stage, detail, state)}{time && state !== 'todo' ? ` · ${time}` : ''}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function CurrentStep({ detail }: { detail: FlowProgress }) {
  if (detail.stage === 'analyze') {
    return (
      <p className="flex items-center gap-2 text-sm text-ink-soft">
        <LoaderCircle className="size-4 animate-spin text-brand-600" />
        Claude is reading all {detail.operations} operations to learn the entities, business rules and areas of your API.
      </p>
    );
  }
  if (detail.stage === 'coverage') {
    return (
      <p className="flex items-center gap-2 text-sm text-ink-soft">
        <LoaderCircle className="size-4 animate-spin text-brand-600" />
        {detail.gapFlows ? `Writing and reviewing ${detail.gapFlows} extra flows so every requirement is covered.` : 'Checking that the flows from all areas together cover every requirement.'}
      </p>
    );
  }
  const groups = detail.groups;
  const finished = groups.filter((g) => g.status === 'done' || g.status === 'failed').length;
  const working = groups.filter((g) => g.status === 'working');
  const progress = groups.length ? (finished + working.reduce((sum, g) => sum + stepWeight(g.step), 0)) / groups.length : 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-ink">Designing and writing flows · {finished} of {groups.length} areas done</p>
        <p className="text-xs text-muted">Up to {detail.parallel} areas at a time</p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-brand-100">
        <div className="h-full rounded-full bg-brand-600 transition-all duration-500" style={{ width: `${Math.max(3, Math.round(progress * 100))}%` }} />
      </div>
      {working.length > 0 && (
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {working.map((group) => (
            <li key={group.name} className="rounded-lg border border-line bg-surface px-3 py-2">
              <p className="truncate text-sm font-medium text-ink" title={group.name}>{group.name}</p>
              <p className="mt-0.5 truncate text-xs text-brand-700">{capitalize(group.step)}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function rowText(group: FlowGroupProgress) {
  if (group.status === 'waiting') return 'Waiting for a free slot';
  if (group.status === 'done') return 'Saved';
  return capitalize(group.step) || (group.status === 'failed' ? 'Failed' : 'Working');
}

function rowFlows(group: FlowGroupProgress) {
  if (group.status === 'done') return `${group.flows} saved`;
  if (group.status === 'working' && group.flows) return `${group.flows} written`;
  return '–';
}

const DOT: Record<FlowGroupProgress['status'], string> = {
  working: 'bg-brand-600', done: 'bg-emerald-600', waiting: 'bg-gray-400', failed: 'bg-red-600',
};

function AreaTable({ groups, now }: { groups: FlowGroupProgress[]; now: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="bg-canvas text-left text-xs font-semibold text-muted">
          <tr>
            <th className="px-5 py-2 font-semibold">Area</th>
            <th className="px-3 py-2 font-semibold">Now</th>
            <th className="px-3 py-2 font-semibold">Flows</th>
            <th className="px-5 py-2 text-right font-semibold">Time</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.name} className="border-t border-line">
              <td className="px-5 py-2.5 font-medium text-ink">{group.name}</td>
              <td className="px-3 py-2.5 text-ink-soft">
                <span className="flex items-center gap-2"><span className={cx('size-2 shrink-0 rounded-full', DOT[group.status])} />{rowText(group)}</span>
              </td>
              <td className="px-3 py-2.5 text-ink-soft">{rowFlows(group)}</td>
              <td className="px-5 py-2.5 text-right tabular-nums text-muted">
                {group.startedAt ? duration((group.finishedAt ?? now) - group.startedAt) : '–'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function readDetailsOpen() {
  try {
    return localStorage.getItem(DETAILS_KEY) === 'open';
  } catch {
    return false;
  }
}

/** Live progress of a running flow generation: a 4-step stepper, what is happening now, and an area table. */
export function FlowJobProgress({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const detail = job.progress.detail!;
  const now = useNow();
  const [open, setOpen] = useState(readDetailsOpen);
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem(DETAILS_KEY, open ? 'closed' : 'open');
    } catch {
      /* the choice is only remembered when storage is available */
    }
  };
  const step = Math.min(STAGES.indexOf(detail.stage) + 1, 4);
  const model = job.models.length ? describeModels(job.models) : job.model && job.model !== 'default' ? modelLabel(job.model) : '';
  const started = job.startedAt ?? job.createdAt;
  return (
    <Card className="overflow-hidden">
      <div className="space-y-6 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 text-base font-semibold text-ink">
              <span className="rounded-full bg-brand-100 px-2.5 py-0.5 text-xs font-semibold text-brand-700">Step {step} of 4</span>
              Generating flow test cases
            </p>
            <p className="mt-1 text-sm text-muted">
              On {job.requestedByName}'s computer{model ? ` · ${model}` : ''} · {duration(now - started)} so far
              {usageText(job.usage) ? ` · ${usageText(job.usage)}` : ''}. You can leave this page.
            </p>
          </div>
          <Button size="sm" variant="secondary" onClick={onCancel}>Cancel</Button>
        </div>
        <Stepper detail={detail} now={now} />
        <div className="rounded-xl border border-brand-100 bg-brand-50/50 p-4">
          <CurrentStep detail={detail} />
        </div>
      </div>
      {detail.groups.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 sm:px-6">
            <p className="text-sm text-ink-soft">
              {detail.savedFlows > 0
                ? <><span className="font-semibold text-ink">{detail.savedFlows} flows saved</span> so far. They appear below and you can start reviewing them.</>
                : 'Flows are saved as each area finishes.'}
            </p>
            <button onClick={toggle} aria-expanded={open}
              className="inline-flex h-9 cursor-pointer items-center gap-1 rounded-lg px-2 text-sm font-medium text-brand-700 hover:bg-brand-50">
              {open ? 'Hide area details' : 'Show area details'}
              <ChevronDown className={cx('size-4 transition-transform', open && 'rotate-180')} />
            </button>
          </div>
          {open && <div className="border-t border-line"><AreaTable groups={detail.groups} now={now} /></div>}
        </>
      )}
    </Card>
  );
}
