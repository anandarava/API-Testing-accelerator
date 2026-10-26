import { useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Circle, CircleCheck, Laptop, Upload } from 'lucide-react';
import { useFramework, useHelper, useProject, useProjectId, useRoles } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { HelperDialog } from '../components/HelperConnect';
import { ModelPicker, describeModels } from '../components/ModelPicker';
import { Badge, Button, Card, PageHeader, Spinner, cx } from '../components/ui';
import { useUpload } from './Apis';
import { FolderCard, ProfileCard } from './Framework';
import { RolesFileCard } from './RoleCases';

/** Everything a project needs before generating tests, in the order it is set up. */
export function ConfigurationPage() {
  const { data: project } = useProject();
  const framework = useFramework();
  const helper = useHelper();
  const roles = useRoles();
  const projectId = useProjectId();
  const client = useQueryClient();
  if (!project) return <Spinner />;
  const { setup } = project;
  const required = [setup.specUploaded, !!helper.data?.connected, setup.frameworkPathSet, setup.frameworkProfile === 'confirmed'];
  const done = required.filter(Boolean).length;
  const refreshRoles = () => client.invalidateQueries({ queryKey: ['project', projectId] });

  return (
    <>
      <PageHeader title="Configuration"
        description={done === required.length
          ? 'Setup is complete. Generate unit, flow and role test cases from the menu.'
          : `${done} of ${required.length} required steps done. Each step is needed once per project; steps 2 and 3 once per team member.`} />
      <div className="space-y-8">
        <Section number={1} title="API spec" done={setup.specUploaded} hint="The OpenAPI 3 or Swagger 2 file of the API you test, in JSON or YAML.">
          <SpecCard />
        </Section>

        <Section number={2} title="Your computer" done={!!helper.data?.connected}
          hint="Claude runs on your computer with your own Claude account. Each team member connects their own computer.">
          <ComputerCard />
        </Section>

        <Section number={3} title="Framework folder" done={setup.frameworkPathSet}
          hint="Where your Playwright + TypeScript project lives on this computer. Generated scripts are written there.">
          {framework.data ? <FolderCard view={framework.data} /> : <Spinner />}
        </Section>

        <Section number={4} title="Framework profile" done={setup.frameworkProfile === 'confirmed'}
          hint="Claude learns your framework's conventions once, so generated scripts look like your team wrote them.">
          {framework.data ? <ProfileCard view={framework.data} /> : <Spinner />}
        </Section>

        <Section number={5} title="Roles file" optional done={!!roles.data?.document}
          hint="Only needed for role test cases: your application's roles and what each may do. Credentials stay in your framework's .env file.">
          {roles.data ? (
            <div className="space-y-2">
              <RolesFileCard data={roles.data} onChanged={refreshRoles} />
              {roles.data.document && (
                <Link to="role-cases" className="inline-flex items-center gap-1 text-sm font-medium text-brand-600 hover:underline">
                  {roles.data.analysis ? 'Review the permission grid' : 'Analyze the roles file'} in Role test cases <ArrowRight className="size-3.5" />
                </Link>
              )}
            </div>
          ) : <Spinner />}
        </Section>

        {project.role === 'lead' && (
          <Section number={6} title="Team" optional done={project.memberCount > 1} hint="Give team members access to this project. Only leads can manage members.">
            <Card className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
              <p className="text-sm text-ink-soft">{plural(project.memberCount, 'member')} in this project</p>
              <Link to="members" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line-strong bg-surface px-3 text-sm font-medium text-ink-soft hover:bg-canvas">
                Manage members <ArrowRight className="size-3.5" />
              </Link>
            </Card>
          </Section>
        )}
      </div>
    </>
  );
}

function Section({ number, title, hint, done, optional, children }:
  { number: number; title: string; hint: string; done: boolean; optional?: boolean; children: ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-start gap-3">
        {done ? <CircleCheck className="mt-0.5 size-6 shrink-0 text-emerald-600" />
          : <span className="relative mt-0.5 flex size-6 shrink-0 items-center justify-center"><Circle className="size-6 text-line-strong" /><span className="absolute text-[11px] font-semibold text-muted">{number}</span></span>}
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-center gap-2 text-base font-semibold text-ink">
            {title}
            {optional && <Badge>Optional</Badge>}
            {done && <Badge tone="green">Done</Badge>}
          </h2>
          <p className="mt-0.5 text-sm text-muted">{hint}</p>
        </div>
      </div>
      <div className="sm:pl-9">{children}</div>
    </section>
  );
}

function SpecCard() {
  const { data: project } = useProject();
  const upload = useUpload();
  const input = useRef<HTMLInputElement>(null);
  const spec = project?.spec;
  return (
    <Card className="flex flex-wrap items-center gap-4 px-5 py-4">
      <div className="min-w-0 flex-1">
        {spec ? (
          <>
            <p className="truncate text-sm font-medium text-ink">{spec.title || 'Untitled API'}</p>
            <p className="text-xs text-muted">Version {spec.apiVersion || '—'} · {plural(spec.endpointCount, 'endpoint')} · upload #{spec.version}</p>
          </>
        ) : <p className="text-sm text-muted">No spec uploaded yet.</p>}
      </div>
      {spec && <Link to="apis" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-sm font-medium text-brand-600 hover:bg-brand-50">Browse APIs <ArrowRight className="size-3.5" /></Link>}
      <Button size="sm" variant={spec ? 'secondary' : 'primary'} icon={<Upload className="size-4" />} loading={upload.isPending} onClick={() => input.current?.click()}>
        {spec ? 'Upload new version' : 'Upload spec'}
      </Button>
      <input ref={input} type="file" accept=".json,.yaml,.yml" className="hidden"
        onChange={(e) => { const file = e.target.files?.[0]; if (file) upload.mutate(file); e.target.value = ''; }} />
    </Card>
  );
}

function ComputerCard() {
  const helper = useHelper();
  const [open, setOpen] = useState(false);
  const state = helper.data;
  const claude = state?.claude;
  return (
    <Card className="divide-y divide-line">
      <div className="flex flex-wrap items-center gap-4 px-5 py-4">
        <div className={cx('flex size-10 items-center justify-center rounded-lg', state?.connected ? 'bg-emerald-50 text-emerald-600' : 'bg-gray-100 text-muted')}>
          <Laptop className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          {state?.connected ? (
            <>
              <p className="text-sm font-medium text-ink">{state.hostname || 'This computer'} is connected</p>
              <p className="text-xs text-muted">
                Local Helper {state.helperVersion}
                {claude?.loggedIn ? ` · Claude signed in as ${claude.email}` : ' · Claude is not signed in'}
                {state.local?.configured && (state.local.reachable ? ` · local AI server ${state.local.server}` : ' · local AI server not reachable')} · seen {timeAgo(state.lastSeen)}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm font-medium text-ink">{state?.paired ? 'Paired, but the helper is not running' : 'Not connected'}</p>
              <p className="text-xs text-muted">{state?.paired ? 'Start it with .venv\\Scripts\\python -m helper start' : 'Pair this computer once, then start the Local Helper.'}</p>
            </>
          )}
        </div>
        <Button size="sm" variant={state?.connected ? 'secondary' : 'primary'} onClick={() => setOpen(true)}>{state?.connected ? 'Details' : 'Connect'}</Button>
      </div>
      <div className="flex flex-wrap items-center gap-3 px-5 py-3">
        <span className="text-sm text-ink-soft">AI model for your jobs</span>
        <ModelPicker />
        {state?.model.lastModels.length ? <span className="text-xs text-muted">Last job ran on {describeModels(state.model.lastModels)}</span> : null}
      </div>
      {open && <HelperDialog onClose={() => setOpen(false)} />}
    </Card>
  );
}
