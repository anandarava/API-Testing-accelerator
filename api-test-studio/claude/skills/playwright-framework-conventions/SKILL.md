---
name: playwright-framework-conventions
description: What to look for when learning a Playwright + TypeScript API test framework, and how to describe it precisely.
---
## Where Playwright API frameworks usually keep things

| Concern | Typical locations and signals |
| --- | --- |
| Test files | `tests/`, `tests/api/`, `e2e/`, `specs/`; `testDir` in `playwright.config.ts` |
| Fixtures | `fixtures/`, `src/fixtures/`, files calling `test.extend<...>()`; tests import `test` from them instead of `@playwright/test` |
| API clients | `api/`, `clients/`, `services/`, `src/api/`; classes wrapping `APIRequestContext` (`request.get/post/fetch`) |
| Auth | `auth/`, `global-setup.ts`, `storageState`, fixtures that call a login endpoint, `extraHTTPHeaders` in config |
| Config and env | `playwright.config.ts` `use.baseURL`, `dotenv` imports, `config/*.ts`, `.env.example` |
| Assertions | `expect(response.status())`, `expect(response).toBeOK()`, custom `assert*` helpers, schema validators such as ajv or zod |
| Test data | `data/`, `test-data/`, `fixtures/*.json`, builder or factory functions, faker usage |
| Cleanup | `afterEach`/`afterAll` hooks, fixture teardown after `await use(...)`, cleanup registries |

## How to describe a framework precisely

- Prefer facts copied from code over general statements. "Tests import `test` from
  `../fixtures/api-fixtures`" is useful; "uses fixtures" is not.
- Name the exact class, function and file for each building block.
- Record naming precisely: `kebab-case` vs `camelCase` files, `users.api.spec.ts` vs `users.spec.ts`,
  test title formats such as `TC-001 should create user`.
- Note how tests reach the base URL: a relative path relies on `baseURL`; an absolute URL comes
  from config.
- Note whether tests are independent or share state, and whether `test.describe.serial` is used.
- When two styles coexist, describe the newest or most common one and add the other to `warnings`.

## Quality bar for generated tests (record anything that contradicts this as a warning)

- No hard waits (`waitForTimeout`), no `test.only`, no committed secrets.
- Credentials and URLs come from environment variables or config.
- Each test asserts status code and response body or schema, not only the status code.
