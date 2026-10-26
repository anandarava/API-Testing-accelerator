# API Test Studio — guide for QA teams

API Test Studio designs API test cases from your OpenAPI / Swagger file, lets your team review them,
and writes the approved ones as Playwright + TypeScript tests in **your own framework**. Claude does
the designing and writing on **your computer** with **your Claude account**; you stay in control of
what gets approved.

---

## 1. One-time setup (10 minutes)

**You need:** the portal address from your lead (e.g. `http://192.168.1.20:8000`), Claude Code
installed and signed in (`claude auth login`), Python 3.12+, Node.js 20+, and a local clone of your
team's Playwright framework repository with `npm install` already run.

1. **Create your account.** Open the portal and click *Create an account*. Use your work email.
2. **Get access.** Ask your lead to add you to the project. You appear as **Employee** (or **Lead**).
3. **Connect your computer.** Click **Connect your computer** in the top-right corner and follow the
   three steps. Keep the helper terminal open while you work. The chip turns green:
   *Computer connected · Claude Pro/Max*.
4. **Point to your framework.** Open the project → **Framework** → paste the full path of your local
   framework folder → **Save folder**. Everyone saves their own path.

5. **Choose your Claude model (optional).** The **Model** menu in the top bar sets the model for the
   jobs you start: *Account default*, or a family (Fable, Opus, Sonnet, Haiku) with either **Latest**
   (always the newest version) or a fixed version such as *Opus 5.5*, *Opus 5* or *Opus 4.8*. A newer
   version not in the list can be typed under *Other model ID* (e.g. `claude-opus-4-8`). Which ones you
   can use depends on your Claude plan; if a model is not available, the job stops with a clear message. Running jobs keep the model they started with. The menu, running jobs and
   finished jobs show the model that actually ran (e.g. *Sonnet 5.5*; Claude Code may also use Haiku
   for small helper tasks). The model you pick runs every step of the job: design, writing and review.

6. **Use your team's local AI server instead of Claude (optional).** Copy `.env.example` to `.env` in the
   `api-test-studio` folder, fill in the server address and API key your lead gives you, and restart the
   helper. The **Model** menu then has a **Local server** tab: pick a model there to run your jobs on it,
   or switch back to the **Claude** tab at any time. Local models are slower and less thorough than Claude,
   so review their cases and scripts with extra care.

The first person on a project also clicks **Analyze framework** once, reviews the profile Claude
writes (test folder, fixtures, auth, conventions) and clicks **Looks right, confirm**.

---

## 2. Everyday workflow

```
Upload spec → Generate cases → Review & approve → Generate scripts → Review in git → Run tests
```

### Upload or update the API spec
**APIs** → drop the OpenAPI/Swagger JSON or YAML. Uploading a new version shows what was added,
changed or removed. Cases written for older versions are marked *Outdated*.

### Unit test cases (one endpoint at a time)
**Unit test cases** → tick the endpoints → **Generate**. For each endpoint Claude:
1. lists every scenario a senior tester would cover (validation, boundaries, formats, auth, errors,
   business rules, security);
2. is checked automatically against the spec — the **Spec requirements** card must read e.g. 18/18;
3. writes each case with concrete data, expected status and checks;
4. is reviewed by a second Claude agent, which also fixes serious problems before you see them.

Each endpoint takes a few minutes. You can leave the page; results appear as endpoints finish.

### Flow test cases (the whole API)
**Flow test cases** → **Analyze APIs & design flows**. Claude explains how the API works as a
business (entities, lifecycles, rules) and designs end-to-end journeys — happy paths, state changes,
negative journeys — with as many steps as each journey needs. Open a flow to see its **step
timeline** and which values pass from one step to the next. This takes 10–30 minutes.

Besides journeys and status changes, Claude checks the edge cases of each business rule by its kind: duplicates, competing requests, idempotent retries, locked records (a signed or completed record refuses changes), wrong-order status changes, money totals, side effects (what else changes is read back) and webhooks. A requirement only counts as covered when the flow really contains the proof, for example a refused step for a uniqueness rule. Rules that need test support (a test clock, a signing secret) are marked *Confirm results* with a note saying what is needed.

If the design stops part-way (for example when your Claude usage or spend limit is reached), finished
areas stay saved. Click **Continue generation** after the limit resets: Claude designs only the remaining
areas and then checks coverage across all flows. **Redesign flows** starts over instead.

### Role test cases (who may do what)
**Role test cases** → upload your **roles file**: the roles of your application and what each may and may
not do (Excel, CSV, JSON, YAML, Markdown, text or Word). No passwords: credentials stay in your
framework's `.env`, and files with passwords or tokens are refused. Without a roles file, no role test
cases are generated.

1. **Analyze roles file**: Claude maps your roles onto every endpoint and builds the **permission grid**
   (Allowed / Own only / Denied / ? not decided). Open the grid and click a cell to correct it; roles left
   at **?** are not tested.
2. Tick endpoints → **Generate**. For each endpoint Claude writes: a case per allowed role, one case for
   all roles that must be refused (with a read-back proving nothing changed), and for "own only" roles a
   second-user case (user B cannot reach user A's record). **Role checks** shows which cases prove each
   permission; it is computed from the cases, not from Claude's claims.
3. Review and approve as usual. Use the **role filter** to see one role's cases across endpoints.
4. **Scripts** → *Role tests* writes one `.roles.spec.ts` per endpoint. Each role signs in with its
   variables from your framework's `.env` (for example `CLERK_USERNAME` / `CLERK_PASSWORD`, and
   `CUSTOMER_2_...` for the second user); tests of a role whose variables are not set are skipped.

### Reviewing — what to look for
Open a case or flow and check:

- **Is the expected result right for our API?** Cases marked **Confirm results** contain an outcome
  the spec does not state. Check with the developer or API owner before approving.
- **Is the data realistic?** Values like `{{unique.name}}` or `{{steps.S1.petId}}` are filled in when
  the test runs; that is expected.
- **AI reviewer notes** — read them; minor notes are suggestions.

Then choose:

| Action | When |
| --- | --- |
| **Approve** | The case is correct. Only approved cases become scripts. |
| **Needs changes** | Something is wrong. Write what — your comment is shown on the case. |
| **Regenerate** | Let Claude rewrite it. Add an instruction such as *"also check the error code"*. A *Needs changes* comment is included automatically. |
| **Edit** | Fix it yourself. Editing an approved case sends it back to review. |
| **Reject** | The case is not useful. |

Select several cases with the checkboxes to approve or reject in bulk.

### Generate scripts
**Scripts** → **Generate missing scripts**, or tick specific endpoints/flows → **Generate**.
Claude reads your framework, writes one spec file per endpoint (and one per flow) in your team's
style, and the helper checks it with **TypeScript**, **ESLint** and **Playwright test discovery**.
**Nothing is run against the API.**

Open a row to see the code, the changes since last time, the check results and any environment
variables you need (for example `API_TOKEN_EXPIRED`). Status *Needs update* means approved cases
changed — generate again.

### Review and run
The files are written into your local framework folder. Review them in your IDE / git like any other
change, set the environment variables, then run them yourself:

```bash
npx playwright test tests/api
```

Commit and raise a pull request as your team normally does.

### Export for sign-off
**Unit test cases** or **Flow test cases** → **Export** → *Excel — approved only* gives a workbook
with one sheet for unit cases and one for flows, ready to share.

---

## 3. Roles

| | Lead | Employee |
|---|:-:|:-:|
| Upload specs, generate, review, approve, regenerate, export, generate scripts | ✅ | ✅ |
| Edit the framework profile | ✅ | ✅ |
| Add / remove members, change roles, rename or delete the project | ✅ | ❌ |

---

## 4. Good habits

- **Generate in batches.** Each endpoint uses several Claude calls; on a Pro plan, do a few endpoints
  at a time. If you hit your usage limit, finished endpoints are kept — continue later.
- **Divide the review.** Agree in the team who reviews which endpoints; the **Activity** page shows who
  approved what.
- **Keep the spec current.** Re-upload when the API changes, then regenerate outdated endpoints.
  Approved cases are kept.
- **Never put real passwords or tokens in cases.** Credentials come from environment variables.

## 5. Troubleshooting

| Problem | Fix |
| --- | --- |
| Chip says *Connect your computer* | Start the helper: `.venv\Scripts\python -m helper start` in the `api-test-studio` folder. |
| *Claude not signed in* | Run `claude auth login`, then restart the helper. |
| *Local server not reachable* | Check `STUDIO_LLM_BASE_URL` and `STUDIO_LLM_API_KEY` in `.env`, that you are on the office network or VPN, then restart the helper. `python -m helper status` shows the exact error. |
| *not available for your API key* | Your local-server key cannot use that model. Pick another one under **Local server** in the Model menu. |
| *too long for the local model's context window* | Generate fewer endpoints at once, raise `STUDIO_LLM_CONTEXT` if the server allows, or run this job on Claude. |
| Job waits at *Waiting for the Local Helper* | The helper runs jobs for the person who started them — start **your** helper. |
| *Different versions* message in the helper | Update your copy of API Test Studio to the same version as the portal. |
| Script checks show *skipped* | Run `npm install` in your framework folder. |
| *already exists and was not created by API Test Studio* | A hand-written file has the suggested name. Rename it or ask Claude for a different path. |
| *usage limit or spend limit has been reached* | Wait for the reset (or ask your admin to raise the limit), then click **Continue generation** on the Flow page. Choosing Sonnet in the Model menu uses less of your limit. |
| A result was rejected by the portal | A copy is saved in `%USERPROFILE%\.api-test-studio\helper\unsent-results`; send it to your lead. |
