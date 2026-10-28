---
name: api-flow-edge-cases
description: The edge cases a senior API tester checks in flow tests, matched to the kind of each business rule.
---
## Use the rule kind

Every business rule has a `kind`. Design at least one flow per rule with the technique for its kind,
and only for patterns the contract actually has:

| Kind | Technique | Example |
| --- | --- | --- |
| `uniqueness` | Create, then create the same thing again → documented 409/422 | Same email registers twice |
| `concurrency` | Two competing requests for one resource, one after the other → the second is refused | Reserve the last unit, reserve it again → 409 |
| `state` | Act in the wrong state → refused; act in the right state → allowed | Approve a CANCELLED request → 409 |
| `validation` | A journey step with a value that breaks the rule → refused, and nothing changed (read back) | A reason or comment shorter than the documented minimum |
| `idempotency` | Send the same request twice with the same Idempotency-Key → same result, no duplicate (list or read back) | Pay twice with one key → one payment |
| `money` | Amounts add up across steps; limits hold | Two partial payments → fully paid; refund ≤ amount paid |
| `side_effect` | After the step, read what else changed | After completing a record → the owner's notification or the audit entry exists |
| `time` | Windows, expiry, cut-offs. Test the side you can reach now; if the other side needs a test clock, add the flow with `needsConfirmation` and say what support is needed | An unpaid reservation expires after 15 minutes |
| `external` | Callbacks and gateways: valid signature accepted, invalid or missing signature refused, duplicate event ignored | Payment webhook with a bad signature → 401 |
| `ownership`, `role` | Designed separately with the project's roles; skip here | |

## Locked and final states

For every `locked:<Entity>:<STATE>` requirement: reach that state, then try to change the record
(update, cancel, transition again) → the documented refusal (409/422/400), then read it back
unchanged. Example: submit or sign a record, then edit it → 409.

## Invalid transitions

Besides the documented transitions, try the most likely wrong order once per lifecycle: skip a state
(complete before it was started), go backwards (reopen a COMPLETED record), repeat a one-time action
(submit twice, refund twice).

## Lists and filters

After creating a record, prove it appears in the matching list or filter and not in a non-matching
one. Check pagination limits only when the contract documents them.

## Test support and needsConfirmation

When a rule has `needsSupport` (a test clock, a signing secret, seeded data), still design the flow:
use `{{env.NAME}}` for the secret or setting, mark the flow `needsConfirmation`, and write in the
note exactly what the test environment must provide.

## Proof

Each requirement has a `proof`: what the flow must contain for its `covers` claim to count. A claim
without that proof does not count as covered, so design the step that proves it.
