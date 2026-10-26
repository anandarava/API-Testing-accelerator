---
name: api-test-design-techniques
description: The senior API tester's playbook for designing unit-level test scenarios for one REST endpoint from its OpenAPI contract.
---
## Mindset

Test one endpoint as a senior API tester would: prove it works for valid input, then prove
that it rejects every kind of bad input and enforces every rule the contract states. Each scenario
changes exactly **one** thing compared with a valid request, so a failure points to one cause.

## Categories to consider for every endpoint

Work through every category. Skip a category only when the contract gives it nothing to test.

| Category | What to design |
| --- | --- |
| `positive` | Only the required inputs; all optional inputs populated; each documented success status (e.g. 200 and 201); response body matches the success schema; values echo the request where the contract implies it. |
| `required` | Each required body field missing; each required field `null` (unless nullable); required query/header parameters missing; body missing when the body is required. |
| `type` | Each field sent with the wrong JSON type (string↔number, object↔array, boolean as string); body that is malformed JSON or an array instead of an object. |
| `boundary` | For every `minLength`/`maxLength`/`minimum`/`maximum`/`minItems`/`maxItems`: the exact limit (valid) **and** just beyond it (invalid). Treat `exclusiveMinimum`/`exclusiveMaximum` correctly. Empty string and zero where meaningful. |
| `format` | Invalid `email`, `uuid`, `date`, `date-time`, `uri` values; values that break a `pattern`. |
| `enum` | A value outside the allowed list; wrong letter case of an allowed value. |
| `path_params` | Malformed id (wrong format/type); an id that does not exist → 404 when documented. |
| `query_params` | Limits, enum filters, unknown filters ignored or rejected, combinations that change results. |
| `headers` | Unsupported `Content-Type` (e.g. `text/plain`); missing or wrong `Accept` when the contract defines media types; required custom headers missing. |
| `auth` | No credentials; invalid or expired credentials → 401; valid credentials without permission → 403 when documented. |
| `business` | Every rule written in summaries and descriptions: uniqueness ("names must be unique" → duplicate → 409), state rules ("only available pets can be ordered"), calculated values, side effects. Quote the rule in `source`. |
| `contract` | Response structure: required response fields present, types correct, error responses follow the documented error schema. |
| `security` | Read-only fields sent in the request (mass assignment) are ignored or rejected; injection-style strings in text fields are stored safely or rejected; oversized payloads are rejected. |
| `idempotency` | Repeating PUT/DELETE gives a consistent result; repeating POST creates duplicates or is rejected as the contract says. |
| `pagination` | First page, last page, page size limits, empty result, invalid page or cursor. |
| `error_handling` | Every documented 4xx status is reached by at least one scenario. |

## Edge cases senior testers add when the contract has them

| Contract signal | Scenario |
| --- | --- |
| `additionalProperties: false` | An unknown extra field is rejected (`type` or `security`). |
| `nullable` vs not required | `null` and a missing field are different cases; test each where they behave differently. |
| Free-text strings | Leading/trailing spaces are trimmed or rejected as documented; Unicode (accents, emoji) is stored unchanged. |
| `number` / money / `multipleOf` | Too many decimal places; negative values; very large values; `0` when `minimum` is 1. |
| `date` / `date-time` | 29 February in a leap year and in a non-leap year; dates in the past or future when the rule matters; a time zone offset is kept. |
| `uniqueItems` | An array with a duplicate item is rejected. |
| `PATCH` | Fields not sent keep their values (read back). |
| `DELETE` | Deleting twice: the second call returns the documented 404 (or 204). |
| `201` with `Location` | The `Location` header points to the created resource. |
| `ETag` / `If-Match` | A stale `If-Match` returns 412 when documented. |
| `429` documented | Too many requests return 429 (mark `needsConfirmation` if limits are not documented). |
| `multipart/form-data` | A file that is too large or of the wrong type is rejected. |

## Large schemas

When a body has many fields, keep one scenario per condition but be selective: test every required
field fully (missing, null, type, limits), and for optional fields test the ones with constraints
(limits, formats, enums, patterns). Plain optional fields without constraints need no type scenario
each; one `positive:full` request covers them.

## Rules that make a checklist trustworthy

1. **One condition per scenario.** "Missing name" and "name too long" are two scenarios.
2. **Never invent status codes.** Use only statuses the endpoint documents. If the contract does not
   say what happens (e.g. wrong Content-Type and no 415 is documented), choose the most likely
   documented status (usually 400), set `needsConfirmation: true` and explain in `confirmationNote`.
3. **Trace every scenario.** `source` names the exact contract element: `requestBody.name.maxLength`,
   `parameters.limit.maximum`, `responses.409`, `security.bearerAuth`, `description: "Names must be unique"`.
4. **Cover every provided requirement.** Each requirement id you are given must appear in the
   `covers` list of at least one scenario. One scenario may cover several ids (a "missing token"
   scenario covers `auth:missing` and `status:401`).
5. **Go beyond the minimum.** The requirement list is the floor, not the ceiling. Add business,
   security, idempotency and contract scenarios a senior tester would add, with `covers: []` when no
   requirement id applies.
6. **Prioritise.** `P1`: core success paths, auth, documented business rules. `P2`: validation of
   required fields, types and boundaries. `P3`: rare edge cases and defensive checks.
7. **5xx statuses are not test targets.** Do not design scenarios that try to crash the server.
