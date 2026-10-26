import { expect } from '@playwright/test';
import type { ApiResponse } from '../core/api-client';
import type { ApiError } from '../types/petstore';
import { describeErrors, responseValidator, schemaValidator } from './schema';

const preview = (response: ApiResponse) => response.text.slice(0, 500);

/** Assert the status code; the message includes the response body to make failures readable. */
export function expectStatus(response: ApiResponse, status: number): void {
  expect(response.status, `Expected HTTP ${status}, got ${response.status}: ${preview(response)}`).toBe(status);
}

/** Assert the body matches a component schema from the OpenAPI spec, e.g. expectSchema(body, 'Pet'). */
export function expectSchema(body: unknown, schemaName: string): void {
  const validate = schemaValidator(schemaName);
  expect(validate(body), `Body does not match schema ${schemaName}: ${describeErrors(validate)}`).toBe(true);
}

/** Assert the body matches the documented response schema of an operation. */
export function expectResponseSchema(response: ApiResponse, operationId: string): void {
  const validate = responseValidator(operationId, response.status);
  expect(validate(response.body), `${operationId} ${response.status} body does not match the spec: ${describeErrors(validate)}`).toBe(true);
}

/** Assert status (and optionally the documented schema) and return the typed body. */
export function expectJson<T>(response: ApiResponse, status: number, operationId?: string): T {
  expectStatus(response, status);
  expect(response.headers['content-type'] ?? '', 'Content-Type').toContain('application/json');
  if (operationId) expectResponseSchema(response, operationId);
  return response.body as T;
}

/** Assert an error response that follows the documented Error schema and return it. */
export function expectError(response: ApiResponse, status: number): ApiError {
  expectStatus(response, status);
  expectSchema(response.body, 'Error');
  return response.body as ApiError;
}
