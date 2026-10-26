import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ChevronDown, Download, FileSpreadsheet, FileText, Sparkles } from 'lucide-react';
import { api } from '../lib/api';
import { useHelper, useProjectId } from '../lib/queries';
import { Alert, Button, Dialog, Field, Textarea, useToast } from './ui';

/** Download the project's cases as Excel or CSV for sign-off. */
export function ExportMenu({ module }: { module: 'unit' | 'flow' | 'role' }) {
  const projectId = useProjectId();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: MouseEvent) => ref.current && !ref.current.contains(event.target as Node) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);
  const href = (format: string, status: string, scope: string = module) => `/api/projects/${projectId}/export?module=${scope}&format=${format}&status=${status}`;
  const options = [
    { label: 'Excel — all cases', hint: 'Unit, flow and role cases, one sheet each', href: href('xlsx', 'all', 'all'), icon: <FileSpreadsheet className="size-4" /> },
    { label: 'Excel — approved only', hint: 'For sign-off', href: href('xlsx', 'approved', 'all'), icon: <FileSpreadsheet className="size-4" /> },
    { label: `CSV — ${module} cases`, hint: 'All statuses', href: href('csv', 'all'), icon: <FileText className="size-4" /> },
  ];
  return (
    <div className="relative" ref={ref}>
      <Button variant="secondary" icon={<Download className="size-4" />} onClick={() => setOpen(!open)}>Export <ChevronDown className="size-4" /></Button>
      {open && (
        <div className="absolute right-0 top-11 z-20 w-72 rounded-xl border border-line bg-surface p-1.5 shadow-lg animate-pop-in">
          {options.map((option) => (
            <a key={option.label} href={option.href} onClick={() => setOpen(false)} className="flex items-start gap-3 rounded-lg px-3 py-2 hover:bg-canvas">
              <span className="mt-0.5 text-brand-600">{option.icon}</span>
              <span><span className="block text-sm font-medium text-ink">{option.label}</span><span className="text-xs text-muted">{option.hint}</span></span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

/** Ask Claude to rewrite one case or flow, optionally with an instruction. */
export function RegenerateDialog({ caseId, code, reviewComment, onClose, onStarted }:
  { caseId: string; code: string; reviewComment?: string; onClose: () => void; onStarted: () => void }) {
  const projectId = useProjectId();
  const helper = useHelper();
  const toast = useToast();
  const [instruction, setInstruction] = useState('');
  const start = useMutation({
    mutationFn: () => api.post(`/projects/${projectId}/cases/${caseId}/regenerate`, { instruction }),
    onSuccess: () => { toast.success(`Claude is rewriting ${code} on your computer.`); onStarted(); onClose(); },
    onError: toast.error,
  });
  return (
    <Dialog title={`Regenerate ${code} with Claude`} onClose={onClose}
      description="Claude rewrites this case using the API contract, its review notes and your instruction. The result comes back for review."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button icon={<Sparkles className="size-4" />} loading={start.isPending} disabled={!helper.data?.connected} onClick={() => start.mutate()}>Regenerate</Button></>}>
      <div className="space-y-4">
        {!helper.data?.connected && <Alert tone="warning">Connect your computer first; Claude runs there.</Alert>}
        {reviewComment && <Alert tone="info" title="The reviewer's comment is included">{reviewComment}</Alert>}
        <Field label="What should change? (optional)" hint="e.g. 'Also assert the error code' or 'Check that the pet list no longer contains it'">
          <Textarea autoFocus rows={4} value={instruction} onChange={(e) => setInstruction(e.target.value)} maxLength={2000} />
        </Field>
      </div>
    </Dialog>
  );
}
