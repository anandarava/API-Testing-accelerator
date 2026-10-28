# Test case generation: ideas to discuss

Proposed improvements to unit and flow test case generation. None of these are built yet.

Already done:
- A second fix round for blocker and major issues that come back after the flow re-review.
- Successful responses must check their body, not only the status code (unit and flow cases).

## 1. Second fix round for unit cases

Flows now get two fix rounds; unit cases still get one (`helper/unit_cases.py`). Doing the same for
unit cases keeps the two consistent.

- **Effort:** small.
- **Cost:** a little more generation time on endpoints where the first fix does not hold.

## 2. AI reviewer written for QA

The "To improve" notes are written in the AI's own terms (step ids like S5, flow keys like F111,
env variable names), so QA cannot act on them.

- Tell the reviewer to describe problems in terms of what the API does, without internal ids.
- Show blocker and major issues by default; collapse minor ones behind "Show n minor notes".
- Name the flow next to its TC code.
- Split old reviews ("Area: text Area: text") back into areas, and hide empty boxes.

## 3. Test data isolation and clean-up

Several reviewer notes are real data problems:
- Flows share one seeded account, so they can affect each other when they run together.
- Sessions are left open and created records are never deleted.

Have the designer and writer create their own data (unique emails or names per run) and end with
clean-up steps, so these problems never reach the review.

## 4. Less overlap between unit and flow cases

Flows include single-endpoint negative steps (invalid input → 400, no login → 401) that unit cases
for the same endpoint may already test. Flows could focus on multi-step business behaviour and
link to the unit case instead of repeating it, leaving QA fewer cases to maintain.

## 5. Use script run results

When a generated script fails because the API answers differently from what the case expected,
offer "update the expected result" or "report as a bug" on that case. This follows up the AI's
"needs confirmation" marks instead of leaving them for QA to chase by hand.

## 6. Local model quality

The local Qwen model gives noticeably weaker results than Claude (for example, in the assistant).
Options:
- Run the reviewer (or the assistant) on Claude even when Qwen is selected.
- Show a "local model, lower quality" note on cases it generated.

## Other ideas raised earlier

- Totals by test type and a short glossary in the assistant's project snapshot, so it answers count
  questions correctly.
- Let a reviewer mark a business process as covered by hand.
- Show the closest existing flow on the Business processes tab for processes that are not covered.
- A clearer assistant error when the portal is running old code (404 on the assistant API).
- An option to also add the reviewer's minor flow suggestions automatically.
