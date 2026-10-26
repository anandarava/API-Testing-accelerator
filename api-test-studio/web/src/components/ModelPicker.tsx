import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, ChevronDown, Cpu } from 'lucide-react';
import { api, type ModelOption, type ModelPreferences } from '../lib/api';
import { keys, useHelper } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { cx, useToast } from './ui';

const FAMILY_HINTS: Record<string, string> = {
  Fable: 'Most capable; uses the most of your plan',
  Opus: 'Most thorough; slower and uses more of your plan',
  Sonnet: 'Balanced speed and quality',
  Haiku: 'Fastest; lighter reasoning',
};
const ALIASES: Record<string, string> = { fable: 'Fable', opus: 'Opus', sonnet: 'Sonnet', haiku: 'Haiku' };
const CUSTOM_MODEL = /^claude-[a-z]+-[0-9]+(-[0-9]+)*$/;
const LOCAL = 'local:';

/** A model on the helper's own AI server rather than Claude. */
export const isLocal = (id: string) => id.startsWith(LOCAL);

/** "claude-sonnet-5-5" -> "Sonnet 5.5", "claude-opus-5" -> "Opus 5". */
export function modelName(id: string): string {
  if (isLocal(id)) return `${id.slice(LOCAL.length)} (local)`;
  const match = id.match(/^claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?!\d)/i);
  if (!match) return id;
  return `${match[1][0].toUpperCase()}${match[1].slice(1)} ${match[2]}${match[3] ? `.${match[3]}` : ''}`;
}

/** The label of a chosen model: "Account default", "Latest Opus" or a version such as "Opus 4.8". */
export function modelLabel(choice: string): string {
  if (choice === 'default') return 'Account default';
  if (ALIASES[choice]) return `Latest ${ALIASES[choice]}`;
  return modelName(choice);
}

/** The main model, with any small helper models Claude Code used noted separately. Local models are listed as equals. */
export function describeModels(models: string[]): string {
  if (!models.length) return '';
  const [main, ...rest] = models;
  const locals = rest.filter(isLocal);
  const helpers = rest.filter((id) => !isLocal(id));
  const listed = [main, ...locals].map(modelName).join(' + ');
  if (!helpers.length) return listed;
  return isLocal(main) ? `${listed} + ${helpers.map(modelName).join(', ')}` : `${listed} (+ ${helpers.map(modelName).join(', ')} for small helper tasks)`;
}

function families(options: ModelOption[]): [string, ModelOption[]][] {
  const groups = new Map<string, ModelOption[]>();
  for (const option of options) if (option.family) groups.set(option.family, [...(groups.get(option.family) ?? []), option]);
  return [...groups];
}

export function ModelPicker() {
  const helper = useHelper();
  const client = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState('');
  const [tab, setTab] = useState<'claude' | 'local' | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => ref.current && !ref.current.contains(event.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const prefs = helper.data?.model;
  const save = useMutation({
    mutationFn: (claudeModel: string) => api.put<ModelPreferences>('/me/preferences', { claudeModel }),
    onSuccess: (result) => {
      void client.invalidateQueries({ queryKey: keys.helper });
      toast.success(`New jobs will run on ${modelLabel(result.claudeModel)}. Jobs already running keep their model.`);
      setOpen(false);
      setTab(null);
      setCustom('');
    },
    onError: toast.error,
  });
  if (!prefs) return null;
  const local = helper.data?.local ?? null;
  const localModels = local?.models ?? [];
  const view = tab ?? (isLocal(prefs.claudeModel) ? 'local' : 'claude');
  const choose = (id: string) => id !== prefs.claudeModel && save.mutate(id);
  const known = prefs.options.some((option) => option.id === prefs.claudeModel);
  const lastRun = describeModels(prefs.lastModels);
  const lastMain = prefs.lastModels[0] ? modelName(prefs.lastModels[0]) : '';
  const showActual = (prefs.claudeModel === 'default' || ALIASES[prefs.claudeModel]) && lastMain && !isLocal(prefs.lastModels[0]);
  const customValid = CUSTOM_MODEL.test(custom.trim());
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} title={lastRun ? `Last job ran on ${lastRun}` : 'Choose the AI model'}
        className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 text-xs font-medium text-ink-soft hover:bg-canvas">
        <Cpu className="size-3.5 text-brand-600" />
        <span className="hidden sm:inline">Model:</span> {modelLabel(prefs.claudeModel)}
        {showActual && <span className="hidden text-muted md:inline">({lastMain})</span>}
        <ChevronDown className="size-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 top-10 z-40 max-h-[80vh] w-[22rem] overflow-y-auto rounded-xl border border-line bg-surface p-1.5 shadow-lg animate-pop-in">
          <p className="px-3 pb-1.5 pt-2 text-xs font-semibold uppercase tracking-wide text-faint">AI model for your jobs</p>
          <div className="mx-1 mb-1.5 grid grid-cols-2 rounded-lg bg-canvas p-0.5 text-xs font-medium" role="tablist">
            {([['claude', 'Claude'], ['local', 'Local server']] as const).map(([id, label]) => (
              <button key={id} role="tab" aria-selected={view === id} onClick={() => setTab(id)}
                className={cx('h-7 cursor-pointer rounded-md', view === id ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink-soft')}>
                {label}{(id === 'local') === isLocal(prefs.claudeModel) && <span className="ml-1 text-brand-600">•</span>}
              </button>
            ))}
          </div>
          {view === 'local' ? (
            <div className="px-3 py-2">
              {!local ? (
                <p className="text-xs text-muted">Start the Local Helper to see the models of your local AI server.</p>
              ) : !local.configured ? (
                <p className="text-xs text-muted">No local AI server is set up on your computer. Add <span className="font-mono">STUDIO_LLM_BASE_URL</span> and <span className="font-mono">STUDIO_LLM_API_KEY</span> to the <span className="font-mono">.env</span> file in the api-test-studio folder, then restart the helper.</p>
              ) : (
                <>
                  <p className={cx('flex items-center gap-1.5 text-xs', local.reachable ? 'text-ink-soft' : 'text-amber-700')} title={local.server}>
                    <span className={cx('size-2 shrink-0 rounded-full', local.reachable ? 'bg-emerald-500' : 'bg-amber-500')} />
                    {local.reachable ? "Connected to your team's AI server" : local.error}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {localModels.map((name) => {
                      const id = LOCAL + name;
                      const selected = id === prefs.claudeModel;
                      return (
                        <button key={id} disabled={save.isPending} onClick={() => choose(id)} title={id}
                          className={cx('inline-flex h-6 cursor-pointer items-center gap-1 rounded-full border px-2.5 font-mono text-xs',
                            selected ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}>
                          {selected && <Check className="size-3" />}{name}
                        </button>
                      );
                    })}
                    {!localModels.length && <span className="text-xs text-muted">The server lists no chat models for your key.</span>}
                  </div>
                  <p className="mt-2 text-xs text-muted">Slower and less thorough than Claude; review results carefully.</p>
                </>
              )}
            </div>
          ) : (<>
          <button disabled={save.isPending} onClick={() => choose('default')}
            className={cx('flex w-full cursor-pointer items-start gap-3 rounded-lg px-3 py-2 text-left hover:bg-canvas', prefs.claudeModel === 'default' && 'bg-brand-50')}>
            <span className="mt-0.5 size-4 shrink-0">{prefs.claudeModel === 'default' && <Check className="size-4 text-brand-600" />}</span>
            <span><span className="block text-sm font-medium text-ink">Account default</span><span className="text-xs text-muted">The default model of your Claude account</span></span>
          </button>
          {families(prefs.options).map(([family, versions]) => {
            const active = versions.some((option) => option.id === prefs.claudeModel);
            return (
              <div key={family} className={cx('rounded-lg px-3 py-2', active && 'bg-brand-50')}>
                <p className="text-sm font-medium text-ink">{family}</p>
                <p className="text-xs text-muted">{FAMILY_HINTS[family] ?? ''}</p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {versions.map((option) => {
                    const selected = option.id === prefs.claudeModel;
                    return (
                      <button key={option.id} disabled={save.isPending} onClick={() => choose(option.id)} title={option.id}
                        className={cx('inline-flex h-6 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-xs font-medium',
                          selected ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}>
                        {selected && <Check className="size-3" />}
                        {ALIASES[option.id] ? 'Latest' : option.label.replace(`${family} `, '')}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
          <form className="px-3 py-2" onSubmit={(event) => { event.preventDefault(); if (customValid) choose(custom.trim()); }}>
            <p className="text-sm font-medium text-ink">Other model ID</p>
            {!known && prefs.claudeModel !== 'default' && !isLocal(prefs.claudeModel) && (
              <p className="text-xs text-muted">Using <span className="font-mono text-ink-soft">{prefs.claudeModel}</span></p>
            )}
            <div className="mt-1.5 flex gap-1.5">
              <input value={custom} onChange={(event) => setCustom(event.target.value)} placeholder="e.g. claude-opus-4-8"
                className="h-7 min-w-0 flex-1 rounded-md border border-line-strong bg-surface px-2 font-mono text-xs text-ink outline-none focus:border-brand-600" />
              <button type="submit" disabled={!customValid || save.isPending}
                className="h-7 cursor-pointer rounded-md border border-line-strong px-2.5 text-xs font-medium text-ink-soft hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50">Use</button>
            </div>
            {custom.trim() && !customValid && <p className="mt-1 text-xs text-muted">Use a full model ID such as claude-sonnet-4-6.</p>}
          </form>
          </>)}
          <div className="mt-1 border-t border-line px-3 py-2.5 text-xs text-muted">
            {lastRun ? <>Last job ran on <span className="font-medium text-ink-soft">{lastRun}</span> · {timeAgo(prefs.lastUsedAt)}</> : 'No job has run yet.'}
            {view === 'claude' && <p className="mt-1">"Latest" always uses the newest version of that family. Applies to jobs you start from now on. Which models you can use depends on your Claude plan.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
