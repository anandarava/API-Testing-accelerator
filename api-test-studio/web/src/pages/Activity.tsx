import type { ReactNode } from 'react';
import { FileCode, FileUp, FolderCog, History, ListChecks, Settings, UserCog, Users, Workflow } from 'lucide-react';
import { useActivity } from '../lib/queries';
import { timeAgo } from '../lib/format';
import { Card, EmptyState, PageHeader, Spinner } from '../components/ui';

function iconFor(action: string): ReactNode {
  if (action.startsWith('spec.')) return <FileUp className="size-4" />;
  if (action.startsWith('unit.')) return <ListChecks className="size-4" />;
  if (action.startsWith('scripts.')) return <FileCode className="size-4" />;
  if (action.startsWith('flows.')) return <Workflow className="size-4" />;
  if (action.startsWith('framework.')) return <FolderCog className="size-4" />;
  if (action === 'member.role_changed') return <UserCog className="size-4" />;
  if (action.startsWith('member.')) return <Users className="size-4" />;
  return <Settings className="size-4" />;
}

export function ActivityPage() {
  const activity = useActivity(200);
  return (
    <>
      <PageHeader title="Activity" description="Everything that happened in this project, newest first." />
      <Card>
        {activity.isPending ? <Spinner /> : !activity.data?.length ? (
          <EmptyState icon={<History className="size-6" />} title="No activity yet" description="Uploads, reviews and changes will appear here." />
        ) : (
          <ul className="divide-y divide-line">
            {activity.data.map((item) => (
              <li key={item.id} className="flex items-start gap-4 px-5 py-3.5">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-canvas text-muted">{iconFor(item.action)}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink">{item.summary}</p>
                  <p className="mt-0.5 text-xs text-muted" title={new Date(item.createdAt * 1000).toLocaleString()}>{timeAgo(item.createdAt)}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
