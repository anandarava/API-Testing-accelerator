# API Test Studio

Generate reviewed API test cases from an OpenAPI / Swagger spec and turn the approved ones into
Playwright + TypeScript tests that follow your own framework. Claude does the design and writing on
each QA's computer with their own Claude account; the team reviews and approves every case.

| Folder | What it is |
| --- | --- |
| [`api-test-studio/`](api-test-studio/) | The app: portal (FastAPI + React), Local Helper, Claude agents and skills. Start with its [README](api-test-studio/README.md) and the [QA guide](api-test-studio/docs/QA_GUIDE.md). |
| [`apitesting/`](apitesting/) | A sample Playwright + TypeScript API test framework with a built-in mock API, to try script generation against. |

## Modules

- **Unit test cases**: every scenario for each endpoint (validation, boundaries, auth, errors, business rules), with coverage checked against the spec.
- **Flow test cases**: end-to-end journeys across the API, designed per business area.
- **Role test cases**: who may call what, from your roles file (allowed, denied, ownership).
- **Scripts**: approved cases become Playwright tests in your framework; the app never runs your tests.
