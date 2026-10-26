import type { APIRequestContext } from '@playwright/test';

/** One request/response pair, kept so failed tests can attach what was sent and received. */
export interface Exchange {
  method: string;
  url: string;
  requestHeaders?: Record<string, string>;
  requestBody?: unknown;
  status: number;
  responseBody: unknown;
  durationMs: number;
}

export interface ApiResponse {
  status: number;
  headers: Record<string, string>;
  /** Parsed JSON body, raw text for non-JSON responses, or undefined when empty. */
  body: unknown;
  text: string;
}

export interface RequestOptions {
  params?: Record<string, string | number | boolean | undefined>;
  /** JSON body. Use `raw` to send an exact string (e.g. malformed JSON). */
  data?: unknown;
  raw?: string;
  headers?: Record<string, string>;
}

const SECRET_HEADERS = /^(authorization|cookie|x-api-key)$/i;

/**
 * Thin wrapper over Playwright's APIRequestContext: relative paths only, parsed bodies and a log of
 * every exchange. Resource clients (PetsClient, OrdersClient) extend this.
 */
export class ApiClient {
  constructor(
    protected readonly request: APIRequestContext,
    private readonly log: Exchange[] = [],
  ) {}

  async send(method: string, path: string, options: RequestOptions = {}): Promise<ApiResponse> {
    if (!path.startsWith('/') || path.startsWith('//')) throw new Error(`Use a relative API path, got "${path}"`);
    const params = Object.fromEntries(
      Object.entries(options.params ?? {}).filter((entry): entry is [string, string | number | boolean] => entry[1] !== undefined),
    );
    const headers = { ...(options.headers ?? {}) };
    let data: unknown = options.data;
    if (options.raw !== undefined) {
      data = options.raw;
      headers['Content-Type'] ??= 'application/json';
    }
    const started = Date.now();
    const response = await this.request.fetch(path, { method, params, headers, data: data as never, maxRedirects: 0 });
    const text = await response.text();
    let body: unknown = undefined;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    this.log.push({
      method, url: response.url(), status: response.status(), durationMs: Date.now() - started,
      requestHeaders: Object.fromEntries(Object.entries(headers).map(([k, v]) => [k, SECRET_HEADERS.test(k) ? '***' : v])),
      requestBody: options.raw ?? options.data, responseBody: body,
    });
    return { status: response.status(), headers: response.headers(), body, text };
  }

  get(path: string, options?: RequestOptions) {
    return this.send('GET', path, options);
  }

  post(path: string, data?: unknown, options: RequestOptions = {}) {
    return this.send('POST', path, { ...options, data });
  }

  patch(path: string, data?: unknown, options: RequestOptions = {}) {
    return this.send('PATCH', path, { ...options, data });
  }

  put(path: string, data?: unknown, options: RequestOptions = {}) {
    return this.send('PUT', path, { ...options, data });
  }

  delete(path: string, options?: RequestOptions) {
    return this.send('DELETE', path, options);
  }
}

/** Encode a path parameter safely. */
export const segment = (value: string | number): string => encodeURIComponent(String(value));
