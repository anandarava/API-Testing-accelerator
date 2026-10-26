import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Trash2, UserPlus } from 'lucide-react';
import { api, type Member, type Role } from '../lib/api';
import { keys, useMe, useMembers, useProject, useProjectId } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { Alert, Avatar, Button, Card, CardHeader, Dialog, Input, PageHeader, Select, Spinner, useToast } from '../components/ui';

export function MembersPage() {
  const project = useProject();
  const members = useMembers();
  const me = useMe();
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('employee');
  const [removing, setRemoving] = useState<Member | null>(null);

  const refresh = () => {
    void client.invalidateQueries({ queryKey: keys.members(projectId) });
    void client.invalidateQueries({ queryKey: keys.project(projectId) });
    void client.invalidateQueries({ queryKey: keys.activity(projectId) });
  };
  const add = useMutation({
    mutationFn: () => api.post<Member>(`/projects/${projectId}/members`, { email, role }),
    onSuccess: (member) => { refresh(); setEmail(''); toast.success(`${member.name} now has access as ${member.role}.`); },
    onError: toast.error,
  });
  const changeRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) => api.patch(`/projects/${projectId}/members/${userId}`, { role }),
    onSuccess: () => { refresh(); toast.success('Role updated.'); },
    onError: (error) => { refresh(); toast.error(error); },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => api.delete(`/projects/${projectId}/members/${userId}`),
    onSuccess: () => { refresh(); setRemoving(null); toast.success('Access removed.'); },
    onError: toast.error,
  });

  if (project.data && project.data.role !== 'lead') {
    return <Alert tone="info" title="Only project leads manage members">Ask a lead of this project to add or remove people.</Alert>;
  }
  const submit = (event: FormEvent) => { event.preventDefault(); add.mutate(); };

  return (
    <>
      <PageHeader title="Members" description="Leads manage access and can do everything. Employees can do all the testing work but cannot manage access." />
      <div className="space-y-6">
        <Card>
          <CardHeader title="Add someone" description="They need an API Test Studio account first. Ask them to sign up with their work email." />
          <form className="flex flex-col gap-3 px-5 py-5 sm:flex-row" onSubmit={submit}>
            <Input type="email" required placeholder="colleague@company.com" value={email} onChange={(e) => setEmail(e.target.value)} className="sm:flex-1" />
            <Select value={role} onChange={(e) => setRole(e.target.value as Role)} className="sm:w-40" aria-label="Role">
              <option value="employee">Employee</option>
              <option value="lead">Lead</option>
            </Select>
            <Button type="submit" icon={<UserPlus className="size-4" />} loading={add.isPending}>Add member</Button>
          </form>
        </Card>

        <Card>
          <CardHeader title="People with access" description={members.data ? `${members.data.length} ${members.data.length === 1 ? 'person' : 'people'}` : undefined} />
          {members.isPending ? <Spinner /> : (
            <ul className="divide-y divide-line">
              {members.data?.map((member) => (
                <li key={member.userId} className="flex items-center gap-4 px-5 py-3.5">
                  <Avatar name={member.name} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{member.name}{member.userId === me.data?.id && <span className="font-normal text-muted"> (you)</span>}</p>
                    <p className="truncate text-sm text-muted">{member.email} · added {timeAgo(member.addedAt)}</p>
                  </div>
                  <div className="w-36 shrink-0">
                    <Select value={member.role} className="h-9" aria-label={`Role for ${member.name}`}
                      onChange={(e) => changeRole.mutate({ userId: member.userId, role: e.target.value as Role })}>
                      <option value="lead">Lead</option>
                      <option value="employee">Employee</option>
                    </Select>
                  </div>
                  <Button size="sm" variant="ghost" aria-label={`Remove ${member.name}`} onClick={() => setRemoving(member)}><Trash2 className="size-4" /></Button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="grid gap-4 sm:grid-cols-2">
          <RoleCard title="Lead" items={['Everything an employee can do', 'Add and remove members', 'Change roles', 'Rename or delete the project']} />
          <RoleCard title="Employee" items={['Upload API specs', 'Generate, edit and approve test cases', 'Generate scripts', 'Edit the framework profile']} />
        </div>
      </div>

      {removing && (
        <Dialog title={`Remove ${removing.name}?`} description="They will lose access to this project immediately. Their work stays in the project." onClose={() => setRemoving(null)}
          footer={<><Button variant="secondary" onClick={() => setRemoving(null)}>Cancel</Button><Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate(removing.userId)}>Remove access</Button></>}>
          <p className="text-sm text-muted">{removing.email}</p>
        </Dialog>
      )}
    </>
  );
}

function RoleCard({ title, items }: { title: string; items: string[] }) {
  return (
    <Card className="p-5">
      <p className="flex items-center gap-2 font-semibold text-ink"><ShieldCheck className="size-4 text-brand-600" /> {title}</p>
      <ul className="mt-2 space-y-1 text-sm text-muted">{items.map((item) => <li key={item}>• {item}</li>)}</ul>
    </Card>
  );
}
