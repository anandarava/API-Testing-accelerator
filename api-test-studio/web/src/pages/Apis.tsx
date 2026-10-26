import { useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileUp, Lock, Search, Upload } from 'lucide-react';
import { api, type EndpointDetail, type EndpointSummary, type Spec } from '../lib/api';
import { keys, useEndpoints, useProjectId } from '../lib/queries';
import { formatLabel, plural, timeAgo } from '../lib/format';
import { SchemaView } from '../components/SchemaView';
import { Alert, Badge, Button, Card, Drawer, EmptyState, Input, MethodBadge, PageHeader, Spinner, cx, useToast } from '../components/ui';

export function useUpload() {
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (file: File) => api.upload<Spec>(`/projects/${projectId}/specs`, file),
    onSuccess: (spec) => {
      void client.invalidateQueries({ queryKey: ['project', projectId] });
      void client.invalidateQueries({ queryKey: keys.projects });
      toast.success(`Imported ${spec.title || spec.filename}: ${plural(spec.endpointCount, 'endpoint')}.`);
    },
    onError: toast.error,
  });
}

export function ApisPage() {
  const endpoints = useEndpoints();
  const upload = useUpload();
  const fileInput = useRef<HTMLInputElement>(null);
  const pick = () => fileInput.current?.click();
  const hidden = <input ref={fileInput} type="file" accept=".json,.yaml,.yml" className="hidden" onChange={(e) => { const file = e.target.files?.[0]; if (file) upload.mutate(file); e.target.value = ''; }} />;

  if (endpoints.isPending) return <Spinner />;
  const spec = endpoints.data?.spec;
  if (!spec) {
    return (
      <>
        <PageHeader title="APIs" description="Upload the OpenAPI or Swagger file for the API you want to test." />
        <DropZone onFile={(file) => upload.mutate(file)} onPick={pick} loading={upload.isPending} />
        {hidden}
      </>
    );
  }
  const changes = spec.changes;
  const hasChanges = changes.added?.length || changes.removed?.length || changes.changed?.length;
  return (
    <>
      <PageHeader
        title={spec.title || 'APIs'}
        description={<>{formatLabel(spec.format)} · API version {spec.apiVersion || '—'} · {plural(spec.endpointCount, 'endpoint')} · upload #{spec.version}, {timeAgo(spec.createdAt)}</>}
        action={<Button variant="secondary" icon={<Upload className="size-4" />} loading={upload.isPending} onClick={pick}>Upload new version</Button>}
      />
      {hidden}
      <div className="mb-6 space-y-3">
        {hasChanges ? (
          <Alert tone="info" title={`What changed in upload #${spec.version}`}>
            {[changes.added?.length && `${changes.added.length} added`, changes.changed?.length && `${changes.changed.length} changed`, changes.removed?.length && `${changes.removed.length} removed`].filter(Boolean).join(' · ')}
          </Alert>
        ) : null}
        {spec.warnings.length > 0 && <Alert tone="warning" title="Notes from import">{spec.warnings.join(' ')}</Alert>}
      </div>
      <EndpointList endpoints={endpoints.data?.endpoints ?? []} />
    </>
  );
}

function DropZone({ onFile, onPick, loading }: { onFile: (file: File) => void; onPick: () => void; loading: boolean }) {
  const [over, setOver] = useState(false);
  const drop = (event: DragEvent) => { event.preventDefault(); setOver(false); const file = event.dataTransfer.files[0]; if (file) onFile(file); };
  return (
    <Card>
      <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
        className={cx('m-2 rounded-lg border-2 border-dashed transition-colors', over ? 'border-brand-500 bg-brand-50' : 'border-line')}>
        <EmptyState icon={<FileUp className="size-6" />} title="Drop your API spec here"
          description="OpenAPI 3.x or Swagger 2.0, as a single JSON or YAML file up to 10 MB. External $ref files must be bundled first."
          action={<Button loading={loading} icon={<Upload className="size-4" />} onClick={onPick}>Choose file</Button>} />
      </div>
    </Card>
  );
}

function EndpointList({ endpoints }: { endpoints: EndpointSummary[] }) {
  const [query, setQuery] = useState('');
  const [method, setMethod] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const methods = useMemo(() => [...new Set(endpoints.map((e) => e.method))], [endpoints]);
  const groups = useMemo(() => {
    const text = query.trim().toLowerCase();
    const visible = endpoints.filter((e) => (!method || e.method === method) &&
      (!text || `${e.method} ${e.path} ${e.summary} ${e.operationId} ${e.tags.join(' ')}`.toLowerCase().includes(text)));
    const byTag = new Map<string, EndpointSummary[]>();
    for (const endpoint of visible) {
      const tag = endpoint.tags[0] ?? 'Other';
      byTag.set(tag, [...(byTag.get(tag) ?? []), endpoint]);
    }
    return [...byTag.entries()];
  }, [endpoints, query, method]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <Input className="pl-9" placeholder="Search by path, name or tag" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={!method} onClick={() => setMethod(null)}>All</FilterChip>
          {methods.map((m) => <FilterChip key={m} active={method === m} onClick={() => setMethod(method === m ? null : m)}>{m}</FilterChip>)}
        </div>
      </div>
      {groups.length === 0 ? <Card><p className="px-5 py-10 text-center text-sm text-muted">No endpoints match your search.</p></Card> : (
        <div className="space-y-5">
          {groups.map(([tag, items]) => (
            <Card key={tag}>
              <div className="flex items-center justify-between border-b border-line px-5 py-3">
                <h3 className="text-sm font-semibold text-ink">{tag}</h3>
                <span className="text-xs text-muted">{plural(items.length, 'endpoint')}</span>
              </div>
              <ul className="divide-y divide-line">
                {items.map((endpoint) => (
                  <li key={endpoint.id}>
                    <button onClick={() => setSelected(endpoint.id)} className="flex w-full cursor-pointer items-center gap-4 px-5 py-3 text-left hover:bg-canvas">
                      <MethodBadge method={endpoint.method} />
                      <span className={cx('min-w-0 truncate font-mono text-[13px] text-ink', endpoint.deprecated && 'line-through opacity-60')}>{endpoint.path}</span>
                      <span className="ml-auto hidden truncate text-sm text-muted sm:block">{endpoint.summary}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
      {selected && <EndpointDrawer endpointId={selected} onClose={() => setSelected(null)} />}
    </>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button onClick={onClick} className={cx('h-8 cursor-pointer rounded-full border px-3 text-xs font-medium transition-colors',
      active ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}>{children}</button>
  );
}

function statusTone(status: string) {
  if (status.startsWith('2')) return 'green' as const;
  if (status.startsWith('3')) return 'blue' as const;
  if (status.startsWith('4')) return 'amber' as const;
  if (status.startsWith('5')) return 'red' as const;
  return 'gray' as const;
}

function EndpointDrawer({ endpointId, onClose }: { endpointId: string; onClose: () => void }) {
  const projectId = useProjectId();
  const detail = useQuery({ queryKey: ['endpoint', endpointId], queryFn: () => api.get<EndpointDetail>(`/projects/${projectId}/endpoints/${endpointId}`) });
  const [tab, setTab] = useState<'request' | 'responses'>('request');
  const [status, setStatus] = useState<string | null>(null);
  const endpoint = detail.data;
  const statuses = endpoint ? Object.keys(endpoint.responses) : [];
  const activeStatus = status ?? statuses[0];
  const response = endpoint && activeStatus ? endpoint.responses[activeStatus] : undefined;

  return (
    <Drawer onClose={onClose}
      title={endpoint ? <div className="flex items-center gap-3"><MethodBadge method={endpoint.method} /><span className="truncate font-mono text-sm font-medium text-ink">{endpoint.path}</span></div> : 'Loading…'}
      subtitle={endpoint?.summary}>
      {!endpoint ? <Spinner /> : (
        <div className="space-y-6 px-6 py-5">
          <div className="space-y-3">
            {endpoint.description && <p className="whitespace-pre-line text-sm leading-relaxed text-ink-soft">{endpoint.description}</p>}
            <div className="flex flex-wrap gap-2">
              <Badge>operationId: {endpoint.operationId}</Badge>
              {endpoint.security.length > 0 && endpoint.security.some((s) => Object.keys(s).length) ? (
                <Badge tone="purple"><Lock className="size-3" /> {endpoint.security.map((s) => Object.keys(s).join(' + ')).filter(Boolean).join(' or ')}</Badge>
              ) : <Badge>No authentication</Badge>}
              {endpoint.deprecated && <Badge tone="amber">Deprecated</Badge>}
            </div>
          </div>

          <div className="flex gap-1 rounded-lg bg-canvas p-1">
            {(['request', 'responses'] as const).map((value) => (
              <button key={value} onClick={() => setTab(value)} className={cx('h-8 flex-1 cursor-pointer rounded-md text-sm font-medium capitalize',
                tab === value ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink')}>{value === 'responses' ? `Responses (${statuses.length})` : 'Request'}</button>
            ))}
          </div>

          {tab === 'request' ? (
            <div className="space-y-6">
              <Section title="Parameters">
                {endpoint.parameters.length === 0 ? <p className="text-sm text-muted">No path, query or header parameters.</p> : (
                  <div className="overflow-hidden rounded-lg border border-line">
                    <table className="w-full text-sm">
                      <thead className="bg-canvas text-left text-xs text-muted"><tr><th className="px-4 py-2 font-medium">Name</th><th className="px-4 py-2 font-medium">In</th><th className="px-4 py-2 font-medium">Type</th><th className="px-4 py-2 font-medium">Description</th></tr></thead>
                      <tbody className="divide-y divide-line">
                        {endpoint.parameters.map((p) => (
                          <tr key={`${p.in}-${p.name}`} className="align-top">
                            <td className="px-4 py-2.5"><span className="font-mono text-[13px] font-medium text-ink">{p.name}</span>{p.required && <span className="ml-1.5 text-[10px] font-semibold uppercase text-red-600">req</span>}</td>
                            <td className="px-4 py-2.5 text-muted">{p.in}</td>
                            <td className="px-4 py-2.5 font-mono text-xs text-brand-700">{[p.schema.type, p.schema.format].filter(Boolean).join(' · ') || 'any'}{p.schema.enum ? ` (${p.schema.enum.join(', ')})` : ''}</td>
                            <td className="px-4 py-2.5 text-muted">{p.description || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Section>
              <Section title="Request body" meta={endpoint.requestBody ? <>{endpoint.requestBody.mediaType}{endpoint.requestBody.required && <Badge tone="red" className="ml-2">required</Badge>}</> : undefined}>
                {endpoint.requestBody ? <SchemaView schema={endpoint.requestBody.schema} /> : <p className="text-sm text-muted">This endpoint has no request body.</p>}
                {endpoint.requestBody?.example != null && <Example value={endpoint.requestBody.example} />}
              </Section>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {statuses.map((code) => (
                  <button key={code} onClick={() => setStatus(code)} className={cx('cursor-pointer rounded-lg border px-3 py-1.5 text-sm font-medium',
                    code === activeStatus ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-line bg-surface text-ink-soft hover:bg-canvas')}>{code}</button>
                ))}
              </div>
              {response && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2"><Badge tone={statusTone(activeStatus!)}>{activeStatus}</Badge><span className="text-sm text-ink-soft">{response.description || 'No description'}</span></div>
                  <SchemaView schema={response.schema} emptyText="No response body documented." />
                  {response.example != null && <Example value={response.example} />}
                  {response.headers.length > 0 && <p className="text-sm text-muted">Headers: <span className="font-mono">{response.headers.join(', ')}</span></p>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}

function Section({ title, meta, children }: { title: string; meta?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2.5">
      <div className="flex items-center justify-between"><h3 className="text-sm font-semibold text-ink">{title}</h3><span className="flex items-center text-xs text-muted">{meta}</span></div>
      {children}
    </section>
  );
}

function Example({ value }: { value: unknown }) {
  return (
    <details className="mt-3 rounded-lg border border-line">
      <summary className="cursor-pointer px-4 py-2 text-sm font-medium text-ink-soft">Example</summary>
      <pre className="overflow-x-auto border-t border-line bg-gray-900 p-4 font-mono text-xs leading-relaxed text-gray-100">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
