import { useEffect, useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Check, Laptop, LoaderCircle, Unplug } from 'lucide-react';
import { api, type HelperState } from '../lib/api';
import { keys, useHelper } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { Alert, Button, CommandLine, Dialog, cx, useToast } from './ui';
import { describeModels, modelLabel } from './ModelPicker';

const plans: Record<string, string> = { pro: 'Pro', max: 'Max', team: 'Team', enterprise: 'Enterprise', free: 'Free' };

export function claudeLabel(state: HelperState | undefined): string {
  const claude = state?.claude;
  if (!claude) return '';
  if (!claude.installed) return 'Claude Code not installed';
  if (!claude.loggedIn) return 'Claude not signed in';
  return `Claude ${plans[claude.subscriptionType] ?? claude.subscriptionType ?? ''}`.trim();
}

export function HelperChip() {
  const { data } = useHelper();
  const [open, setOpen] = useState(false);
  const ready = data?.connected && data.claude?.loggedIn;
  const warn = data?.connected && !data.claude?.loggedIn;
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={cx('inline-flex h-8 cursor-pointer items-center gap-2 rounded-full border px-3 text-xs font-medium transition-colors',
          ready ? 'border-emerald-200 bg-emerald-50 text-emerald-800 hover:bg-emerald-100'
            : warn ? 'border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100'
              : 'border-line-strong bg-surface text-ink-soft hover:bg-canvas')}
      >
        <span className={cx('size-2 rounded-full', ready ? 'bg-emerald-500' : warn ? 'bg-amber-500' : 'bg-gray-300')} />
        {data?.connected ? <>Computer connected<span className="hidden opacity-70 sm:inline">· {claudeLabel(data)}</span></> : 'Connect your computer'}
      </button>
      {open && <HelperDialog onClose={() => setOpen(false)} />}
    </>
  );
}

export function HelperDialog({ onClose }: { onClose: () => void }) {
  const { data: state } = useHelper();
  const client = useQueryClient();
  const toast = useToast();
  const [code, setCode] = useState<string | null>(null);
  const createCode = useMutation({
    mutationFn: () => api.post<{ code: string }>('/me/helper/pairing-code'),
    onSuccess: (result) => setCode(result.code),
    onError: toast.error,
  });
  const disconnect = useMutation({
    mutationFn: () => api.delete('/me/helper'),
    onSuccess: () => { setCode(null); void client.invalidateQueries({ queryKey: keys.helper }); toast.success('This computer was disconnected.'); },
    onError: toast.error,
  });

  useEffect(() => {
    if (!state?.paired && !code && !createCode.isPending) createCode.mutate();
  }, [state?.paired]);

  const python = navigator.userAgent.includes('Windows') ? '.venv\\Scripts\\python' : '.venv/bin/python';
  const server = window.location.origin;

  if (state?.connected) {
    const claude = state.claude;
    return (
      <Dialog title="Your computer is connected" onClose={onClose}
        footer={<><Button variant="secondary" icon={<Unplug className="size-4" />} loading={disconnect.isPending} onClick={() => disconnect.mutate()}>Disconnect</Button><Button onClick={onClose}>Done</Button></>}>
        <div className="space-y-4">
          <div className="flex items-center gap-3 rounded-xl border border-line p-4">
            <div className="flex size-10 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600"><Laptop className="size-5" /></div>
            <div className="min-w-0 text-sm">
              <p className="font-medium text-ink">{state.hostname || 'This computer'}</p>
              <p className="text-muted">Local Helper {state.helperVersion} · last seen {timeAgo(state.lastSeen)}</p>
            </div>
          </div>
          {claude?.loggedIn ? (
            <Alert tone="success" title={`Claude Code ${claude.version} is ready`}>Signed in as {claude.email} ({plans[claude.subscriptionType] ?? claude.subscriptionType} plan). Test design and script generation will use this account.</Alert>
          ) : (
            <Alert tone="warning" title="Claude is not ready on this computer">
              {claude?.error || 'Install Claude Code and sign in.'} Then run <code className="font-mono">claude auth login</code> in a terminal.
            </Alert>
          )}
          <p className="text-sm text-muted">
            Jobs you start in the portal run on this computer, using your Claude account and your local framework folder.
            Model: <span className="font-medium text-ink-soft">{modelLabel(state.model.claudeModel)}</span>
            {state.model.lastModels.length > 0 && <> · last job ran on <span className="font-medium text-ink-soft">{describeModels(state.model.lastModels)}</span></>}.
            Change it with the <span className="font-medium text-ink-soft">Model</span> menu in the top bar.
          </p>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title="Connect your computer" width="max-w-xl" onClose={onClose}
      description="The Local Helper runs on your computer. It uses your own Claude account and reads your framework folder. Nothing runs on the server."
      footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <ol className="space-y-5">
        <Step number={1} title="Sign in to Claude Code on this computer">
          Skip this if you have done it before.
          <CommandLine command="claude auth login" />
        </Step>
        <Step number={2} title="Pair this computer">
          {state?.paired && !code ? (
            <span className="mt-1 flex items-center gap-2">
              <Check className="size-4 text-emerald-600" />
              <span>This computer is already paired, so you can skip to step 3.{' '}
                <button className="cursor-pointer font-medium text-brand-600 hover:underline" onClick={() => createCode.mutate()}>Pair again</button>
              </span>
            </span>
          ) : (
            <>
              In a terminal, open the <span className="font-medium text-ink-soft">api-test-studio</span> folder and run:
              {code ? <CommandLine command={`${python} -m helper pair ${code} --server ${server}`} />
                : <div className="flex h-11 items-center gap-2 text-sm text-muted"><LoaderCircle className="size-4 animate-spin" /> Creating a pairing code…</div>}
              <span className="block">The code works once and expires in 10 minutes. <button className="cursor-pointer font-medium text-brand-600 hover:underline" onClick={() => createCode.mutate()}>New code</button></span>
            </>
          )}
        </Step>
        <Step number={3} title="Start the helper and keep the terminal open">
          <CommandLine command={`${python} -m helper start`} />
        </Step>
      </ol>
      <div className="mt-6 flex items-center gap-2 rounded-lg bg-canvas px-4 py-3 text-sm text-muted">
        {state?.paired ? <><LoaderCircle className="size-4 animate-spin text-brand-600" /> Paired. Waiting for the helper to start…</>
          : <><LoaderCircle className="size-4 animate-spin" /> Waiting for this computer to connect…</>}
      </div>
    </Dialog>
  );
}

function Step({ number, title, children }: { number: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-4">
      <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-sm font-semibold text-brand-700">{number}</span>
      <div className="min-w-0 flex-1 space-y-2 text-sm text-muted">
        <p className="font-medium text-ink">{title}</p>
        {children}
      </div>
    </li>
  );
}

