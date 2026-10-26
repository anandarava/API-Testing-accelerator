import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { CircleCheck, FolderOpen, Pencil, Sparkles, TriangleAlert } from 'lucide-react';
import { api, type FrameworkProfile, type FrameworkView, type Job } from '../lib/api';
import { keys, useHelper, useProjectId } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { HelperDialog } from '../components/HelperConnect';
import { describeModels } from '../components/ModelPicker';
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Field, Input, ProgressBar, Textarea, useToast } from '../components/ui';

function useRefresh() {
  const projectId = useProjectId();
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.framework(projectId) });
    void client.invalidateQueries({ queryKey: keys.project(projectId) });
  };
}

export function FolderCard({ view }: { view: FrameworkView }) {
  const projectId = useProjectId();
  const [path, setPath] = useState(view.myPath);
  const refresh = useRefresh();
  const toast = useToast();
  useEffect(() => setPath(view.myPath), [view.myPath]);
  const save = useMutation({
    mutationFn: () => api.put(`/projects/${projectId}/framework/path`, { path }),
    onSuccess: () => { refresh(); toast.success('Framework folder saved.'); },
    onError: toast.error,
  });
  const submit = (event: FormEvent) => { event.preventDefault(); save.mutate(); };
  const example = navigator.userAgent.includes('Windows') ? 'C:\\Users\\you\\code\\api-tests' : '/Users/you/code/api-tests';
  return (
    <Card>
      <CardHeader title="Your framework folder" description="Only you see this path. Each team member points to their own copy of the framework repository." />
      <form className="flex flex-col gap-3 px-5 py-5 sm:flex-row sm:items-start" onSubmit={submit}>
        <div className="flex-1">
          <div className="relative">
            <FolderOpen className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
            <Input className="pl-9 font-mono" value={path} onChange={(e) => setPath(e.target.value)} placeholder={example} />
          </div>
          <p className="mt-1.5 text-sm text-muted">The full path of the folder that contains <code className="font-mono">package.json</code> and <code className="font-mono">playwright.config.ts</code>.</p>
        </div>
        <Button type="submit" variant="secondary" loading={save.isPending} disabled={!path.trim() || path.trim() === view.myPath}>Save folder</Button>
      </form>
    </Card>
  );
}

const STATUS = {
  missing: <Badge>Not analyzed</Badge>,
  draft: <Badge tone="amber">Needs review</Badge>,
  confirmed: <Badge tone="green"><CircleCheck className="size-3" /> Confirmed</Badge>,
};

export function ProfileCard({ view }: { view: FrameworkView }) {
  const projectId = useProjectId();
  const helper = useHelper();
  const refresh = useRefresh();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const job = view.latestJob;
  const running = job?.status === 'queued' || job?.status === 'running';
  const failedAfterProfile = job?.status === 'failed' && (!view.updatedAt || job.createdAt > view.updatedAt);

  const analyze = useMutation({ mutationFn: () => api.post(`/projects/${projectId}/framework/analyze`), onSuccess: refresh, onError: toast.error });
  const cancel = useMutation({ mutationFn: (id: string) => api.post(`/projects/${projectId}/jobs/${id}/cancel`), onSuccess: refresh, onError: toast.error });
  const confirm = useMutation({
    mutationFn: () => api.put(`/projects/${projectId}/framework/profile`, { revision: view.revision, profile: view.profile, confirm: true }),
    onSuccess: () => { refresh(); toast.success('Framework profile confirmed.'); },
    onError: toast.error,
  });

  const blocker = !view.myPath ? 'Save your framework folder first.' : !helper.data?.connected ? 'Connect your computer to run the analysis.' : null;
  const analyzeButton = (
    <Button variant={view.profile ? 'secondary' : 'primary'} icon={<Sparkles className="size-4" />} loading={analyze.isPending}
      disabled={!!blocker || running} title={blocker ?? undefined} onClick={() => analyze.mutate()}>
      {view.profile ? 'Analyze again' : 'Analyze framework'}
    </Button>
  );

  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2">Framework profile {STATUS[view.status]}</span>}
        description={view.updatedAt ? `Last updated by ${view.updatedBy} ${timeAgo(view.updatedAt)}. Shared with everyone in this project.` : 'Claude reads your framework once and describes how tests are written. The whole project shares this profile.'}
        action={!editing && !running ? analyzeButton : undefined}
      />
      <div className="px-5 py-5">
        {running && job && <RunningJob job={job} onCancel={() => cancel.mutate(job.id)} />}
        {!running && blocker && !view.profile && (
          <Alert tone="info" title="Before you analyze" action={!helper.data?.connected && view.myPath ? <Button size="sm" variant="secondary" onClick={() => setConnecting(true)}>Connect</Button> : undefined}>{blocker}</Alert>
        )}
        {!running && failedAfterProfile && job && <div className="mb-5"><Alert tone="error" title="The last analysis failed">{job.error}</Alert></div>}
        {!running && !view.profile && !blocker && (
          <EmptyState icon={<Sparkles className="size-6" />} title="Let Claude learn your framework"
            description="It reads your config, fixtures, API clients and existing tests on your computer (read-only) and never opens .env files." action={analyzeButton} />
        )}
        {view.profile && !running && (editing
          ? <ProfileEditor view={view} onDone={() => setEditing(false)} />
          : (
            <>
              {view.status === 'draft' && (
                <div className="mb-6">
                  <Alert tone="warning" title="Review this profile"
                    action={<div className="flex gap-2"><Button size="sm" variant="secondary" icon={<Pencil className="size-3.5" />} onClick={() => setEditing(true)}>Edit</Button><Button size="sm" loading={confirm.isPending} onClick={() => confirm.mutate()}>Looks right, confirm</Button></div>}>
                    Check that it matches how your team writes tests. Scripts will follow it exactly.
                  </Alert>
                </div>
              )}
              <ProfileDetails view={view} />
              {view.status === 'confirmed' && <div className="mt-6 flex justify-end"><Button variant="secondary" icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>Edit profile</Button></div>}
            </>
          ))}
      </div>
      {connecting && <HelperDialog onClose={() => setConnecting(false)} />}
    </Card>
  );
}

function RunningJob({ job, onCancel }: { job: Job; onCancel: () => void }) {
  return (
    <div className="rounded-xl border border-brand-100 bg-brand-50/50 p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-ink">{job.status === 'queued' ? 'Waiting for the Local Helper…' : job.progress.message || 'Analyzing…'}</p>
          <p className="mt-0.5 text-sm text-muted">Running on {job.requestedByName}'s computer{job.models.length ? ` on ${describeModels(job.models)}` : ''} · started {timeAgo(job.createdAt)}</p>
        </div>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      <div className="mt-4"><ProgressBar percent={job.progress.percent ?? 2} /></div>
      <p className="mt-3 text-xs text-muted">This usually takes 1–4 minutes. You can leave this page.</p>
    </div>
  );
}

function ProfileDetails({ view }: { view: FrameworkView }) {
  const p = view.profile!;
  return (
    <div className="space-y-6">
      <p className="text-sm leading-relaxed text-ink-soft">{p.summary}</p>
      {p.warnings.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="flex items-center gap-2 text-sm font-medium text-amber-900"><TriangleAlert className="size-4" /> Things to check</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-10 text-sm text-amber-900/90">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      <dl className="grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2">
        <Fact label="New tests go in" value={<code className="font-mono">{p.testDirectory}</code>} />
        <Fact label="Spec file pattern" value={<code className="font-mono">{p.testFilePattern}</code>} />
        <Fact label="File naming" value={p.fileNaming} />
        <Fact label="HTTP client" value={<>{p.httpClient.description}{p.httpClient.location && <code className="mt-1 block font-mono text-xs text-muted">{p.httpClient.location}</code>}</>} />
        <Fact label="Authentication" value={<>{p.authentication.approach}{p.authentication.envVariables.length > 0 && <EnvList names={p.authentication.envVariables} />}</>} />
        <Fact label="Base URL" value={<>{p.baseUrl.source}{p.baseUrl.envVariable && <EnvList names={[p.baseUrl.envVariable]} />}</>} />
        <Fact label="Assertions" value={p.assertions.style} />
        <Fact label="Test data" value={p.testData.approach} />
      </dl>
      {p.conventions.length > 0 && (
        <Block title="Conventions to follow">
          <ul className="space-y-1.5">{p.conventions.map((c) => <li key={c} className="flex gap-2 text-sm text-ink-soft"><CircleCheck className="mt-0.5 size-4 shrink-0 text-brand-600" />{c}</li>)}</ul>
        </Block>
      )}
      {p.imports.length > 0 && (
        <Block title="Imports used by API tests">
          <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 font-mono text-xs leading-relaxed text-gray-100">{p.imports.map((i) => i.statement).join('\n')}</pre>
        </Block>
      )}
      {p.httpClient.exampleUsage && (
        <Block title="Example request and assertion">
          <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 font-mono text-xs leading-relaxed text-gray-100">{p.httpClient.exampleUsage}</pre>
        </Block>
      )}
      {(p.fixtures.length > 0 || p.assertions.helpers.length > 0) && (
        <Block title="Building blocks">
          <ul className="divide-y divide-line rounded-lg border border-line">
            {[...p.fixtures, ...p.assertions.helpers].map((f) => (
              <li key={f.file + f.name} className="px-4 py-2.5 text-sm"><span className="font-medium text-ink">{f.name}</span> <code className="ml-1 font-mono text-xs text-muted">{f.file}</code><p className="text-muted">{f.description}</p></li>
            ))}
          </ul>
        </Block>
      )}
      {p.exampleTests.length > 0 && (
        <Block title="Reference tests">
          <ul className="space-y-1.5 text-sm">{p.exampleTests.map((t) => <li key={t.file}><code className="font-mono text-ink">{t.file}</code><span className="text-muted"> — {t.why}</span></li>)}</ul>
        </Block>
      )}
      {view.scan && (
        <p className="text-xs text-faint">Detected Playwright {view.scan.playwrightVersion || '?'}, TypeScript {view.scan.typescriptVersion || '?'}, {view.scan.specFileCount} existing spec files.</p>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return <div className="bg-surface px-4 py-3"><dt className="text-xs font-medium text-muted">{label}</dt><dd className="mt-1 text-sm text-ink">{value}</dd></div>;
}

function EnvList({ names }: { names: string[] }) {
  return <span className="mt-1.5 flex flex-wrap gap-1">{names.map((n) => <code key={n} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">{n}</code>)}</span>;
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return <section><h3 className="mb-2 text-sm font-semibold text-ink">{title}</h3>{children}</section>;
}

const lines = (text: string) => text.split('\n').map((line) => line.trim()).filter(Boolean);
const names = (text: string) => text.split(/[\s,]+/).map((name) => name.trim()).filter(Boolean);

function ProfileEditor({ view, onDone }: { view: FrameworkView; onDone: () => void }) {
  const projectId = useProjectId();
  const refresh = useRefresh();
  const toast = useToast();
  const [p, setP] = useState<FrameworkProfile>(view.profile!);
  const [conventions, setConventions] = useState(p.conventions.join('\n'));
  const [authEnv, setAuthEnv] = useState(p.authentication.envVariables.join(', '));
  const save = useMutation({
    mutationFn: (confirm: boolean) => api.put(`/projects/${projectId}/framework/profile`, {
      revision: view.revision, confirm,
      profile: { ...p, conventions: lines(conventions), authentication: { ...p.authentication, envVariables: names(authEnv) } },
    }),
    onSuccess: (_, confirm) => { refresh(); toast.success(confirm ? 'Profile saved and confirmed.' : 'Profile saved.'); onDone(); },
    onError: toast.error,
  });
  const set = <K extends keyof FrameworkProfile>(key: K, value: FrameworkProfile[K]) => setP({ ...p, [key]: value });
  return (
    <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(true); }}>
      <Field label="Summary"><Textarea rows={3} value={p.summary} onChange={(e) => set('summary', e.target.value)} /></Field>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Folder for new API tests"><Input className="font-mono" value={p.testDirectory} onChange={(e) => set('testDirectory', e.target.value)} /></Field>
        <Field label="Spec file pattern"><Input className="font-mono" value={p.testFilePattern} onChange={(e) => set('testFilePattern', e.target.value)} /></Field>
        <Field label="File naming"><Input value={p.fileNaming} onChange={(e) => set('fileNaming', e.target.value)} /></Field>
        <Field label="Base URL comes from"><Input value={p.baseUrl.source} onChange={(e) => set('baseUrl', { ...p.baseUrl, source: e.target.value })} /></Field>
        <Field label="Authentication approach"><Input value={p.authentication.approach} onChange={(e) => set('authentication', { ...p.authentication, approach: e.target.value })} /></Field>
        <Field label="Auth environment variables" hint="Comma separated"><Input className="font-mono" value={authEnv} onChange={(e) => setAuthEnv(e.target.value)} /></Field>
        <Field label="Assertion style"><Input value={p.assertions.style} onChange={(e) => set('assertions', { ...p.assertions, style: e.target.value })} /></Field>
        <Field label="Test data approach"><Input value={p.testData.approach} onChange={(e) => set('testData', { ...p.testData, approach: e.target.value })} /></Field>
      </div>
      <Field label="Conventions" hint="One rule per line"><Textarea rows={6} value={conventions} onChange={(e) => setConventions(e.target.value)} /></Field>
      <div className="flex justify-end gap-2 border-t border-line pt-5">
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
        <Button type="button" variant="secondary" loading={save.isPending && !save.variables} onClick={() => save.mutate(false)}>Save draft</Button>
        <Button type="submit" loading={save.isPending && !!save.variables}>Save and confirm</Button>
      </div>
    </form>
  );
}
