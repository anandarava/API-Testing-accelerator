# API testing framework

Playwright + TypeScript framework for API tests. It runs out of the box against a built-in mock of
`specs/petstore.yaml`; point it at a real environment with one setting.

## Quick start

```bash
npm install
npm test            # unit + flow tests against the built-in mock API
npm run report      # open the HTML report
```

To test a real environment, copy `.env.example` to `.env` and set:

```bash
API_BASE_URL=https://your-test-environment.example/v1
API_TOKEN=<bearer token>
API_TOKEN_EXPIRED=<optional, enables expired-token cases>
```

When `API_BASE_URL` is empty, Playwright starts `mock/petstore-mock.mjs` automatically
(token `local-dev-token`).

## Commands

| Command | What it does |
| --- | --- |
| `npm test` | All tests (projects `unit` and `flows`) |
| `npm run test:unit` / `npm run test:flows` | One project |
| `npm run test:smoke` | Tests tagged `@smoke` |
| `npm run check` | TypeScript, ESLint and test discovery — no requests are sent |
| `npm run mock` | Start the mock API on port 4010 for manual exploration |
| `npm run report` | Open the last HTML report (`reports/html`); JUnit is in `reports/junit.xml` |

## Structure

```
specs/                 OpenAPI document; response schemas are validated against it
mock/                  In-memory mock API used when API_BASE_URL is empty
src/
  config/env.ts        Environment settings (.env), mock defaults
  core/api-client.ts   Base client: relative paths, parsed bodies, request/response log
  core/cleanup.ts      Cleanup registry (runs after each test, even on failure)
  clients/             One client per resource: PetsClient, OrdersClient
  fixtures/index.ts    test + expect with fixtures: pets, orders, clientAs, cleanup, createPet, apiLog
  helpers/assertions.ts expectStatus, expectJson, expectError, expectSchema, expectResponseSchema
  helpers/schema.ts    OpenAPI schema validation (ajv)
  data/builders.ts     newPet, newOrder, uniqueName, ofLength, unknownId
  types/               Types matching the spec
tests/
  api/<resource>/      Unit tests per endpoint
  flows/               End-to-end journeys with one test.step per step
```

## Writing a test

```ts
import { test, expect } from '../../../src/fixtures';
import { expectError, expectJson } from '../../../src/helpers/assertions';
import { newPet } from '../../../src/data/builders';
import type { Pet } from '../../../src/types/petstore';

test.describe('POST /pets', () => {
  test('creates a pet @smoke', async ({ pets, cleanup }) => {
    const pet = expectJson<Pet>(await pets.create(newPet()), 201, 'createPet'); // status + spec schema
    cleanup.add('delete pet', () => pets.remove(pet.id));
    expect(pet.status).toBe('available');
  });

  test('rejects a missing name', async ({ pets }) => {
    expectError(await pets.create({ tag: 'dog' }), 400); // status + Error schema
  });
});
```

Conventions:

- Import `test` and `expect` from `src/fixtures`, never from `@playwright/test`.
- Call the API through the resource clients; add a method to the client when a new endpoint is needed.
- Use `expectJson(response, status, operationId)` so every successful response is checked against
  the documented schema; use `expectError` for error responses.
- Use builders (`newPet`, `uniqueName`) instead of fixed values so tests are independent and repeatable.
- Clean up everything a test creates: `createPet` does it for you, otherwise `cleanup.add(...)`.
- Credentials: `pets`/`orders` use `API_TOKEN`; `clientAs(PetsClient, null)` sends none;
  `clientAs(PetsClient, 'invalid-token')` sends a specific token. Skip cases that need optional
  credentials with `test.skip(!env.expiredToken, '...')`.
- Flows: one `test()` per journey, one `test.step('S1 ...')` per step, values passed in variables.
- No `test.only`, no fixed waits; tag core cases `@smoke`.
- When a test fails, `api-exchanges.json` with every request and response (secrets masked) is
  attached to the report.

## Adding a new API

1. Put its OpenAPI file in `specs/` and set `SPEC_FILE=specs/<file>` in `.env` (or replace petstore.yaml).
2. Add types in `src/types/`, a client in `src/clients/` and fixtures in `src/fixtures/index.ts`.
3. Add tests under `tests/api/<resource>/` and `tests/flows/`.

## Using it with API Test Studio

In API Test Studio, set this folder as your **framework folder** and run **Analyze framework**. The
generated scripts follow the conventions above and land in `tests/api/` (and `tests/api/flows/`).
API Test Studio records the files it manages in `.api-test-studio/manifest.json`.
