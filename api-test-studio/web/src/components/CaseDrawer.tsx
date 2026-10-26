import { useState, type ReactNode } from 'react';
import { useMutation } from '@tanstack/react-query';
import { CircleCheck, CircleX, MessageSquareWarning, Pencil, RotateCcw, Sparkles, Trash2 } from 'lucide-react';
import { RegenerateDialog } from './CaseTools';
import { api, type AuthMode, type ExpectedResult, type Priority, type RequestSpec, type TestCase } from '../lib/api';
import { useProjectId } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { AUTH_LABEL, CATEGORY_LABEL, PRIORITY_LABEL, PriorityBadge, ROLE_KIND_LABEL, StatusBadge, statusTone } from './cases';
import { Alert, Badge, Button, Dialog, Drawer, Field, Input, MethodBadge, Select, Textarea, useToast } from './ui';

export function CaseDrawer({ item, regenerating, onClose, onChanged }: { item: TestCase; regenerating: boolean; onClose: () => void; onChanged: () => void }) {
  const projectId = useProjectId();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [dialog, setDialog] = useState<'needs_changes' | 'reject' | 'delete' | 'regenerate' | null>(null);
  const act = useMutation({
    mutationFn: ({ action, comment = '' }: { action: string; comment?: string }) =>
      api.post(`/projects/${projectId}/unit/cases/review`, { caseIds: [item.id], action, comment }),
    onSuccess: () => { setDialog(null); onChanged(); },
    onError: toast.error,
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/unit/cases/${item.id}`),
    onSuccess: () => { toast.success(`${item.code} deleted.`); onChanged(); onClose(); },
    onError: toast.error,
  });

  const footer = editing ? undefined : (
    <>
      {item.status !== 'approved' && <Button size="sm" icon={<CircleCheck className="size-4" />} loading={act.isPending && act.variables?.action === 'approve'} onClick={() => act.mutate({ action: 'approve' })}>Approve</Button>}
      {item.status !== 'needs_changes' && <Button size="sm" variant="secondary" icon={<MessageSquareWarning className="size-4" />} onClick={() => setDialog('needs_changes')}>Needs changes</Button>}
      {item.status !== 'rejected' && <Button size="sm" variant="secondary" icon={<CircleX className="size-4" />} onClick={() => setDialog('reject')}>Reject</Button>}
      {item.status !== 'in_review' && <Button size="sm" variant="ghost" icon={<RotateCcw className="size-4" />} onClick={() => act.mutate({ action: 'reopen' })}>Back to review</Button>}
      <div className="ml-auto flex gap-1">
        {item.module !== 'role' && <Button size="sm" variant="ghost" icon={<Sparkles className="size-4" />} disabled={regenerating} onClick={() => setDialog('regenerate')}>Regenerate</Button>}
        <Button size="sm" variant="ghost" icon={<Pencil className="size-4" />} onClick={() => setEditing(true)}>Edit</Button>
        <Button size="sm" variant="ghost" aria-label="Delete" onClick={() => setDialog('delete')}><Trash2 className="size-4" /></Button>
      </div>
    </>
  );

  return (
    <Drawer onClose={onClose} footer={footer}
      title={<div><p className="font-mono text-xs text-muted">{item.code} · {item.scenarioKey}</p><p className="mt-0.5 text-base font-semibold text-ink">{item.title}</p></div>}
      subtitle={<div className="mt-1 flex flex-wrap items-center gap-1.5"><StatusBadge status={item.status} /><PriorityBadge priority={item.priority} /><Badge>{(item.module === 'role' ? ROLE_KIND_LABEL : CATEGORY_LABEL)[item.category] ?? item.category}</Badge></div>}>
      {regenerating && <div className="px-6 pt-5"><Alert tone="info" title="Claude is rewriting this case">It updates here when it is done. Wait before editing.</Alert></div>}
      {editing ? <CaseEditor item={item} onDone={() => setEditing(false)} onSaved={onChanged} /> : <CaseView item={item} />}
      {dialog === 'regenerate' && <RegenerateDialog caseId={item.id} code={item.code} reviewComment={item.status === 'needs_changes' ? item.reviewComment : ''} onClose={() => setDialog(null)} onStarted={onChanged} />}
      {(dialog === 'needs_changes' || dialog === 'reject') && (
        <ReviewDialog action={dialog} count={1} loading={act.isPending} onClose={() => setDialog(null)} onSubmit={(comment) => act.mutate({ action: dialog, comment })} />
      )}
      {dialog === 'delete' && (
        <Dialog title={`Delete ${item.code}?`} description="This removes the test case for everyone in the project." onClose={() => setDialog(null)}
          footer={<><Button variant="secondary" onClick={() => setDialog(null)}>Cancel</Button><Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>Delete</Button></>}>
          <p className="text-sm text-ink-soft">{item.title}</p>
        </Dialog>
      )}
    </Drawer>
  );
}

export function ReviewDialog({ action, count, loading, onClose, onSubmit }:
  { action: 'needs_changes' | 'reject'; count: number; loading: boolean; onClose: () => void; onSubmit: (comment: string) => void }) {
  const [comment, setComment] = useState('');
  const needs = action === 'needs_changes';
  const subject = count === 1 ? 'this case' : `${count} cases`;
  return (
    <Dialog title={needs ? `Request changes on ${subject}` : `Reject ${subject}`} onClose={onClose}
      description={needs ? 'Explain what should change. The comment is shown on the case.' : 'Rejected cases are not used for scripts. A reason helps your team.'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant={needs ? 'primary' : 'danger'} loading={loading} disabled={needs && !comment.trim()} onClick={() => onSubmit(comment)}>{needs ? 'Request changes' : 'Reject'}</Button></>}>
      <Field label={needs ? 'What needs to change?' : 'Reason (optional)'}><Textarea autoFocus rows={4} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
    </Dialog>
  );
}

// --- Reading view ------------------------------------------------------------------------------

function CaseView({ item }: { item: TestCase }) {
  const { content } = item;
  const request = content.request;
  const expected = content.expected;
  return (
    <div className="space-y-6 px-6 py-5">
      {item.outdated && <Alert tone="warning" title="Outdated">The API spec changed after this case was written. Check it against the current contract.</Alert>}
      {item.reviewComment && <Alert tone={item.status === 'rejected' ? 'error' : 'warning'} title={item.status === 'rejected' ? 'Rejected' : 'Changes requested'}>{item.reviewComment}{item.reviewedBy && <span className="opacity-75"> — {item.reviewedBy}</span>}</Alert>}
      {item.needsConfirmation && (
        <Alert tone="warning" title="Confirm the expected result">{content.confirmationNote || 'The API contract does not state this behaviour exactly.'} Approving the case confirms it.</Alert>
      )}
      {item.findings.length > 0 && (
        <div className="rounded-lg border border-line">
          <p className="border-b border-line px-4 py-2 text-sm font-medium text-ink">AI reviewer notes</p>
          <ul className="divide-y divide-line">
            {item.findings.map((f, i) => (
              <li key={i} className="flex gap-3 px-4 py-2.5 text-sm">
                <Badge tone={f.severity === 'blocker' ? 'red' : f.severity === 'major' ? 'amber' : 'gray'} className="h-fit">{f.severity}</Badge>
                <span className="text-ink-soft">{f.issue}{f.suggestion && <span className="block text-muted">Suggestion: {f.suggestion}</span>}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Section title="Objective"><p className="text-sm leading-relaxed text-ink-soft">{content.objective}</p></Section>
      {item.module === 'role' && (
        <Section title="Runs as">
          <div className="flex flex-wrap items-center gap-1.5">
            {(content.roles ?? []).map((role) => <Badge key={role} tone="brand">{role}</Badge>)}
            <span className="text-sm text-muted">· {content.userSlot === 'second' ? 'a second user of the role (not the owner of the record)' : 'the first user of each role'}</span>
          </div>
          {(content.roles?.length ?? 0) > 1 && <p className="mt-1.5 text-xs text-muted">The request runs once for each role.</p>}
        </Section>
      )}
      {content.preconditions.length > 0 && <Section title="Preconditions"><NumberedList items={content.preconditions} /></Section>}

      <Section title="Request">
        <div className="space-y-3 rounded-lg border border-line p-4">
          <div className="flex flex-wrap items-center gap-2">
            <MethodBadge method={item.method} /><span className="font-mono text-[13px] text-ink">{item.path}</span>
            <Badge tone={request.auth === 'valid' ? 'gray' : 'purple'}>{AUTH_LABEL[request.auth]}</Badge>
          </div>
          <KeyValues title="Path parameters" values={request.pathParams} />
          <KeyValues title="Query" values={request.query} />
          <KeyValues title="Headers" values={request.headers} />
          {request.body !== null && request.body !== undefined && (
            <div><p className="mb-1 text-xs font-medium text-muted">Body</p><Code value={request.body} /></div>
          )}
          {request.bodyNote && <p className="text-sm text-muted">{request.bodyNote}</p>}
        </div>
      </Section>

      <Section title="Expected result">
        <div className="space-y-3 rounded-lg border border-line p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted">Status</span>
            {expected.status ? <Badge tone={statusTone(expected.status)}>{expected.status}</Badge> : <Badge>Not specified</Badge>}
            {expected.responseSchema !== 'none' && <span className="text-sm text-muted">· body matches the {expected.responseSchema === 'success' ? 'success' : 'error'} schema</span>}
          </div>
          {expected.bodyChecks.length > 0 && (
            <ul className="space-y-1">
              {expected.bodyChecks.map((check, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-2 text-sm">
                  <CircleCheck className="size-3.5 shrink-0 translate-y-0.5 text-brand-600" />
                  <code className="font-mono text-[13px] text-ink">{check.path}</code>
                  <span className="text-muted">{check.check.replaceAll('_', ' ')}</span>
                  {check.value !== null && check.value !== undefined && <code className="rounded bg-gray-100 px-1.5 font-mono text-xs">{JSON.stringify(check.value)}</code>}
                </li>
              ))}
            </ul>
          )}
          {expected.notes && <p className="text-sm text-muted">{expected.notes}</p>}
        </div>
      </Section>

      {content.verifyUnchanged && <Section title="Prove nothing changed"><p className="text-sm text-ink-soft">{content.verifyUnchanged}</p></Section>}
      {content.testData && <Section title="Test data"><p className="whitespace-pre-line text-sm text-ink-soft">{content.testData}</p></Section>}
      {content.cleanup.length > 0 && <Section title="Cleanup"><NumberedList items={content.cleanup} /></Section>}

      {(content.condition || content.source) && (
        <Section title="Traceability">
          <dl className="space-y-1.5 text-sm">
            <div className="flex gap-2"><dt className="w-24 shrink-0 text-muted">Condition</dt><dd className="text-ink-soft">{content.condition}</dd></div>
            <div className="flex gap-2"><dt className="w-24 shrink-0 text-muted">Source</dt><dd className="font-mono text-xs text-ink-soft">{content.source}</dd></div>
            {(content.covers?.length ?? 0) > 0 && <div className="flex gap-2"><dt className="w-24 shrink-0 text-muted">Covers</dt><dd className="flex flex-wrap gap-1">{content.covers!.map((c) => <code key={c} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">{c}</code>)}</dd></div>}
          </dl>
        </Section>
      )}
      <p className="text-xs text-faint">
        Created by {item.createdBy ?? 'Claude'} {timeAgo(item.createdAt)}
        {item.updatedBy && item.updatedAt !== item.createdAt && ` · edited by ${item.updatedBy} ${timeAgo(item.updatedAt)}`}
        {item.reviewedBy && item.status !== 'in_review' && ` · reviewed by ${item.reviewedBy} ${timeAgo(item.reviewedAt)}`}
      </p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section><h3 className="mb-2 text-sm font-semibold text-ink">{title}</h3>{children}</section>;
}

function NumberedList({ items }: { items: string[] }) {
  return <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-soft">{items.map((text, i) => <li key={i}>{text}</li>)}</ol>;
}

function KeyValues({ title, values }: { title: string; values: Record<string, unknown> }) {
  const entries = Object.entries(values ?? {});
  if (!entries.length) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([key, value]) => (
          <span key={key} className="rounded-md bg-canvas px-2 py-1 font-mono text-xs"><span className="text-muted">{key}=</span><span className="text-ink">{typeof value === 'string' ? value : JSON.stringify(value)}</span></span>
        ))}
      </div>
    </div>
  );
}

function Code({ value }: { value: unknown }) {
  return <pre className="max-h-72 overflow-auto rounded-lg bg-gray-900 p-3 font-mono text-xs leading-relaxed text-gray-100">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>;
}

// --- Editing ---------------------------------------------------------------------------------------

const json = (value: unknown) => (value === null || value === undefined ? '' : JSON.stringify(value, null, 2));
const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);

function parse(label: string, text: string, fallback: unknown): unknown {
  if (!text.trim()) return fallback;
  try { return JSON.parse(text); } catch { throw new Error(`${label} is not valid JSON.`); }
}

function CaseEditor({ item, onDone, onSaved }: { item: TestCase; onDone: () => void; onSaved: () => void }) {
  const projectId = useProjectId();
  const toast = useToast();
  const c = item.content;
  const [form, setForm] = useState({
    title: item.title, objective: c.objective, category: item.category, priority: item.priority,
    preconditions: c.preconditions.join('\n'), auth: c.request.auth, pathParams: json(c.request.pathParams), query: json(c.request.query),
    headers: json(c.request.headers), body: json(c.request.body), bodyNote: c.request.bodyNote, status: String(c.expected.status ?? ''),
    responseSchema: c.expected.responseSchema, bodyChecks: json(c.expected.bodyChecks), notes: c.expected.notes,
    testData: c.testData, cleanup: c.cleanup.join('\n'), roles: (c.roles ?? []).join(', '), verifyUnchanged: c.verifyUnchanged ?? '',
  });
  const isRole = item.module === 'role';
  const [error, setError] = useState('');
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const save = useMutation({
    mutationFn: () => {
      const request: RequestSpec = {
        auth: form.auth as AuthMode, pathParams: parse('Path parameters', form.pathParams, {}) as Record<string, unknown>,
        query: parse('Query', form.query, {}) as Record<string, unknown>, headers: parse('Headers', form.headers, {}) as Record<string, string>,
        body: parse('Body', form.body, null), bodyNote: form.bodyNote,
      };
      const expected: ExpectedResult = {
        status: form.status ? Number(form.status) : null, responseSchema: form.responseSchema,
        bodyChecks: parse('Body checks', form.bodyChecks, []) as ExpectedResult['bodyChecks'], headers: c.expected.headers ?? {}, notes: form.notes,
      };
      return api.patch(`/projects/${projectId}/unit/cases/${item.id}`, {
        revision: item.revision, title: form.title, objective: form.objective, category: form.category, priority: form.priority,
        preconditions: lines(form.preconditions), request, expected, testData: form.testData, cleanup: lines(form.cleanup),
        ...(isRole ? { roles: form.roles.split(',').map((r) => r.trim()).filter(Boolean), verifyUnchanged: form.verifyUnchanged } : {}),
      });
    },
    onSuccess: () => { toast.success(`${item.code} saved and moved to review.`); onSaved(); onDone(); },
    onError: (e: Error) => setError(e.message),
  });
  return (
    <form className="space-y-5 px-6 py-5" onSubmit={(e) => { e.preventDefault(); setError(''); save.mutate(); }}>
      {item.status === 'approved' && <Alert tone="info">Saving moves this approved case back to review.</Alert>}
      <Field label="Title"><Input value={form.title} onChange={set('title')} required /></Field>
      <Field label="Objective"><Textarea rows={2} value={form.objective} onChange={set('objective')} /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={isRole ? 'Check' : 'Category'}><Select value={form.category} onChange={set('category')}>{Object.entries(isRole ? ROLE_KIND_LABEL : CATEGORY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
        <Field label="Priority"><Select value={form.priority} onChange={set('priority')}>{(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => <option key={p} value={p}>{PRIORITY_LABEL[p]}</option>)}</Select></Field>
      </div>
      {isRole && <Field label="Runs as roles" hint="Comma separated, exactly as in the roles file"><Input value={form.roles} onChange={set('roles')} /></Field>}
      <Field label="Preconditions" hint="One per line"><Textarea rows={3} value={form.preconditions} onChange={set('preconditions')} /></Field>

      <fieldset className="space-y-4 rounded-lg border border-line p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Request</legend>
        <Field label="Credentials"><Select value={form.auth} onChange={set('auth')}>{Object.entries(AUTH_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Path parameters (JSON)"><Textarea rows={3} className="font-mono text-xs" value={form.pathParams} onChange={set('pathParams')} placeholder="{}" /></Field>
          <Field label="Query (JSON)"><Textarea rows={3} className="font-mono text-xs" value={form.query} onChange={set('query')} placeholder="{}" /></Field>
          <Field label="Headers (JSON)"><Textarea rows={3} className="font-mono text-xs" value={form.headers} onChange={set('headers')} placeholder="{}" /></Field>
        </div>
        <Field label="Body (JSON)" hint="Leave empty for no body"><Textarea rows={6} className="font-mono text-xs" value={form.body} onChange={set('body')} /></Field>
        <Field label="Note about the data"><Input value={form.bodyNote} onChange={set('bodyNote')} /></Field>
      </fieldset>

      <fieldset className="space-y-4 rounded-lg border border-line p-4">
        <legend className="px-1 text-sm font-semibold text-ink">Expected result</legend>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Status code"><Input type="number" min={100} max={599} value={form.status} onChange={set('status')} /></Field>
          <Field label="Validate body against"><Select value={form.responseSchema} onChange={set('responseSchema')}>
            <option value="success">Success schema</option><option value="error">Error schema</option><option value="none">Nothing</option></Select></Field>
        </div>
        <Field label="Body checks (JSON)" hint={<>e.g. <code className="font-mono">[{'{'}"path": "$.name", "check": "equals", "value": "Rex"{'}'}]</code></>}>
          <Textarea rows={4} className="font-mono text-xs" value={form.bodyChecks} onChange={set('bodyChecks')} />
        </Field>
        <Field label="Notes"><Input value={form.notes} onChange={set('notes')} /></Field>
      </fieldset>

      {isRole && <Field label="Prove nothing changed" hint="For refused requests: how to read the record back"><Input value={form.verifyUnchanged} onChange={set('verifyUnchanged')} /></Field>}
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
