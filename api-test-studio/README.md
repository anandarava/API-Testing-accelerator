# API Test Studio

QA teams use API Test Studio to turn OpenAPI / Swagger specs into reviewed API test cases, then
into Playwright + TypeScript scripts written in **their own framework**.

- **Unit test cases** – every scenario for each endpoint, the way a senior API tester writes them.
- **Flow test cases** – end-to-end business journeys across the APIs.
- **Scripts** – approved cases become tests that follow the team's framework conventions.

All AI work runs on each QA's own computer with their own **Claude Pro / Max** account.

> **Status: Phase 5.** Accounts, projects, Lead/Employee roles, spec import, the API browser, the
> Local Helper, the framework profile, **unit test cases**, **flow test cases**, **script
> generation**, **Excel/CSV export** and **single-case regeneration** work today.
>
> **QA team? Start with the [QA guide](docs/QA_GUIDE.md).**

## How it fits together

```
Portal (this server)          QA's computer
 ├ Web UI + API     ◄──────── Local Helper  (python -m helper start)
 ├ Users, roles                 ├ claude CLI  (signed in with the QA's Claude account)
 ├ Specs, endpoints             └ framework folder  (the QA's clone of the Playwright repo)
 └ Profiles, jobs, activity
```

The helper always connects **out** to the portal. A job (for example “analyze framework”) runs on
the computer of the person who started it.

## Start the portal

Requires Python 3.12+ and Node.js 20.19+.

```powershell
cd api-test-studio
./start.ps1            # Windows  (Linux/macOS: bash start.sh)
```

Open <http://127.0.0.1:8000>, create an account and create a project. You become its **Lead**.
Data is stored in `%USERPROFILE%\.api-test-studio\server` (outside OneDrive). Override with
`STUDIO_DATA_DIR`, or use PostgreSQL with `STUDIO_DATABASE_URL=postgresql+psycopg://...`
(after `pip install "psycopg[binary]"`).

After the first run you can start the server without rebuilding:

```powershell
./.venv/Scripts/python.exe -m uvicorn studio.main:app --host 127.0.0.1 --port 8000
```

## Connect your computer (each QA once)

1. Install Claude Code and sign in: `claude auth login`
2. In the portal click **Connect your computer** (top right) and copy the pair command, e.g.
   `.venv\Scripts\python -m helper pair ABCD-EFGH --server http://127.0.0.1:8000`
3. Start the helper and keep the terminal open: `.venv\Scripts\python -m helper start`

**Claude model.** Each user picks a model in the top-bar **Model** menu (Account default, a family alias
such as `opus` that always means the newest version, or a pinned version such as `claude-opus-4-8`; the list
is `CLAUDE_MODEL_CATALOG` in `contracts/__init__.py`, and any other full model id can be typed in). The helper passes it as `--model` to every Claude call of the jobs that user starts,
records the models Claude Code reports (`modelUsage`), and the portal shows them on jobs and in the menu.

`python -m helper status` shows the pairing and Claude sign-in state. Pairing again replaces the
previous computer; **Disconnect** in the portal revokes it.

## Roles

| | Lead | Employee |
|---|:-:|:-:|
| View everything, upload specs, analyze and edit the framework profile | ✅ | ✅ |
| Generate / review / approve test cases and scripts (next phases) | ✅ | ✅ |
| Add or remove members, change roles | ✅ | ❌ |
| Rename or delete the project | ✅ | ❌ |

A project always keeps at least one lead.

## Framework profile

On **Framework**, each QA saves the path of their local framework folder. **Analyze framework**
asks Claude (read-only tools: Read, Glob, Grep; `.env` files blocked) to study the config,
fixtures, API clients and existing tests and produce a **framework profile**. A team member
reviews it, edits if needed and confirms it. Generated scripts will follow this profile.

Try it with `examples/sample-playwright-framework` and `examples/petstore.yaml`.

## Unit test cases

Open **Unit test cases**, select endpoints and click **Generate**. For each endpoint, on the
computer of the person who clicked:

1. **Requirements (code).** `contracts/coverage.py` lists what the contract makes mandatory: every
   required field (missing and null), wrong types, every min/max limit, enums, formats and patterns,
   path parameters (invalid / not found), every documented 2xx–4xx status, auth (missing / invalid /
   forbidden), Content-Type and read-only fields.
2. **Checklist (Claude, `unit-scenario-planner`).** Designs the scenarios with the
   `api-test-design-techniques` skill and tags each with the requirement ids it covers. It adds
   business-rule, security, idempotency and contract scenarios beyond the minimum.
3. **Coverage check (code).** Any uncovered requirement is sent back to Claude to fill (up to two
   rounds). Remaining gaps are shown on the endpoint page.
4. **Test cases (Claude, `unit-case-writer`).** One detailed case per scenario: preconditions,
   concrete request, expected status/schema/body checks, test data and cleanup.
5. **Review (Claude, `unit-case-reviewer`).** Independent QA-lead review.
6. **Fix pass.** For blocker and major findings, the planner adds the missing scenarios the
   reviewer suggested and the writer revises the flagged cases. A final review then runs; its
   findings appear on the endpoint and on each case. Minor findings are left to the QA.

Cases appear in the portal as each endpoint finishes. Everyone in the project can **edit**,
**approve**, **request changes** (with a comment) or **reject** cases, one at a time or in bulk.
Editing an approved case moves it back to review. Regenerating an endpoint keeps approved cases and
replaces the rest. Cases written for an older spec version are marked *Outdated*.

Up to **5 endpoints run at the same time**; each uses about four to eight Claude calls and is saved as
soon as it finishes. Parallel runs use your Claude quota faster; on a Pro plan, generate in smaller
batches.

## Flow test cases

Open **Flow test cases** and click **Analyze APIs & design flows**. For the whole API, on the
computer of the person who clicked:

1. **Dependency map (code).** `contracts/flows.py` finds which documented response identifiers can
   feed which request inputs (for example `POST /pets → $.id` into `GET /pets/{petId}`). It never
   enumerates paths, so large APIs stay fast.
2. **Domain analysis (Claude, `flow-domain-analyst`).** Entities, relationships, lifecycle states
   and transitions, business rules, assumptions, and a split of the API into **business areas**
   (every operation in exactly one area). Saved to the portal immediately.
3. **Design groups, in parallel (5 at a time).** One **cross-area journeys** group designs the
   end-to-end processes that span areas (e.g. register patient → book appointment → admit → invoice
   → pay → discharge); one group per **business area** designs that area's lifecycles, state
   transitions, negatives and data-integrity flows (steps may call other areas when needed). There is
   **no step limit**. Each group validates its flows (real operations, documented statuses, every
   chained value captured by an earlier step), writes them (`flow-case-writer`), reviews them
   (`flow-reviewer`), fixes serious findings, and **saves its flows as soon as it finishes**.
4. **Combined coverage check (code).** Over all groups' flows: every operation used, every path id
   received from an earlier step, every lifecycle transition and every business rule covered. Gaps go
   back to Claude (up to two rounds) and the resulting flows are saved under *Coverage gaps*.

Every Claude call may run up to 60 minutes. Each flow shows the area it was designed for.

The page shows the domain summary, coverage, the reviewer's verdict and every flow; each flow opens
as a step timeline showing which values pass between steps. Review works like unit cases.
Approved flows appear on the **Scripts** page and become one chained Playwright test per flow
(`tests/api/flows/*.flow.spec.ts`) with a `test.step` per step and cleanup in `finally`.

## Scripts

Open **Scripts**, select endpoints that have approved unit cases and click **Generate scripts**.
This needs a confirmed framework profile, your framework folder and a connected computer. For each
endpoint, on your computer:

1. **Write (Claude, `script-writer`).** Claude runs inside your framework folder with read-only
   tools, studies the example tests, fixtures and clients from the profile, and returns one spec file
   per endpoint (`playwright-script-standards` skill). Each test title starts with its case code
   (`TC-0005 ...`).
2. **Safety checks (code).** The path must be a `.spec.ts`/`.test.ts` file inside the framework;
   files not created by API Test Studio are never overwritten; forbidden code (file system, child
   processes, `eval`, `test.only`, fixed waits, `@ts-ignore`) and missing case codes are rejected.
3. **Checks (your tools).** The file is written, then TypeScript (`tsc --noEmit`, errors in this file
   only), ESLint (if configured) and `playwright test --list` (all cases discovered) run with a
   minimal environment. **Tests are never executed.** Checks are skipped until `npm install` has run.
4. **Fix (Claude, `script-fixer`).** Failed checks go back to Claude, up to two rounds.

`.api-test-studio/manifest.json` in your framework records which files the tool manages. The
portal shows the code, the diff against the previous version, the check results, required
environment variables and which approved cases are in the file. Editing or approving more cases
marks the endpoint **Needs update**. Review the changes in source control and run the tests
yourself (`npx playwright test`).

## Export and regeneration

- **Export** (Unit / Flow test cases pages): Excel workbook with a *Unit cases* and a *Flow cases*
  sheet (all or approved only), or CSV per module. Cells starting with `=`, `+`, `-` or `@` are
  neutralised in CSV.
- **Regenerate** (inside a case or flow): Claude rewrites that one case with the QA's optional
  instruction, the *Needs changes* comment and the reviewer's notes. Flows may gain, lose or reorder
  steps; the data flow is validated before it is saved. If someone edits the case meanwhile, the
  regenerated version is discarded.
- **Generate missing scripts** (Scripts page): one click for every endpoint and flow whose approved
  cases have no script yet or changed since the last one.

## Project layout

| Folder | Contents |
| --- | --- |
| `studio/` | FastAPI server: auth, projects, roles, specs, framework, helper/job exchange |
| `helper/` | Local Helper CLI: pairing, heartbeat, job runner, Claude CLI wrapper |
| `contracts/` | Pydantic models shared by server and helper (e.g. `FrameworkProfile`) |
| `claude/agents/`, `claude/skills/` | Agent prompts and skills loaded into each Claude run |
| `web/` | React + TypeScript + Tailwind UI |
| `examples/` | Sample spec and sample Playwright framework |
| `tests/` | Server and helper tests |

## Development

```powershell
./.venv/Scripts/python.exe -m pytest -q          # server + helper tests
cd web; npm run dev                               # UI with hot reload (proxies /api to :8000)
```

## Measuring prompt changes

`evals/run_eval.py` runs the real unit, flow and role pipelines on a fixed API (`evals/petstore.yaml`
and `evals/petstore-roles.csv`, or your own with `--spec` / `--roles`) with your signed-in Claude Code,
scores the results with the portal's code checks (coverage, code-check failures, reviewer findings,
tokens, time) and compares them with the previous run. It spends Claude usage, so run it when you change
an agent or skill:

```
.venv\Scripts\python -m evals.run_eval --modules unit,flows --endpoints 3 --model sonnet
```

Reports are saved in `evals/results/` (not committed).
