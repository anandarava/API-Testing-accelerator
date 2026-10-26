export function timeAgo(epochSeconds: number | null | undefined): string {
  if (!epochSeconds) return '';
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? '' : 's'} ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase() || '?';
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`;
}

export function formatLabel(format: string): string {
  if (format.startsWith('openapi-')) return 'OpenAPI ' + format.slice(8);
  if (format === 'swagger-2.0') return 'Swagger 2.0';
  return format;
}
