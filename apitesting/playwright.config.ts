import { defineConfig } from '@playwright/test';
import { env, useMock } from './src/config/env';

export default defineConfig({
  testDir: './tests',
  testMatch: '**/*.spec.ts',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'reports/html', open: 'never' }],
    ['junit', { outputFile: 'reports/junit.xml' }],
  ],
  use: {
    baseURL: env.baseUrl,
    extraHTTPHeaders: { Accept: 'application/json' },
  },
  projects: [
    { name: 'unit', testDir: './tests/api' },
    { name: 'flows', testDir: './tests/flows' },
  ],
  // Without API_BASE_URL the suite runs against the in-memory mock of specs/petstore.yaml.
  webServer: useMock
    ? {
        command: 'node mock/petstore-mock.mjs',
        url: `${env.baseUrl}/health`,
        env: { MOCK_PORT: String(env.mockPort) },
        reuseExistingServer: !process.env.CI,
        stdout: 'ignore',
      }
    : undefined,
});
