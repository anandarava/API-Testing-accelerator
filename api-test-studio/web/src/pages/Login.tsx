import { useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { FileCode, ListChecks, Workflow } from 'lucide-react';
import { api, type User } from '../lib/api';
import { keys, useMe } from '../lib/queries';
import { Logo } from '../components/AppShell';
import { Alert, Button, Field, Input } from '../components/ui';

export function LoginPage() {
  const me = useMe();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const client = useQueryClient();
  const navigate = useNavigate();
  const submit = useMutation({
    mutationFn: () => mode === 'login'
      ? api.post<User>('/auth/login', { email: form.email, password: form.password })
      : api.post<User>('/auth/register', form),
    onSuccess: (user) => { client.setQueryData(keys.me, user); navigate('/'); },
  });

  if (me.data) return <Navigate to="/" replace />;

  const onSubmit = (event: FormEvent) => { event.preventDefault(); submit.mutate(); };
  const set = (field: keyof typeof form) => (event: ChangeEvent<HTMLInputElement>) => setForm({ ...form, [field]: event.target.value });

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-gradient-to-br from-brand-700 to-indigo-900 p-12 text-white lg:flex">
        <span className="flex items-center gap-2.5 text-lg font-semibold"><img src="/favicon.svg" alt="" className="size-8 rounded-lg ring-2 ring-white/20" /> API Test Studio</span>
        <div>
          <h1 className="max-w-md text-4xl font-semibold leading-tight tracking-tight">From OpenAPI to reviewed Playwright tests, in your own framework.</h1>
          <ul className="mt-10 space-y-5 text-indigo-100">
            <Point icon={<ListChecks className="size-5" />} title="Unit test cases" text="Every scenario a senior API tester would write, for each endpoint." />
            <Point icon={<Workflow className="size-5" />} title="Flow test cases" text="End-to-end journeys built from how your APIs work together." />
            <Point icon={<FileCode className="size-5" />} title="Scripts in your framework" text="Approved cases become TypeScript tests that follow your team's conventions." />
          </ul>
        </div>
        <p className="text-sm text-indigo-200">Runs with your own Claude account on your computer.</p>
      </div>

      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h2 className="text-2xl font-semibold tracking-tight text-ink">{mode === 'login' ? 'Welcome back' : 'Create your account'}</h2>
          <p className="mt-1.5 text-sm text-muted">{mode === 'login' ? 'Sign in to continue to your projects.' : 'Your lead can add you to projects once you have an account.'}</p>
          <form className="mt-8 space-y-4" onSubmit={onSubmit}>
            {mode === 'register' && <Field label="Full name"><Input required autoFocus value={form.name} onChange={set('name')} placeholder="Priya Sharma" /></Field>}
            <Field label="Work email"><Input required type="email" autoFocus={mode === 'login'} value={form.email} onChange={set('email')} placeholder="you@company.com" autoComplete="email" /></Field>
            <Field label="Password" hint={mode === 'register' ? 'At least 8 characters.' : undefined}>
              <Input required type="password" minLength={mode === 'register' ? 8 : undefined} value={form.password} onChange={set('password')} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
            </Field>
            {submit.error && <Alert tone="error">{submit.error.message}</Alert>}
            <Button type="submit" className="w-full" loading={submit.isPending}>{mode === 'login' ? 'Sign in' : 'Create account'}</Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted">
            {mode === 'login' ? 'New here? ' : 'Already have an account? '}
            <button className="cursor-pointer font-medium text-brand-600 hover:underline" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); submit.reset(); }}>
              {mode === 'login' ? 'Create an account' : 'Sign in'}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}

function Point({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <li className="flex gap-4">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-white/10">{icon}</span>
      <span><span className="block font-medium text-white">{title}</span><span className="text-sm">{text}</span></span>
    </li>
  );
}
