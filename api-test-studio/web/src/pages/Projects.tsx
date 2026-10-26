import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FolderPlus, Plus, Users } from 'lucide-react';
import { api, type ProjectCard } from '../lib/api';
import { keys, useMe, useProjects } from '../lib/queries';
import { plural, timeAgo } from '../lib/format';
import { Button, Card, Dialog, EmptyState, Field, Input, PageHeader, RoleBadge, Spinner, Textarea, useToast } from '../components/ui';

export function ProjectsPage() {
  const projects = useProjects();
  const me = useMe();
  const [creating, setCreating] = useState(false);
  const firstName = me.data?.name.split(' ')[0];

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <PageHeader
        title={firstName ? `Hi ${firstName}` : 'Projects'}
        description="Pick a project to continue, or create a new one."
        action={projects.data?.length ? <Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>New project</Button> : undefined}
      />
      {projects.isPending ? <Spinner /> : !projects.data?.length ? (
        <Card>
          <EmptyState
            icon={<FolderPlus className="size-6" />}
            title="No projects yet"
            description="Create a project for an API you want to test. If your lead already created one, ask them to add you."
            action={<Button icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>Create your first project</Button>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data.map((project) => <ProjectTile key={project.id} project={project} />)}
        </div>
      )}
      {creating && <CreateProjectDialog onClose={() => setCreating(false)} />}
    </main>
  );
}

function ProjectTile({ project }: { project: ProjectCard }) {
  return (
    <Link to={`/projects/${project.id}`} className="group block rounded-xl">
      <Card className="flex h-full flex-col p-5 transition-all group-hover:border-brand-500/40 group-hover:shadow-md">
        <div className="flex items-start justify-between gap-3">
          <h3 className="font-semibold text-ink group-hover:text-brand-700">{project.name}</h3>
          <RoleBadge role={project.role} />
        </div>
        <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted">{project.description || 'No description'}</p>
        <div className="mt-4 rounded-lg bg-canvas px-3 py-2.5 text-sm">
          {project.spec ? (
            <><span className="font-medium text-ink-soft">{project.spec.title || 'API spec'}</span>
              <span className="text-muted"> · {plural(project.spec.endpointCount, 'endpoint')}</span></>
          ) : <span className="text-muted">No API spec uploaded yet</span>}
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-muted">
          <span className="inline-flex items-center gap-1.5"><Users className="size-3.5" /> {plural(project.memberCount, 'member')}</span>
          <span>Updated {timeAgo(project.updatedAt)}</span>
        </div>
      </Card>
    </Link>
  );
}

function CreateProjectDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const create = useMutation({
    mutationFn: () => api.post<ProjectCard>('/projects', { name, description }),
    onSuccess: (project) => {
      void client.invalidateQueries({ queryKey: keys.projects });
      toast.success('Project created. You are its lead.');
      navigate(`/projects/${project.id}`);
    },
    onError: toast.error,
  });
  const submit = (event: FormEvent) => { event.preventDefault(); create.mutate(); };
  return (
    <Dialog title="New project" description="You will be the project lead and can add your team afterwards." onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button form="new-project" type="submit" loading={create.isPending} disabled={!name.trim()}>Create project</Button></>}>
      <form id="new-project" className="space-y-4" onSubmit={submit}>
        <Field label="Project name"><Input autoFocus required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Payments API" /></Field>
        <Field label="Description" hint="Optional. What does this API do?"><Textarea rows={3} maxLength={1000} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      </form>
    </Dialog>
  );
}
