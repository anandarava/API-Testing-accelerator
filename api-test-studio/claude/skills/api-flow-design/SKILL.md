---
name: api-flow-design
description: How a senior API tester designs end-to-end flow test cases that chain several operations into business journeys.
---
## What a flow test is

A flow test proves a **business journey** works across several API operations, passing real data
from one step to the next: create a pet, look it up, order it, confirm the order, check the pet is no
longer available, cancel, clean up. Unit tests check each endpoint alone; flows check that the
endpoints work **together** and that state changes are consistent.

## Flow types to design

| Type | What it proves |
| --- | --- |
| `happy_path` | The main journey of each entity works end to end (create → read → update → read → delete → read gives 404). |
| `end_to_end` | A complete business process across entities (register → create pet → order pet → fetch order). |
| `state_transition` | Every lifecycle transition the contract describes, and that each state is visible through reads. |
| `alternate_path` | Valid variations: optional fields, different filters, updating different fields. |
| `negative` | The journey breaks correctly: acting on a deleted resource (404), ordering an unavailable pet (409), duplicate creation (409), using an id from another resource type. |
| `data_integrity` | Data written in one step is returned unchanged by later reads, lists and related resources. |
| `role_based` | Different credentials see or change different things, when the contract documents roles or 403s. |

## Rules

1. **No step limit.** Use as many steps as the journey needs; do not pad journeys with extra steps.
2. **Real data flow.** Each value a step needs from an earlier step is an `input` whose `source` is
   `steps.<StepKey>.<captureName>`, and the earlier step lists that capture. Never hard-code ids.
3. **Verify, don't assume.** After each state change, add a read step that proves the new state
   (e.g. after DELETE, GET returns 404; after an order, the pet status is pending).
4. **Documented statuses only.** If the contract does not say what a step returns, choose the most
   likely documented status and mark the flow `needsConfirmation` with a note.
5. **Clean up.** Flows that create data end by deleting it, or state how the data is removed.
6. **Trace.** Each flow lists in `covers` the requirement ids it satisfies (operations, id
   dependencies, lifecycle transitions `transition:<entity>:<from>-><to>`, business rules `rule:R1`,
   locked states `locked:<entity>:<STATE>`, side effects `effect:<operationId>:<n>`). A claim
   counts only when the flow contains the requirement's `proof`.
7. **One goal per flow.** A flow proves one journey; do not merge unrelated journeys.
8. **Prioritise.** `P1` for core journeys and money/state-changing processes, `P2` for alternates
   and negatives, `P3` for rare combinations.
