import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import type { Schema } from '../lib/api';
import { cx } from './ui';

const CONSTRAINTS: [string, (value: any) => string][] = [
  ['format', (v) => v], ['minLength', (v) => `min length ${v}`], ['maxLength', (v) => `max length ${v}`],
  ['minimum', (v) => `≥ ${v}`], ['maximum', (v) => `≤ ${v}`], ['exclusiveMinimum', (v) => (typeof v === 'number' ? `> ${v}` : '')],
  ['exclusiveMaximum', (v) => (typeof v === 'number' ? `< ${v}` : '')], ['multipleOf', (v) => `multiple of ${v}`],
  ['pattern', (v) => `pattern ${v}`], ['minItems', (v) => `min ${v} items`], ['maxItems', (v) => `max ${v} items`],
  ['uniqueItems', (v) => (v ? 'unique items' : '')], ['default', (v) => `default ${JSON.stringify(v)}`],
];

/** Merge allOf parts so the common "base + extension" pattern reads as one object. */
function flatten(schema: Schema): Schema {
  if (!schema?.allOf) return schema ?? {};
  const merged: Schema = { ...schema, properties: { ...(schema.properties ?? {}) }, required: [...(schema.required ?? [])] };
  delete merged.allOf;
  for (const part of schema.allOf.map(flatten)) {
    Object.assign(merged.properties, part.properties ?? {});
    merged.required.push(...(part.required ?? []));
    merged.type ??= part.type;
  }
  return merged;
}

function typeLabel(schema: Schema): string {
  if (schema['x-circular-ref']) return 'circular reference';
  if (schema.oneOf) return 'one of';
  if (schema.anyOf) return 'any of';
  const type = Array.isArray(schema.type) ? schema.type.join(' | ') : schema.type ?? (schema.properties ? 'object' : 'any');
  if (type === 'array') return `array of ${typeLabel(flatten(schema.items ?? {}))}`;
  return schema.nullable ? `${type} | null` : type;
}

export function SchemaView({ schema, emptyText = 'No schema documented' }: { schema: Schema | undefined; emptyText?: string }) {
  const root = flatten(schema ?? {});
  if (!schema || !Object.keys(schema).length) return <p className="text-sm text-muted">{emptyText}</p>;
  const isObject = root.properties || root.type === 'object';
  const isArrayOfObjects = root.type === 'array' && flatten(root.items ?? {}).properties;
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      {isObject || isArrayOfObjects ? (
        <>
          {isArrayOfObjects && <div className="border-b border-line bg-canvas px-4 py-2 font-mono text-xs text-muted">array of objects</div>}
          <Properties schema={isArrayOfObjects ? flatten(root.items) : root} depth={0} />
        </>
      ) : <div className="px-4 py-3"><Row name="(value)" schema={root} required={false} depth={0} /></div>}
    </div>
  );
}

function Properties({ schema, depth }: { schema: Schema; depth: number }) {
  const properties = Object.entries<Schema>(schema.properties ?? {});
  const required = new Set<string>(schema.required ?? []);
  if (!properties.length) return <p className="px-4 py-3 text-sm text-muted">Object with no documented properties</p>;
  return (
    <div className="divide-y divide-line">
      {properties.map(([name, child]) => <Row key={name} name={name} schema={child} required={required.has(name)} depth={depth} />)}
    </div>
  );
}

function Row({ name, schema: raw, required, depth }: { name: string; schema: Schema; required: boolean; depth: number }) {
  const schema = flatten(raw ?? {});
  const nested = schema.properties ? schema : schema.type === 'array' && flatten(schema.items ?? {}).properties ? flatten(schema.items) : null;
  const variants: Schema[] = schema.oneOf ?? schema.anyOf ?? [];
  const [open, setOpen] = useState(depth < 1);
  const chips = CONSTRAINTS.map(([key, render]) => (key in schema ? render(schema[key]) : '')).filter(Boolean);
  if (schema.enum) chips.unshift(`one of: ${schema.enum.map((v: unknown) => JSON.stringify(v)).join(', ')}`);
  const expandable = !!nested || variants.length > 0;
  return (
    <div className={cx(depth > 0 && 'bg-canvas/40')}>
      <div className="flex items-start gap-2 px-4 py-2.5" style={{ paddingLeft: 16 + depth * 18 }}>
        <button disabled={!expandable} onClick={() => setOpen(!open)} className={cx('mt-0.5 shrink-0 rounded text-faint', expandable ? 'cursor-pointer hover:text-ink' : 'invisible')} aria-label="Toggle">
          <ChevronRight className={cx('size-4 transition-transform', open && 'rotate-90')} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="font-mono text-[13px] font-medium text-ink">{name}</span>
            <span className="font-mono text-xs text-brand-700">{typeLabel(schema)}</span>
            {required && <span className="text-[11px] font-semibold uppercase tracking-wide text-red-600">required</span>}
            {schema.readOnly && <span className="text-[11px] font-medium text-muted">read-only</span>}
            {schema.writeOnly && <span className="text-[11px] font-medium text-muted">write-only</span>}
            {schema.deprecated && <span className="text-[11px] font-medium text-amber-700">deprecated</span>}
          </div>
          {schema.description && <p className="mt-0.5 text-sm text-muted">{schema.description}</p>}
          {chips.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {chips.map((chip) => <span key={chip} className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-soft">{chip}</span>)}
            </div>
          )}
        </div>
      </div>
      {open && nested && <Properties schema={nested} depth={depth + 1} />}
      {open && variants.map((variant, index) => (
        <div key={index} className="border-t border-line">
          <p className="px-4 pt-2 text-xs font-medium text-muted" style={{ paddingLeft: 34 + depth * 18 }}>Option {index + 1}</p>
          <Row name={variant.title ?? `option ${index + 1}`} schema={variant} required={false} depth={depth + 1} />
        </div>
      ))}
    </div>
  );
}
