import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Check, CircleAlert, Download, LoaderCircle, MessageSquare, RotateCcw, Route, Send, Sparkles, X } from 'lucide-react';
import { api, type AssistantAction, type AssistantCaseRef, type AssistantDraft, type AssistantMessage, type AssistantState } from '../lib/api';
import { useProjectId } from '../lib/queries';
import { describeModels } from './ModelPicker';
import { Badge, Button, cx, useToast } from './ui';

const PAGES: Record<string, string> = { configuration: '', apis: 'apis', unit: 'unit-cases', flows: 'flow-cases', roles: 'role-cases',
  scripts: 'scripts', members: 'members', activity: 'activity' };
const PAGE_OF: Record<string, string> = { '': 'configuration', apis: 'apis', 'unit-cases': 'unit', 'flow-cases': 'flows', 'role-cases': 'roles',
  scripts: 'scripts', members: 'members', activity: 'activity' };
const STARTERS = ['What is not covered yet?', 'Summarise the AI review notes', 'Which flows need their results confirmed?'];
const MISSED = 'You missed this flow: ';

/** The project assistant: a button on every project page that opens a side panel. */
export function Assistant() {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState<string | null>(null);
  // Other parts of the page (e.g. "Draft flow" on a reviewer suggestion) hand the assistant a question.
  useEffect(() => {
    const listen = (event: Event) => { setQuestion((event as CustomEvent<string>).detail); setOpen(true); };
    window.addEventListener('assistant:ask', listen);
    return () => window.removeEventListener('assistant:ask', listen);
  }, []);
  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} aria-label="Open the project assistant"
          className="fixed bottom-6 right-6 z-30 inline-flex h-12 cursor-pointer items-center gap-2 rounded-full bg-brand-600 px-5 text-sm font-semibold text-white shadow-lg hover:bg-brand-700">
          <MessageSquare className="size-4" /> Ask
        </button>
      )}
      {open && <AssistantPanel question={question} onAsked={() => setQuestion(null)} onClose={() => setOpen(false)} />}
    </>
  );
}

function AssistantPanel({ question, onAsked, onClose }: { question: string | null; onAsked: () => void; onClose: () => void }) {
  const projectId = useProjectId();
  const client = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const [text, setText] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const key = ['project', projectId, 'assistant'];
  const state = useQuery({
    queryKey: key,
    queryFn: () => api.get<AssistantState>(`/projects/${projectId}/assistant`),
    refetchInterval: (query) => (query.state.data?.messages.some((m) => m.status === 'pending') ? 1500 : false),
  });
  const messages = state.data?.messages ?? [];
  const pending = messages.some((m) => m.status === 'pending');
  const page = PAGE_OF[location.pathname.split(`/projects/${projectId}`)[1]?.split('/')[1] ?? ''] ?? 'configuration';
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [messages.length, pending]);
  // A handed-over question is sent once the conversation has loaded; without a helper it waits in the input.
  useEffect(() => {
    if (!question || !state.data) return;
    if (state.data.helperConnected && !pending) send.mutate(question);
    else setText(question);
    onAsked();
  }, [question, state.data]);

  // Answers that change data (an approval, an added flow) refresh the pages behind the panel too.
  const done = (result: AssistantState) => {
    client.setQueryData(key, result);
    void client.invalidateQueries({ queryKey: ['project', projectId], predicate: (q) => q.queryKey[2] !== 'assistant' });
    if (result.download) window.location.assign(result.download);
    if (result.navigate !== undefined) navigate(`/projects/${projectId}/${PAGES[result.navigate] ?? ''}`);
  };
  const call = useMutation({ mutationFn: (path: string) => api.post<AssistantState>(`/projects/${projectId}/assistant/${path}`), onSuccess: done, onError: toast.error });
  const send = useMutation({
    mutationFn: (question: string) => api.post<AssistantState>(`/projects/${projectId}/assistant/messages`, { text: question, context: { page } }),
    onSuccess: (result) => { setText(''); client.setQueryData(key, result); },
    onError: toast.error,
  });
  const clear = useMutation({ mutationFn: () => api.delete<AssistantState>(`/projects/${projectId}/assistant/messages`), onSuccess: done, onError: toast.error });
  const ask = (question: string) => question.trim() && !pending && send.mutate(question.trim());
  const openCase = (ref: AssistantCaseRef) => {
    const where = ref.module === 'flow' ? `flow-cases?open=${ref.id}`
      : ref.module === 'unit' ? (ref.endpointId ? `unit-cases/${ref.endpointId}` : 'unit-cases')
        : (ref.endpointId ? `role-cases/${ref.endpointId}` : 'role-cases');
    navigate(`/projects/${projectId}/${where}`);
  };

  const connected = state.data?.helperConnected ?? false;
  return (
    <aside aria-label="Project assistant"
      className="fixed bottom-6 right-6 z-40 flex h-[min(680px,calc(100vh-6rem))] w-[min(420px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl animate-pop-in">
      <header className="flex items-center gap-3 bg-brand-700 px-4 py-3 text-white">
        <span className="flex size-9 items-center justify-center rounded-xl bg-white/15"><MessageSquare className="size-5" /></span>
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 text-[15px] font-semibold">
            Project assistant
            <span className="rounded-full bg-white/20 px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide">Beta</span>
          </p>
          <p className="text-xs text-white/80">{connected ? 'Answers from this project · runs on your computer' : 'Your Local Helper is not running'}</p>
        </div>
        {messages.length > 0 && (
          <button onClick={() => clear.mutate()} title="Start a new conversation" aria-label="Start a new conversation"
            className="cursor-pointer rounded-lg p-1.5 text-white/90 hover:bg-white/15"><RotateCcw className="size-4" /></button>
        )}
        <button onClick={onClose} aria-label="Close the assistant" className="cursor-pointer rounded-lg p-1.5 text-white/90 hover:bg-white/15"><X className="size-5" /></button>
      </header>

      <>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-canvas/60 px-4 py-4">
            {messages.length === 0 && <Welcome onPick={(q) => (q === MISSED ? setText(MISSED) : ask(q))} />}
            {messages.map((message, index) => message.role === 'user'
              ? <div key={message.id} className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand-600 px-3.5 py-2.5 text-sm text-white">{message.text}</div>
              : <Reply key={message.id} message={message} busy={call.isPending} onCase={openCase} onAsk={ask}
                  onRetry={() => ask(messages[index - 1]?.text ?? '')} onCall={(path) => call.mutate(`messages/${message.id}/${path}`)} />)}
            {messages.length > 0 && <div ref={end} />}
          </div>
          <footer className="space-y-2.5 border-t border-line bg-surface px-4 pb-3 pt-2.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="ml-auto text-[11px] text-muted">Asking from: {page}</span>
            </div>
            {!connected && <p className="text-xs text-amber-800">Start the Local Helper on your computer to ask questions.</p>}
            <div className="flex items-end gap-2">
              <label htmlFor="assistant-input" className="sr-only">Ask the assistant</label>
              <textarea id="assistant-input" rows={1} value={text} onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(text); } }}
                placeholder="Type your message…"
                className="max-h-32 min-h-11 min-w-0 flex-1 resize-none rounded-full border border-line-strong bg-surface px-4 py-2.5 text-sm text-ink outline-none focus:border-brand-600" />
              <button onClick={() => ask(text)} disabled={!text.trim() || pending || send.isPending || !connected} aria-label="Send"
                className="flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-full bg-brand-700 text-white hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-40">
                {send.isPending ? <LoaderCircle className="size-4 animate-spin" /> : <Send className="size-4" />}
              </button>
            </div>
            <p className="text-center text-[11px] text-muted">Actions run only after you confirm them.</p>
          </footer>
      </>
    </aside>
  );
}

function Welcome({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-2 py-6 text-center">
      <MessageSquare className="size-12 text-gray-300" strokeWidth={1.5} />
      <div className="space-y-1">
        <p className="text-base font-semibold text-ink-soft">How can I help you?</p>
        <p className="text-sm text-muted">Ask about this project's API and test cases, ask for an action, or describe a flow the AI missed.</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {[...STARTERS, MISSED].map((q) => (
          <button key={q} onClick={() => onPick(q)}
            className="cursor-pointer rounded-full border border-brand-500/30 bg-brand-50 px-3.5 py-1.5 text-sm font-medium text-brand-700 hover:bg-brand-100">
            {q === MISSED ? 'I found a flow you missed…' : q}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The answer text with case codes turned into links. Paragraphs and "- " lists only. */
function AnswerText({ text, cases, onCase }: { text: string; cases: AssistantCaseRef[]; onCase: (ref: AssistantCaseRef) => void }) {
  const byCode = new Map(cases.map((c) => [c.code, c]));
  const inline = (line: string) => line.split(/(TC-\d{4,})/g).map((part, i) => {
    const ref = byCode.get(part);
    return ref ? <button key={i} onClick={() => onCase(ref)} title={ref.title} className="cursor-pointer rounded bg-brand-50 px-1 font-medium text-brand-700 hover:bg-brand-100">{part}</button> : part;
  });
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) blocks.push(<ul key={blocks.length} className="list-disc space-y-0.5 pl-5">{list.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>); list = []; };
  for (const line of text.split('\n')) {
    if (/^\s*[-*]\s+/.test(line)) list.push(line.replace(/^\s*[-*]\s+/, ''));
    else { flush(); if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>); }
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed text-ink">{blocks}</div>;
}

function Reply({ message, busy, onCase, onAsk, onRetry, onCall }: { message: AssistantMessage; busy: boolean; onCase: (ref: AssistantCaseRef) => void;
  onAsk: (q: string) => void; onRetry: () => void; onCall: (path: string) => void }) {
  if (message.status === 'pending') {
    return <p className="flex items-center gap-2 text-sm text-muted"><LoaderCircle className="size-4 animate-spin text-brand-600" />{message.progress || 'Thinking on your computer…'}</p>;
  }
  if (message.status === 'failed') {
    return (
      <div className="space-y-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-800">
        <p className="flex items-start gap-2"><CircleAlert className="mt-0.5 size-4 shrink-0" />{message.error}</p>
        <button onClick={onRetry} className="inline-flex cursor-pointer items-center gap-1 text-xs font-medium hover:underline"><RotateCcw className="size-3.5" /> Ask again</button>
      </div>
    );
  }
  const cases = message.cases ?? [];
  return (
    <div className="max-w-[96%] space-y-3">
      <AnswerText text={message.text} cases={[...cases, ...(message.actions ?? []).flatMap((a) => a.cases)]} onCase={onCase} />
      {(message.actions ?? []).map((action, i) => <ActionCard key={i} action={action} busy={busy} onCase={onCase}
        onConfirm={() => onCall(`actions/${i}`)} onDismiss={() => onCall(`actions/${i}/dismiss`)} />)}
      {(message.drafts ?? []).map((draft, i) => <DraftCard key={i} draft={draft} busy={busy}
        onAdd={() => onCall(`drafts/${i}/accept`)} onDiscard={() => onCall(`drafts/${i}/discard`)} />)}
      {message.draftError && <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">{message.draftError}</p>}
      {(message.followUps ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {message.followUps!.map((q) => <button key={q} onClick={() => onAsk(q)} className="cursor-pointer rounded-full border border-line-strong bg-surface px-3 py-1 text-xs text-ink-soft hover:bg-canvas">{q}</button>)}
        </div>
      )}
      {message.models && message.models.length > 0 && <p className="text-[11px] text-muted">Answered on {describeModels(message.models)}</p>}
    </div>
  );
}

const ACTION_ICON = { review: Check, regenerate: Sparkles, fill_gaps: Route, export: Download, open: ArrowRight };

function ActionCard({ action, busy, onCase, onConfirm, onDismiss }: { action: AssistantAction; busy: boolean; onCase: (ref: AssistantCaseRef) => void;
  onConfirm: () => void; onDismiss: () => void }) {
  const Icon = ACTION_ICON[action.kind] ?? Check;
  const unconfirmed = action.kind === 'review' && action.reviewAction === 'approve' ? action.cases.filter((c) => c.needsConfirmation).length : 0;
  return (
    <section aria-label="Proposed action" className={cx('overflow-hidden rounded-xl border bg-surface', action.state === 'proposed' ? 'border-brand-500/40' : 'border-line')}>
      <p className="flex items-center gap-2 bg-brand-50 px-3.5 py-2 text-sm font-semibold text-brand-700"><Icon className="size-4" />{action.title}</p>
      <div className="space-y-2 px-3.5 py-2.5 text-sm">
        {action.cases.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {action.cases.slice(0, 24).map((c) => (
              <button key={c.id} onClick={() => onCase(c)} title={c.title} className="cursor-pointer rounded-md bg-canvas px-1.5 py-0.5 text-xs font-medium text-ink-soft hover:bg-gray-100">{c.code}</button>
            ))}
            {action.cases.length > 24 && <span className="text-xs text-muted">+{action.cases.length - 24}</span>}
          </div>
        )}
        {action.comment && <p className="text-xs text-ink-soft">Comment: {action.comment}</p>}
        {action.instruction && <p className="text-xs text-ink-soft">Instruction: {action.instruction}</p>}
        {unconfirmed > 0 && <p className="text-xs text-amber-800">{unconfirmed} of them include results the spec does not state exactly. Approving confirms them.</p>}
        {action.state === 'done' && <p className="flex items-center gap-1.5 text-xs font-medium text-emerald-700"><Check className="size-3.5" />{action.result}</p>}
        {action.state === 'dismissed' && <p className="text-xs text-muted">Dismissed</p>}
      </div>
      {action.state === 'proposed' && (
        <div className="flex gap-2 border-t border-line px-3.5 py-2.5">
          <Button size="sm" loading={busy} onClick={onConfirm}>Confirm</Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={onDismiss}>Cancel</Button>
        </div>
      )}
    </section>
  );
}

function DraftCard({ draft, busy, onAdd, onDiscard }: { draft: AssistantDraft; busy: boolean; onAdd: () => void; onDiscard: () => void }) {
  return (
    <article className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="space-y-2 px-3.5 py-3">
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="brand">{draft.area || 'Cross-area journeys'}</Badge>
          <Badge tone="purple">{draft.type.replaceAll('_', ' ')}</Badge>
          <Badge tone="gray">{draft.priority}</Badge>
          {draft.needsConfirmation && <Badge tone="amber">Confirm results</Badge>}
        </div>
        <p className="text-sm font-semibold text-ink">{draft.title}</p>
        {draft.objective && <p className="text-xs text-ink-soft">{draft.objective}</p>}
        <div className="flex flex-wrap items-center gap-1">
          {draft.steps.map((step, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-xs text-faint">→</span>}
              <span className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">{step}</span>
            </span>
          ))}
        </div>
        <p className="text-xs text-muted">{draft.steps.length} steps · passed the code checks (real operations, documented statuses, IDs from earlier steps)</p>
        {draft.needsConfirmation && draft.confirmationNote && <p className="text-xs text-amber-800">{draft.confirmationNote}</p>}
        {draft.state === 'added' && <p className="flex items-center gap-1.5 text-xs font-medium text-emerald-700"><Check className="size-3.5" />Added as {draft.caseCode} · in review</p>}
        {draft.state === 'discarded' && <p className="text-xs text-muted">Discarded</p>}
      </div>
      {draft.state === 'pending' && (
        <div className="flex gap-2 border-t border-line px-3.5 py-2.5">
          <Button size="sm" loading={busy} onClick={onAdd}>Add to flows</Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={onDiscard}>Discard</Button>
        </div>
      )}
    </article>
  );
}
