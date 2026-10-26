import 'dotenv/config';

/** Token the built-in mock API accepts. Only used when no real API is configured. */
export const MOCK_TOKEN = 'local-dev-token';

const mockPort = Number(process.env.MOCK_PORT ?? 4010);

/** True when API_BASE_URL is empty: tests run against the built-in mock API. */
export const useMock = !process.env.API_BASE_URL;

export const env = {
  baseUrl: process.env.API_BASE_URL || `http://127.0.0.1:${mockPort}`,
  token: process.env.API_TOKEN || (useMock ? MOCK_TOKEN : ''),
  /** Optional credentials for negative auth cases; tests that need them skip when unset. */
  expiredToken: process.env.API_TOKEN_EXPIRED || (useMock ? 'expired-token' : ''),
  limitedToken: process.env.API_TOKEN_LIMITED || '',
  mockPort,
};

export function requireToken(): string {
  if (!env.token) throw new Error('Set API_TOKEN in .env (see .env.example) to run tests against a real API.');
  return env.token;
}
