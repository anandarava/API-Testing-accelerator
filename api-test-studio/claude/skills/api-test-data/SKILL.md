---
name: api-test-data
description: How to write concrete, valid and reproducible request data for API test cases.
---
## Start from a valid request

Build one valid request first: every required field, realistic values that satisfy every
constraint (type, format, enum, min/max, pattern), and the schema `example` when one exists. Each
negative case is that valid request with exactly one change.

## Realistic values

- Names and text: meaningful values (`"Rex"`, `"Order for QA"`), not `"string"` or `"test"`.
- Emails: `qa.user+<case>@example.test`. URLs: `https://example.test/...`.
- Dates: ISO 8601 (`2026-01-15`, `2026-01-15T10:30:00Z`).
- Numbers: inside the documented range; use the exact boundary only in boundary cases.
- Enums: a real allowed value in valid requests.
- Phone numbers: E.164 (`+919876543210`). Money: the documented currency and number of decimals
  (`1250.50`), never more decimals than allowed. Identifiers: the documented format (UUID, ULID,
  `PAT-000123`).
- No realistic personal data: invented names, `example.test` emails, never real ID or card numbers.
- Unique fields (email, username, code) always use `{{unique.name}}`-style values so repeated runs do
  not collide.

## Placeholders (the script generator resolves these)

| Placeholder | Meaning |
| --- | --- |
| `{{env.NAME}}` | Environment-specific value, e.g. `{{env.API_BASE_URL}}`. Never write real secrets. |
| `{{unique.name}}` | A unique value per run, used when the API enforces uniqueness. |
| `{{repeat:x:51}}` | A string of 51 `x` characters; use for length boundaries above 20 characters. |
| `{{uuid.random}}` | A random UUID that does not exist (for 404 cases). |
| `{{created.<field>}}` | A value from a resource created in a precondition, e.g. `{{created.petId}}`. |
| `{{steps.<StepKey>.<capture>}}` | In flow tests: a value captured by an earlier step, e.g. `{{steps.S1.petId}}`. |

## Preconditions and cleanup

- If the case needs an existing resource, add a precondition ("Create a pet and keep its id as
  `{{created.petId}}`") and a cleanup step ("Delete the pet created in the precondition").
- Duplicate/conflict cases create the first resource in a precondition, then send the duplicate.
- Cases that create data must list cleanup steps.

## Authentication modes

`request.auth` is one of `valid` (normal credentials), `none` (send no credentials), `invalid`
(malformed or wrong token), `expired`, `insufficient` (valid user without permission). Never put
tokens or passwords in headers or bodies.

## Expected results

- `expected.status` is a documented status code.
- `responseSchema` is `success` for 2xx with a documented body, `error` for documented error bodies,
  otherwise `none`.
- `bodyChecks` assert what matters for this case: created values echo the request
  (`matches_request` with value `"$.name"`), generated ids exist (`exists`) and have the right format
  (`matches_pattern`), enum fields hold an allowed value (`one_of`). Assert error message text only
  when the contract documents it.
