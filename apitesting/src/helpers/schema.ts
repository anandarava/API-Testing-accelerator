import fs from 'node:fs';
import path from 'node:path';
import Ajv, { type ValidateFunction } from 'ajv';
import addFormats from 'ajv-formats';
import { parse } from 'yaml';

/** Validates response bodies against the schemas in the OpenAPI document (SPEC_FILE, default specs/petstore.yaml). */
const specFile = path.resolve(__dirname, '../..', process.env.SPEC_FILE ?? 'specs/petstore.yaml');
const spec = parse(fs.readFileSync(specFile, 'utf8')) as {
  paths: Record<string, Record<string, { operationId?: string; responses?: Record<string, unknown> }>>;
  components?: Record<string, unknown>;
};

const ajv = new Ajv({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema({ $id: 'spec', components: spec.components ?? {} });
const cache = new Map<string, ValidateFunction>();

function compile(key: string, schema: object): ValidateFunction {
  if (!cache.has(key)) cache.set(key, ajv.compile(schema));
  return cache.get(key)!;
}

function rewriteRefs(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(rewriteRefs);
  if (node && typeof node === 'object') {
    return Object.fromEntries(Object.entries(node).map(([key, value]) =>
      [key, key === '$ref' && typeof value === 'string' && value.startsWith('#/') ? `spec${value}` : rewriteRefs(value)]));
  }
  return node;
}

/** Validator for a named component schema, e.g. schemaValidator('Pet'). */
export function schemaValidator(name: string): ValidateFunction {
  return compile(`component:${name}`, { $ref: `spec#/components/schemas/${name}` });
}

/** Validator for the documented response of an operation, e.g. responseValidator('createPet', 201). */
export function responseValidator(operationId: string, status: number): ValidateFunction {
  for (const item of Object.values(spec.paths)) {
    for (const operation of Object.values(item)) {
      if (operation?.operationId !== operationId) continue;
      let response = operation.responses?.[String(status)] as Record<string, unknown> | undefined;
      if (!response) throw new Error(`${operationId} does not document a ${status} response`);
      if (typeof response.$ref === 'string') {
        const name = response.$ref.split('/').pop()!;
        response = (spec.components?.responses as Record<string, Record<string, unknown>>)[name];
      }
      const content = response.content as Record<string, { schema?: object }> | undefined;
      const schema = content?.['application/json']?.schema;
      if (!schema) throw new Error(`${operationId} ${status} has no JSON schema`);
      return compile(`response:${operationId}:${status}`, rewriteRefs(schema) as object);
    }
  }
  throw new Error(`Unknown operationId ${operationId}`);
}

export function describeErrors(validate: ValidateFunction): string {
  return (validate.errors ?? []).map((e) => `${e.instancePath || '(root)'} ${e.message}`).join('; ');
}
