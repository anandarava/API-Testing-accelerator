import type { CaseStatus, Priority } from '../lib/api';
import { Badge, type Tone } from './ui';

export const STATUS_LABEL: Record<CaseStatus, string> = {
  in_review: 'In review', approved: 'Approved', needs_changes: 'Needs changes', rejected: 'Rejected',
};
export const STATUS_TONE: Record<CaseStatus, Tone> = { in_review: 'blue', approved: 'green', needs_changes: 'amber', rejected: 'red' };
export const STATUS_DOT: Record<CaseStatus, string> = { in_review: 'bg-blue-500', approved: 'bg-emerald-500', needs_changes: 'bg-amber-500', rejected: 'bg-red-500' };

export function StatusBadge({ status }: { status: CaseStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
}

export const CATEGORY_LABEL: Record<string, string> = {
  positive: 'Positive', required: 'Required fields', type: 'Data types', boundary: 'Boundaries', format: 'Formats',
  enum: 'Allowed values', path_params: 'Path parameters', query_params: 'Query parameters', headers: 'Headers',
  auth: 'Authentication', business: 'Business rules', contract: 'Response contract', security: 'Security',
  idempotency: 'Idempotency', pagination: 'Pagination', error_handling: 'Error handling',
};

export const PRIORITY_LABEL: Record<Priority, string> = { P1: 'High', P2: 'Medium', P3: 'Low' };

export function PriorityBadge({ priority }: { priority: Priority }) {
  const tone: Record<Priority, Tone> = { P1: 'red', P2: 'amber', P3: 'gray' };
  return <Badge tone={tone[priority]}>{PRIORITY_LABEL[priority]}</Badge>;
}

export const ROLE_KIND_LABEL: Record<string, string> = {
  allowed: 'Allowed', denied: 'Denied', ownership: 'Ownership (second user)', hidden_data: 'Hidden data', protected_field: 'Protected field',
};

export const AUTH_LABEL: Record<string, string> = {
  valid: 'Valid credentials', none: 'No credentials', invalid: 'Invalid credentials', expired: 'Expired credentials',
  insufficient: 'Valid user without permission',
};

export function statusTone(status: number | null | undefined): Tone {
  if (!status) return 'gray';
  if (status < 300) return 'green';
  if (status < 400) return 'blue';
  if (status < 500) return 'amber';
  return 'red';
}
